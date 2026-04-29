"""
Built-in llama.cpp LLM provider for fully offline GGUF operation.

Manages a llama-cpp-python server subprocess, downloads GGUF models
from HuggingFace on first use, and delegates inference to the
OpenAI-compatible local API.

Design invariants:
  - One shared server process per Python process (singleton, lock-protected).
  - Lazy init: model download + server start deferred to first call.
  - Auto-restart: server death detected on every call, restart transparent.
  - Port-race retry: up to _MAX_PORT_RETRIES attempts with fresh port.
  - atexit cleanup: subprocess killed on parent exit, including abnormal exits.
  - Log file always closed: try/finally in start(), stop().
  - Model-mismatch guard: config change without restart raises clear error.
  - No hardcoded hardware flags: flash_attn off by default (requires CUDA/Metal).

Usage:
    ATULYA_API_LLM_PROVIDER=llamacpp
    ATULYA_API_LLAMACPP_MODEL_PATH=~/.atulya/models/your-model.gguf
    ATULYA_API_LLAMACPP_GPU_LAYERS=-1         # -1 = all on GPU (Metal/CUDA)
    ATULYA_API_LLAMACPP_CONTEXT_SIZE=8192
    ATULYA_API_LLAMACPP_FLASH_ATTN=false      # enable only on CUDA/Metal hardware
    ATULYA_API_LLAMACPP_LORA_PATH=...         # LoRA adapter for fine-tuned models

Install:
    pip install 'atulya-api[local-llm]'

"""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import shlex
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ..llm_interface import LLMInterface
from ..response_models import LLMToolCallResult

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Default GGUF model (auto-downloaded on first use when no path set)
# ------------------------------------------------------------------
DEFAULT_LLAMACPP_HF_REPO = "bartowski/google_gemma-4-E2B-it-GGUF"
DEFAULT_LLAMACPP_HF_FILENAME = "google_gemma-4-E2B-it-Q4_K_M.gguf"
DEFAULT_LLAMACPP_MODEL_ALIAS = "gemma-4-e2b-it"

MODELS_DIR = Path.home() / ".atulya" / "models"

# ------------------------------------------------------------------
# Defaults — overridden by config/env; module-local so this file is
# self-contained (config.py values are read in llm_wrapper.py).
# ------------------------------------------------------------------
DEFAULT_LLAMACPP_GPU_LAYERS: int = -1  # -1 = all layers on GPU
DEFAULT_LLAMACPP_CONTEXT_SIZE: int = 8192
DEFAULT_LLAMACPP_CHAT_FORMAT: str | None = None  # auto-detect from GGUF metadata
DEFAULT_LLAMACPP_NO_GRAMMAR: bool = False
DEFAULT_LLAMACPP_EXTRA_ARGS: str | None = None
# Hardware-safety defaults: off until operator opts in.
DEFAULT_LLAMACPP_FLASH_ATTN: bool = False
DEFAULT_LLAMACPP_N_BATCH: int = 512  # safe for <8 GB VRAM
DEFAULT_LLAMACPP_VERBOSE: bool = False

# ------------------------------------------------------------------
# Singleton server — shared across all LlamaCppLLM instances so that
# retain/reflect/consolidation each reuse the same subprocess.
# ------------------------------------------------------------------
_shared_server: "LlamaCppServer | None" = None
_shared_model_path: "Path | None" = None  # tracks which model the singleton is serving
_shared_server_lock = asyncio.Lock()
_atexit_registered: bool = False

# Port race: window between _find_free_port() releasing port and subprocess binding it.
# Retry with a fresh port on EADDRINUSE pattern in the server startup log.
_MAX_PORT_RETRIES = 3


def _find_free_port() -> int:
    """Bind to port 0 and return the OS-assigned free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _download_default_model() -> Path:
    """Download the default GGUF from HuggingFace if not already cached."""
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        raise ImportError(
            "huggingface-hub is required for automatic model download. "
            "Install with: pip install 'atulya-api[local-llm]'"
        ) from None

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    target = MODELS_DIR / DEFAULT_LLAMACPP_HF_FILENAME
    if target.exists():
        logger.info("[VALID] Using cached GGUF model: %s", target)
        return target

    logger.info(
        "[INFO] Downloading %s from %s (~3.5 GB, first-run only)...",
        DEFAULT_LLAMACPP_HF_FILENAME,
        DEFAULT_LLAMACPP_HF_REPO,
    )
    downloaded = hf_hub_download(
        repo_id=DEFAULT_LLAMACPP_HF_REPO,
        filename=DEFAULT_LLAMACPP_HF_FILENAME,
        local_dir=str(MODELS_DIR),
    )
    logger.info("[VALID] GGUF model downloaded: %s", downloaded)
    return Path(downloaded)


def _resolve_model_path(model_path: str | None) -> Path:
    """
    Resolve model path to an absolute Path.

    - Explicit path: validated to exist, raises FileNotFoundError otherwise.
    - None: auto-download default model.
    """
    if model_path:
        p = Path(model_path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(
                f"[ERROR] GGUF model not found: {p}\n"
                "Set ATULYA_API_LLAMACPP_MODEL_PATH to a valid .gguf file, "
                "or remove the setting to auto-download the default model."
            )
        return p
    return _download_default_model()


def _register_atexit_cleanup() -> None:
    """
    Register a synchronous atexit handler to terminate the server subprocess.

    Uses the module-level global reference directly (no weakref needed since
    the singleton lives for the process lifetime). Safe to call multiple times
    — registered exactly once per process via _atexit_registered flag.
    """
    global _atexit_registered
    if _atexit_registered:
        return
    _atexit_registered = True

    def _cleanup() -> None:
        server = _shared_server
        if server is None or server._process is None:
            return
        pid = server._process.pid
        try:
            server._process.terminate()
            server._process.wait(timeout=5)
            logger.info("[VALID] atexit: llama.cpp server (pid=%d) terminated", pid)
        except subprocess.TimeoutExpired:
            try:
                server._process.kill()
                server._process.wait(timeout=3)
            except Exception:
                pass
        except Exception as exc:
            logger.debug("[DEBUG] atexit cleanup error: %s", exc)

    atexit.register(_cleanup)


class LlamaCppServer:
    """
    llama-cpp-python OpenAI-compatible HTTP server as a managed subprocess.

    Lifecycle: __init__ → start() → (inference calls) → stop()

    Critical design notes:
    - start() always cleans up (process + log file) on any exception.
    - _is_alive() is the canonical liveness check — poll() is None when running.
    - _read_log_tail() never raises; used for diagnostics in error messages.
    - All attributes initialized in __init__ to safe defaults — avoids
      AttributeError in stop()/_read_log_tail() if start() fails early.
    """

    def __init__(
        self,
        model_path: Path,
        port: int,
        gpu_layers: int = -1,
        context_size: int = 8192,
        chat_format: str | None = None,
        flash_attn: bool = False,
        n_batch: int = 512,
        verbose: bool = False,
        lora_path: str | None = None,
        extra_args: str | None = None,
    ) -> None:
        self.model_path = model_path
        self.port = port
        self.gpu_layers = gpu_layers
        self.context_size = context_size
        self.chat_format = chat_format
        self.flash_attn = flash_attn
        self.n_batch = n_batch
        self.verbose = verbose
        self.lora_path = lora_path
        self.extra_args = extra_args
        self._process: subprocess.Popen | None = None
        self._log_path: Path = MODELS_DIR / "llamacpp_server.log"
        self._log_file = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def _is_alive(self) -> bool:
        """Return True if the subprocess is still running."""
        return self._process is not None and self._process.poll() is None

    def _build_cmd(self) -> list[str]:
        """Construct the llama-cpp-python server CLI command."""
        cmd = [
            sys.executable,
            "-m",
            "llama_cpp.server",
            "--model",
            str(self.model_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
            "--n_gpu_layers",
            str(self.gpu_layers),
            "--n_ctx",
            str(self.context_size),
            "--n_batch",
            str(self.n_batch),
            # Silence model-tensor loading noise in production logs.
            "--verbose",
            "true" if self.verbose else "false",
        ]
        # Flash attention: requires CUDA/Metal — opt-in only, not a safe default.
        if self.flash_attn:
            cmd.extend(["--flash_attn", "true"])
        # Chat format: only pass if explicitly set; GGUF metadata auto-detects it.
        if self.chat_format:
            cmd.extend(["--chat_format", self.chat_format])
        # LoRA / fine-tuned adapter path.
        if self.lora_path:
            cmd.extend(["--lora_path", self.lora_path])
        # Operator escape hatch for any other llama.cpp server flags.
        # shlex.split preserves quoted arguments (e.g. paths with spaces).
        if self.extra_args:
            cmd.extend(shlex.split(self.extra_args))
        return cmd

    async def start(self) -> None:
        """
        Start the subprocess and block until the server is ready.

        Guarantees: if this method raises, both the subprocess and log file are
        cleaned up before the exception propagates — no resource leaks.
        """
        cmd = self._build_cmd()
        logger.info("[INFO] Starting llama.cpp server on port %d", self.port)
        logger.debug("[DEBUG] Command: %s", " ".join(cmd))

        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        # Open log BEFORE Popen so the fd is tracked for cleanup in the except block.
        self._log_file = open(self._log_path, "w")
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=self._log_file,
                # New process group → can kill the entire tree on cleanup.
                preexec_fn=os.setsid if hasattr(os, "setsid") else None,
            )
            await self._wait_for_ready()
        except Exception:
            # Deterministic cleanup — never leak subprocess or log fd.
            if self._process is not None:
                try:
                    self._process.kill()
                    self._process.wait(timeout=5)
                except Exception as kill_exc:
                    logger.debug("[DEBUG] kill during failed start: %s", kill_exc)
                self._process = None
            if self._log_file is not None:
                self._log_file.close()
                self._log_file = None
            raise

    async def _wait_for_ready(self, timeout: float = 120.0) -> None:
        """
        Poll /v1/models until the server accepts connections or timeout expires.

        Checks for early process death (OOM, bad model, EADDRINUSE) every
        iteration so failures surface quickly with a useful log snippet.
        """
        import httpx

        start = time.monotonic()
        url = f"http://127.0.0.1:{self.port}/v1/models"
        last_log = start

        while time.monotonic() - start < timeout:
            # Early exit: process died (OOM, bad model, port conflict, etc.)
            if self._process is not None and self._process.poll() is not None:
                log = self._read_log_tail()
                raise RuntimeError(
                    f"[ERROR] llama.cpp server exited (code {self._process.returncode}) "
                    f"during startup.\n--- server log tail ---\n{log}"
                )
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(url, timeout=5.0)
                    if resp.status_code == 200:
                        elapsed = time.monotonic() - start
                        logger.info("[VALID] llama.cpp server ready on port %d (%.1fs)", self.port, elapsed)
                        return
            except (httpx.ConnectError, httpx.TimeoutException, httpx.ConnectTimeout):
                pass

            now = time.monotonic()
            if now - last_log > 15:
                logger.info("[INFO] Waiting for llama.cpp to load model... (%ds elapsed)", int(now - start))
                last_log = now
            await asyncio.sleep(1.0)

        raise TimeoutError(
            f"[ERROR] llama.cpp server did not become ready within {timeout}s.\n"
            "Check model compatibility and available memory.\n"
            f"--- server log tail ---\n{self._read_log_tail()}"
        )

    def _read_log_tail(self, chars: int = 2000) -> str:
        """Read the tail of the server log for diagnostics. Never raises."""
        try:
            return self._log_path.read_text()[-chars:]
        except Exception:
            return "(log not available)"

    async def stop(self) -> None:
        """
        Terminate the subprocess gracefully (SIGTERM → SIGKILL fallback).

        Safe to call on a server that was never started or already stopped.
        Always closes the log file descriptor in the finally block.
        """
        if self._process is None:
            return

        pid = self._process.pid
        logger.info("[INFO] Stopping llama.cpp server (pid=%d)...", pid)
        try:
            if hasattr(os, "killpg"):
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass  # Already dead — let wait() confirm
            else:
                self._process.terminate()

            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                # Escalate: SIGKILL the entire process group
                try:
                    if hasattr(os, "killpg"):
                        os.killpg(os.getpgid(pid), signal.SIGKILL)
                    else:
                        self._process.kill()
                except ProcessLookupError:
                    pass
                self._process.wait(timeout=5)

        except (ProcessLookupError, OSError) as exc:
            logger.debug("[DEBUG] stop() process signal error: %s", exc)
        finally:
            self._process = None
            if self._log_file is not None:
                self._log_file.close()
                self._log_file = None
            logger.info("[VALID] llama.cpp server stopped (was pid=%d)", pid)


class LlamaCppLLM(LLMInterface):
    """
    Atulya built-in GGUF provider.

    Manages a shared llama-cpp-python server subprocess and delegates
    all inference calls to OpenAICompatibleLLM pointing at the local API.

    Safety guarantees:
    - Fast-path liveness check before acquiring the lock — no contention on
      every request once the server is healthy.
    - Dead-server recovery: if the process dies (OOM/signal) between requests
      the singleton is reset and a new server is started automatically.
    - Model-mismatch guard: raises RuntimeError if a second instance requests
      a different model than the running singleton — prevents silent wrong-model
      inference.
    - Port-race retry: up to _MAX_PORT_RETRIES attempts with a fresh port each
      time, guarding against the TOCTOU race in _find_free_port().
    - no_grammar=True disables JSON grammar enforcement (faster, less reliable).
    """

    def __init__(
        self,
        provider: str,
        api_key: str,
        base_url: str,
        model: str,
        reasoning_effort: str = "low",
        model_path: str | None = None,
        gpu_layers: int = DEFAULT_LLAMACPP_GPU_LAYERS,
        context_size: int = DEFAULT_LLAMACPP_CONTEXT_SIZE,
        chat_format: str | None = DEFAULT_LLAMACPP_CHAT_FORMAT,
        flash_attn: bool = False,
        n_batch: int = 512,
        verbose: bool = False,
        lora_path: str | None = None,
        no_grammar: bool = DEFAULT_LLAMACPP_NO_GRAMMAR,
        extra_args: str | None = DEFAULT_LLAMACPP_EXTRA_ARGS,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            provider=provider,
            api_key=api_key or "llamacpp",
            base_url=base_url or "",
            model=model or DEFAULT_LLAMACPP_MODEL_ALIAS,
            reasoning_effort=reasoning_effort,
        )
        self._model_path_str = model_path
        self._gpu_layers = gpu_layers
        self._context_size = context_size
        self._chat_format = chat_format
        self._flash_attn = flash_attn
        self._n_batch = n_batch
        self._verbose = verbose
        self._lora_path = lora_path
        self._no_grammar = no_grammar
        self._extra_args = extra_args
        self._server: LlamaCppServer | None = None
        self._delegate: Any = None  # OpenAICompatibleLLM, created after server starts
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        """
        Download model + start shared server on first use.

        Fast path (no lock): already initialized and server still alive.
        Slow path (lock): first call, dead server, or model mismatch.
        """
        global _shared_server, _shared_model_path

        from .openai_compatible_llm import OpenAICompatibleLLM

        # --- Fast path: server healthy, skip lock ---
        if self._initialized and self._delegate is not None:
            if _shared_server is not None and _shared_server._is_alive():
                return
            # Server died between calls — fall through to slow path
            logger.warning("[WARNING] llama.cpp server died unexpectedly; recovering...")
            self._initialized = False
            self._delegate = None
            self._server = None

        async with _shared_server_lock:
            # Double-checked locking: another coroutine may have recovered the server.
            if _shared_server is not None and _shared_server._is_alive():
                # Server healthy — validate model consistency
                requested_model = _resolve_model_path(self._model_path_str)
                if _shared_model_path is not None and requested_model != _shared_model_path:
                    raise RuntimeError(
                        f"[ERROR] Model mismatch: running server uses '{_shared_model_path}' "
                        f"but this instance requests '{requested_model}'. "
                        "Use a single LlamaCppLLM instance per process or stop the server first."
                    )
                self._server = _shared_server
                self._delegate = OpenAICompatibleLLM(
                    provider="llamacpp",
                    api_key="llamacpp",
                    base_url=self._server.base_url,
                    model=self.model,
                    reasoning_effort=self.reasoning_effort,
                )
                self._initialized = True
                return

            # --- Dead server recovery: stop before re-starting ---
            if _shared_server is not None and not _shared_server._is_alive():
                logger.warning("[WARNING] Cleaning up dead llama.cpp server singleton...")
                await _shared_server.stop()
                _shared_server = None
                _shared_model_path = None

            # --- First start or post-recovery restart ---
            model_path = _resolve_model_path(self._model_path_str)
            logger.info("[INFO] Using GGUF model: %s", model_path)

            server = await self._start_server_with_retry(model_path)
            _shared_server = server
            _shared_model_path = model_path
            _register_atexit_cleanup()

            if self._no_grammar:
                logger.info("[INFO] JSON grammar enforcement disabled (ATULYA_API_LLAMACPP_NO_GRAMMAR=true)")

            self._server = _shared_server
            self._delegate = OpenAICompatibleLLM(
                provider="llamacpp",
                api_key="llamacpp",
                base_url=self._server.base_url,
                model=self.model,
                reasoning_effort=self.reasoning_effort,
            )
            self._initialized = True

    async def _start_server_with_retry(self, model_path: Path) -> LlamaCppServer:
        """
        Attempt to start LlamaCppServer up to _MAX_PORT_RETRIES times.

        Retries only on EADDRINUSE (port race); propagates all other errors
        immediately to avoid masking real problems (bad model, OOM, etc.).
        """
        last_exc: Exception = RuntimeError("unreachable")
        for attempt in range(1, _MAX_PORT_RETRIES + 1):
            port = _find_free_port()
            server = LlamaCppServer(
                model_path=model_path,
                port=port,
                gpu_layers=self._gpu_layers,
                context_size=self._context_size,
                chat_format=self._chat_format,
                flash_attn=self._flash_attn,
                n_batch=self._n_batch,
                verbose=self._verbose,
                lora_path=self._lora_path,
                extra_args=self._extra_args,
            )
            try:
                await server.start()
                return server
            except RuntimeError as exc:
                last_exc = exc
                log = server._read_log_tail()
                if "address already in use" in log.lower() or "EADDRINUSE" in log:
                    logger.warning(
                        "[WARNING] Port %d taken (attempt %d/%d); retrying with new port...",
                        port,
                        attempt,
                        _MAX_PORT_RETRIES,
                    )
                    continue
                raise  # Non-recoverable error — do not retry
        raise RuntimeError(
            f"[ERROR] Failed to start llama.cpp server after {_MAX_PORT_RETRIES} port-retry attempts. "
            f"Last error: {last_exc}"
        )

    async def verify_connection(self) -> None:
        """Verify the server is running and can generate text."""
        await self._ensure_initialized()
        await self._delegate.call(
            messages=[{"role": "user", "content": "Say 'ok'"}],
            max_completion_tokens=10,
            max_retries=2,
            initial_backoff=0.5,
            max_backoff=2.0,
            scope="verification",
        )
        logger.info("[VALID] llama.cpp LLM verification passed")

    async def call(
        self,
        messages: list[dict[str, str]],
        response_format: Any | None = None,
        max_completion_tokens: int | None = None,
        temperature: float | None = None,
        scope: str = "memory",
        max_retries: int = 10,
        initial_backoff: float = 1.0,
        max_backoff: float = 60.0,
        skip_validation: bool = False,
        strict_schema: bool = False,
        return_usage: bool = False,
    ) -> Any:
        await self._ensure_initialized()
        return await self._delegate.call(
            messages=messages,
            response_format=response_format,
            max_completion_tokens=max_completion_tokens,
            temperature=temperature,
            scope=scope,
            max_retries=max_retries,
            initial_backoff=initial_backoff,
            max_backoff=max_backoff,
            skip_validation=skip_validation,
            strict_schema=strict_schema,
            return_usage=return_usage,
        )

    async def call_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_completion_tokens: int | None = None,
        temperature: float | None = None,
        scope: str = "tools",
        max_retries: int = 5,
        initial_backoff: float = 1.0,
        max_backoff: float = 30.0,
        tool_choice: str | dict[str, Any] = "auto",
    ) -> LLMToolCallResult:
        await self._ensure_initialized()
        return await self._delegate.call_with_tools(
            messages=messages,
            tools=tools,
            max_completion_tokens=max_completion_tokens,
            temperature=temperature,
            scope=scope,
            max_retries=max_retries,
            initial_backoff=initial_backoff,
            max_backoff=max_backoff,
            tool_choice=tool_choice,
        )

    async def cleanup(self) -> None:
        """Stop the shared llama.cpp server subprocess."""
        global _shared_server, _shared_model_path

        if self._delegate:
            await self._delegate.cleanup()
            self._delegate = None

        async with _shared_server_lock:
            if _shared_server is not None:
                await _shared_server.stop()
                _shared_server = None
                _shared_model_path = None  # clear so next init can pick any model

        self._server = None
        self._initialized = False
