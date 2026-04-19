"""whatsapp — pair, run, and send messages over WhatsApp.

Drives `sensors.whatsapp.WhatsAppEar` with one of two backends, picked by
`config.whatsapp.backend`:

- `baileys` (default): spawns a local Node bridge (`scripts/whatsapp-bridge`)
  that handles the unofficial WhatsApp Web protocol and exchanges
  newline-delimited JSON over stdout / `POST /send` with our `BaileysBackend`.
- `cloud`: talks straight to the Meta WhatsApp Cloud API. Requires a
  registered Business account; better for production.

Subcommands
-----------
- `whatsapp pair`     — start the bridge with `--pair-only`, print QR, exit
                        once `connection.update == "open"`. Cloud-backend
                        users skip this; their pairing happens in Meta UI.
- `whatsapp start`    — full ingress/egress loop: stimulus -> reflex chain
                        (DMPairing) -> cortex -> Reply motor.
- `whatsapp send`     — one-shot test: open the bridge, POST a message, exit.
                        Useful to verify the bridge is alive without a real
                        peer messaging the bot.
- `whatsapp doctor`   — channel-scoped health subset: bridge command found,
                        session dir present, baileys port reachable.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from cortex import config as config_module

if TYPE_CHECKING:
    from cortex.home import CortexHome

NAME = "whatsapp"
HELP = "Pair, run, and send messages over WhatsApp."

DEFAULT_BRIDGE_PORT = 7732
DEFAULT_BRIDGE_DIR = "scripts/whatsapp-bridge"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def register(subparsers, common_parents) -> None:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=list(common_parents),
        description="Pair, run, and send messages via WhatsApp (Baileys or Cloud API).",
    )
    sub = parser.add_subparsers(dest="whatsapp_command", metavar="<action>")

    p_pair = sub.add_parser("pair", help="Run the Baileys bridge with QR pairing only; exit on success.")
    p_pair.add_argument("--print-qr", action="store_true", default=True, help="Render QR in this terminal.")
    p_pair.add_argument("--no-print-qr", dest="print_qr", action="store_false", help="Suppress QR rendering.")
    p_pair.add_argument("--bridge-dir", default=None, help=f"Override bridge directory (default {DEFAULT_BRIDGE_DIR}).")
    p_pair.add_argument("--bridge-cmd", default=None, help="Override bridge launch command (e.g. 'node bridge.js').")
    p_pair.add_argument("--timeout", type=float, default=180.0, help="Abort if pairing takes longer (seconds).")
    p_pair.add_argument(
        "--reset",
        action="store_true",
        help="Wipe the existing Baileys session before pairing. Use this when a previous "
        "pair attempt left stale creds (you'll see code 401 / 'logged_out' instead of a QR).",
    )
    p_pair.set_defaults(_whatsapp_run=_run_pair)

    p_start = sub.add_parser("start", help="Start the full ingress/egress loop. Ctrl-C to stop.")
    p_start.add_argument("--bridge-dir", default=None)
    p_start.add_argument("--bridge-cmd", default=None)
    p_start.add_argument(
        "--default-allow",
        action="store_true",
        help="Auto-allow every WhatsApp peer (skip DMPairing). DANGEROUS — use only on a private number.",
    )
    p_start.add_argument(
        "--echo",
        action="store_true",
        help="Skip the LLM and echo back. Useful to confirm transport plumbing.",
    )
    p_start.set_defaults(_whatsapp_run=_run_start)

    p_send = sub.add_parser("send", help="Send a one-off message via the bridge (test transport).")
    p_send.add_argument("to", help="Destination JID, e.g. 919999999999@s.whatsapp.net")
    p_send.add_argument("text", help="Message body.")
    p_send.add_argument("--bridge-dir", default=None)
    p_send.add_argument("--bridge-cmd", default=None)
    p_send.add_argument("--timeout", type=float, default=30.0, help="Wait this long for the bridge to come up.")
    p_send.set_defaults(_whatsapp_run=_run_send)

    p_doctor = sub.add_parser("doctor", help="Channel-scoped health checks for WhatsApp.")
    p_doctor.set_defaults(_whatsapp_run=_run_doctor)

    parser.set_defaults(_run=run)


def run(args: argparse.Namespace, *, home: "CortexHome") -> int:
    handler = getattr(args, "_whatsapp_run", None)
    if handler is None:
        # No subcommand: show help and exit 2 like argparse would.
        sys.stderr.write("usage: atulya-cortex whatsapp <pair|start|send|doctor>\n")
        return 2
    try:
        cfg = config_module.load(home)
    except config_module.ConfigError as exc:
        print(f"error: {exc}\nrun `atulya-cortex setup` to seed a fresh config.", file=sys.stderr)
        return 2
    return handler(args, home=home, config=cfg)


# ---------------------------------------------------------------------------
# Resolving the bridge command
# ---------------------------------------------------------------------------


def _resolve_bridge(args: argparse.Namespace, config) -> tuple[list[str], str | None]:
    """Return `(command, cwd)` for spawning the Baileys bridge."""

    if getattr(args, "bridge_cmd", None):
        return _shlex(args.bridge_cmd), None

    bridge_dir = args.bridge_dir or _find_bridge_dir(config.whatsapp.bridge_path)
    if bridge_dir is None:
        return _default_bridge_command(), None

    bridge_path = Path(bridge_dir).expanduser().resolve()
    js = bridge_path / "whatsapp-bridge.js"
    if not js.exists():
        # Fall back to whatever the user passed; bridge spawn will fail loudly.
        return _default_bridge_command(), str(bridge_path)
    return ["node", str(js)], str(bridge_path)


def _find_bridge_dir(configured: str) -> str | None:
    """Locate the bridge directory in obvious places.

    Checks (in order):
    - the configured path as-is (for absolute or CWD-relative paths)
    - relative to CWD
    - relative to the atulya-cortex package root (works for `uv run` from
      the monorepo whether `cwd` is the repo root or the package dir)
    - one level up (monorepo root)
    """

    cortex_root = Path(__file__).resolve().parents[2]  # cortex/cli_commands/.. -> atulya-cortex
    monorepo_root = cortex_root.parent
    candidates = [
        Path(configured),
        Path.cwd() / configured,
        cortex_root / configured,
        monorepo_root / configured,
    ]
    for c in candidates:
        if (c / "whatsapp-bridge.js").exists():
            return str(c.resolve())
    return None


def _default_bridge_command() -> list[str]:
    return ["node", "whatsapp-bridge.js"]


def _shlex(s: str) -> list[str]:
    import shlex

    return shlex.split(s)


def _bridge_env(home: "CortexHome", *, port: int, print_qr: bool, pair_only: bool) -> dict[str, str]:
    env = os.environ.copy()
    env["CORTEX_WA_AUTH_DIR"] = str(home.whatsapp_session_dir)
    env["CORTEX_WA_BRIDGE_PORT"] = str(port)
    env["CORTEX_WA_PRINT_QR"] = "1" if print_qr else "0"
    env["CORTEX_WA_PAIR_ONLY"] = "1" if pair_only else "0"
    return env


# ---------------------------------------------------------------------------
# pair
# ---------------------------------------------------------------------------


def _run_pair(args: argparse.Namespace, *, home: "CortexHome", config) -> int:
    if config.whatsapp.backend != "baileys":
        print(
            "config.whatsapp.backend is not 'baileys'; pairing happens in the Meta UI for the cloud backend.",
            file=sys.stderr,
        )
        return 0

    cmd, cwd = _resolve_bridge(args, config)
    if not _node_available():
        print(
            "error: 'node' not found on PATH; install Node.js >= 18 then `npm i` in scripts/whatsapp-bridge.",
            file=sys.stderr,
        )
        return 2

    if getattr(args, "reset", False):
        wiped = _wipe_session_dir(home.whatsapp_session_dir)
        print(f"reset: wiped {wiped} session file(s) from {home.whatsapp_session_dir}")
    elif _session_has_creds(home.whatsapp_session_dir):
        print(
            f"note: session already exists at {home.whatsapp_session_dir} — no QR will appear unless\n"
            "      you pass --reset to clear it (use this if your last pair attempt failed mid-way).",
            file=sys.stderr,
        )

    home.whatsapp_session_dir.mkdir(parents=True, exist_ok=True)
    env = _bridge_env(home, port=DEFAULT_BRIDGE_PORT, print_qr=args.print_qr, pair_only=True)
    print("Spawning Baileys bridge for pairing. Open WhatsApp -> Linked Devices -> scan the QR.")
    return asyncio.run(_pair_loop(cmd, cwd=cwd, env=env, timeout=args.timeout))


def _session_has_creds(session_dir: Path) -> bool:
    return (session_dir / "creds.json").exists()


def _wipe_session_dir(session_dir: Path) -> int:
    """Remove the contents of a Baileys session directory and return the
    number of files wiped. We delete files (not the directory itself) so
    the bridge's `mkdir -p` invariant still holds."""

    if not session_dir.exists():
        return 0
    count = 0
    for entry in session_dir.iterdir():
        try:
            if entry.is_dir():
                import shutil as _shutil

                _shutil.rmtree(entry)
            else:
                entry.unlink()
            count += 1
        except OSError as exc:
            logger.warning("could not remove %s: %s", entry, exc)
    return count


async def _pair_loop(cmd: list[str], *, cwd: str | None, env: dict[str, str], timeout: float) -> int:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
    )

    async def _pump(stream, prefix: str) -> None:
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                return
            text = line.decode("utf-8", "replace").rstrip()
            # JSON status lines get the `[bridge]` tag; QR rows / blank lines
            # render unprefixed so the scanner code stays readable.
            if text.startswith("{") or text.startswith("["):
                sys.stderr.write(f"[{prefix}] {text}\n")
            else:
                sys.stderr.write(f"{text}\n")

    pump_out = asyncio.create_task(_pump(proc.stdout, "bridge"))
    pump_err = asyncio.create_task(_pump(proc.stderr, "bridge"))

    try:
        rc = await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        print(f"timed out after {timeout}s; killing bridge", file=sys.stderr)
        proc.kill()
        await proc.wait()
        rc = 124
    finally:
        for t in (pump_out, pump_err):
            t.cancel()
    return rc


# ---------------------------------------------------------------------------
# start (full loop)
# ---------------------------------------------------------------------------


def _run_start(args: argparse.Namespace, *, home: "CortexHome", config) -> int:
    if config.whatsapp.backend == "cloud":
        print(
            "the cloud backend has no local loop to start; configure the gateway in batch E and point Meta at it.",
            file=sys.stderr,
        )
        return 2

    if not _node_available():
        print("error: 'node' not found on PATH; install Node.js >= 18.", file=sys.stderr)
        return 2

    cmd, cwd = _resolve_bridge(args, config)
    home.whatsapp_session_dir.mkdir(parents=True, exist_ok=True)
    env = _bridge_env(home, port=DEFAULT_BRIDGE_PORT, print_qr=False, pair_only=False)

    try:
        return asyncio.run(_full_loop(home, config, cmd=cmd, cwd=cwd, env=env, args=args))
    except KeyboardInterrupt:
        return 130


async def _full_loop(
    home: "CortexHome",
    config,
    *,
    cmd: list[str],
    cwd: str | None,
    env: dict[str, str],
    args: argparse.Namespace,
) -> int:
    # Local imports keep `--help` snappy and let unit tests stub modules.
    from brainstem import Allowlist, ReflexChain, Router
    from brainstem.reflexes import DMPairing
    from cortex._runtime import build_cortex_from_config, build_language_from_config, pair_pending_message
    from motors import Reply
    from sensors.whatsapp import BaileysBackend, WhatsAppEar

    def _bridge_log(line: str) -> None:
        # Match the `pair` flow: tag JSON status lines, leave QR / human text
        # bare. Without this drain the OS pipe fills and the Node process
        # eventually blocks; with it the user actually sees what's going on.
        sys.stderr.write(f"[bridge] {line}\n" if line.startswith(("{", "[")) else f"{line}\n")
        sys.stderr.flush()

    backend = BaileysBackend(
        bridge_command=cmd,
        bridge_url=f"http://127.0.0.1:{env['CORTEX_WA_BRIDGE_PORT']}",
        cwd=cwd,
        env=env,
        stderr_sink=_bridge_log,
    )
    ear = WhatsAppEar(backend)

    language = None if args.echo else build_language_from_config(config)
    cortex = build_cortex_from_config(home, config, language=language)

    # Pre-flight: confirm the LLM endpoint is actually reachable BEFORE we
    # wait silently on inbound messages. A misconfigured base_url here used
    # to manifest as "loop runs but every reply silently fails".
    if language is not None:
        ok, detail = await _probe_language(language, config)
        if ok:
            print(f"[llm] {config.model.provider}/{config.model.model} -> {detail}")
        else:
            print(f"[llm] WARNING: {detail}", file=sys.stderr)
            print(
                "      replies will fall through to a friendly error message until the model is reachable.",
                file=sys.stderr,
            )

    async def egress(channel: str, target: str, text: str) -> None:
        # Visibility on outbound: same shape as `[recv]` on inbound, so the
        # operator can read the conversation top-to-bottom in the loop log.
        preview = text if len(text) < 80 else text[:77] + "..."
        sys.stderr.write(f"[send] {channel}: {preview}\n")
        sys.stderr.flush()
        await ear.send(target, text)

    reply = Reply({"whatsapp": egress})

    if args.default_allow:
        reflexes = ReflexChain([Allowlist(allow=["whatsapp:*"], default_decision="allow")])
        logger.warning("--default-allow: every WhatsApp peer will reach the cortex without pairing")
    else:
        pairing = DMPairing(home.pairing_store)
        reflexes = ReflexChain([pairing])

    async def cortex_call(stim, reflex):
        # Catch LLM blow-ups here so we *always* reply something instead of
        # silently dropping the user's message. Without this, an Ollama
        # restart or an LM Studio model swap kills replies until the next
        # cortex restart.
        #
        # `peer_key=stim.sender` opts this peer's transcript into working
        # memory: the cortex loads the recent N turns from
        # `<home>/conversations/whatsapp/<sender>.jsonl` into the system
        # prompt before calling the LLM, then appends both halves of the
        # new exchange after the call. This is what stops the bot from
        # answering "what's my name?" with a hallucinated guess.
        try:
            return await cortex.reflect(stim, reflex=reflex, peer_key=stim.sender)
        except Exception as exc:
            logger.exception("cortex.reflect crashed on %s", stim.channel)
            from cortex.bus import Action, Intent

            return Intent(
                action=Action(
                    kind="reply",
                    payload={"text": f"sorry — my brain hit an error ({type(exc).__name__}). I'll be back soon."},
                ),
                channel=stim.channel,
                sender=stim.sender,
            )

    async def reply_motor(intent):
        return await reply.act(intent)

    router = Router(
        reflexes=reflexes,
        cortex=cortex_call,
        reply_motor=reply_motor,
        pairing_message=pair_pending_message("whatsapp:*", name=config.general.name),
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows / restricted env
            pass

    print(f"WhatsApp loop starting (bridge={cmd[0]}; session={home.whatsapp_session_dir})")
    if args.echo:
        print("[mode] --echo: replies will be deterministic echoes (LLM disabled)")
    else:
        print(f"[mode] LLM: {config.model.provider}/{config.model.model}  (temp={config.model.temperature})")
    if args.default_allow:
        print("[gate] --default-allow: every peer will reach the cortex without pairing approval")
    else:
        print("[gate] DMPairing: new peers get the 'waiting on operator' reply")
        print("       approve with: atulya-cortex pairing approve whatsapp:<jid>")
    await ear.tune_in()
    pump_task = asyncio.create_task(_pump_stimuli(ear, router))
    stop_task = asyncio.create_task(stop.wait())
    try:
        await asyncio.wait({pump_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        pump_task.cancel()
        stop_task.cancel()
        await ear.tune_out()
        if language is not None:
            await language.aclose()
    print("WhatsApp loop stopped.")
    return 0


async def _probe_language(language, config) -> tuple[bool, str]:
    """Tiny LLM round-trip to confirm the configured endpoint is reachable.

    Returns (ok, detail). Used by `whatsapp start` so we fail loudly at boot
    instead of letting every reply silently 500 against a misconfigured base
    url. Cost is one ~5-token completion; fine on local LLMs and trivial on
    paid APIs.
    """

    import time as _time

    started = _time.monotonic()
    try:
        utt = await language.think(
            [
                {"role": "system", "content": "Respond with the single word: ok"},
                {"role": "user", "content": "ping"},
            ],
            temperature=0.0,
            max_tokens=8,
        )
    except Exception as exc:
        return False, f"{config.model.provider}/{config.model.model} unreachable ({type(exc).__name__}: {exc})"
    elapsed_ms = int((_time.monotonic() - started) * 1000)
    text = (getattr(utt, "text", "") or "").strip().splitlines()[0:1]
    preview = text[0] if text else "(empty)"
    return True, f"{preview!r} in {elapsed_ms} ms"


async def _pump_stimuli(ear, router) -> None:
    async for stim in ear.perceive():
        # Surface every inbound message — without this, the loop is silent
        # whether or not anything arrives and the operator can't tell if
        # the cortex is dead, the bridge is wedged, or the contact is just
        # blocked by DMPairing.
        preview = stim.text if len(stim.text) < 80 else stim.text[:77] + "..."
        sys.stderr.write(f"[recv] {stim.channel}: {preview}\n")
        sys.stderr.flush()
        try:
            await router.route(stim)
        except Exception:
            logger.exception("router crashed on stimulus from %s; continuing", stim.channel)


# ---------------------------------------------------------------------------
# send
# ---------------------------------------------------------------------------


def _run_send(args: argparse.Namespace, *, home: "CortexHome", config) -> int:
    if config.whatsapp.backend == "cloud":
        # Cloud backend can send directly without a bridge.
        try:
            return asyncio.run(_send_cloud(config, jid=args.to, text=args.text))
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    if not _node_available():
        print("error: 'node' not found on PATH.", file=sys.stderr)
        return 2

    cmd, cwd = _resolve_bridge(args, config)
    home.whatsapp_session_dir.mkdir(parents=True, exist_ok=True)
    env = _bridge_env(home, port=DEFAULT_BRIDGE_PORT, print_qr=False, pair_only=False)
    try:
        return asyncio.run(_send_via_bridge(cmd, cwd=cwd, env=env, jid=args.to, text=args.text, timeout=args.timeout))
    except KeyboardInterrupt:
        return 130


async def _send_via_bridge(
    cmd: list[str],
    *,
    cwd: str | None,
    env: dict[str, str],
    jid: str,
    text: str,
    timeout: float,
) -> int:
    import httpx

    from sensors.whatsapp import BaileysBackend

    port = env["CORTEX_WA_BRIDGE_PORT"]

    def _bridge_log(line: str) -> None:
        sys.stderr.write(f"[bridge] {line}\n" if line.startswith(("{", "[")) else f"{line}\n")
        sys.stderr.flush()

    backend = BaileysBackend(
        bridge_command=cmd,
        bridge_url=f"http://127.0.0.1:{port}",
        cwd=cwd,
        env=env,
        stderr_sink=_bridge_log,
    )

    async def _drop(_stim):
        return None

    await backend.start(_drop)
    try:
        deadline = asyncio.get_running_loop().time() + timeout
        last_err: Exception | None = None
        while asyncio.get_running_loop().time() < deadline:
            try:
                await backend.send(jid, text)
                print("sent.")
                return 0
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                last_err = exc
                await asyncio.sleep(0.5)
        print(f"error: bridge did not accept POST /send within {timeout}s ({last_err})", file=sys.stderr)
        return 1
    finally:
        await backend.stop()


async def _send_cloud(config, *, jid: str, text: str) -> int:
    from sensors.whatsapp import WhatsAppCloudBackend

    token = os.environ.get(config.whatsapp.access_token_env, "")
    phone_id = os.environ.get(config.whatsapp.phone_number_id_env, "")
    if not token or not phone_id:
        print(
            f"error: ${config.whatsapp.access_token_env} and ${config.whatsapp.phone_number_id_env} must be set.",
            file=sys.stderr,
        )
        return 2
    backend = WhatsAppCloudBackend(access_token=token, phone_number_id=phone_id)
    await backend.send(jid, text)
    print("sent (cloud).")
    return 0


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def _run_doctor(args: argparse.Namespace, *, home: "CortexHome", config) -> int:
    rows: list[tuple[str, str, str]] = []

    if config.whatsapp.backend == "cloud":
        for env_name in (
            config.whatsapp.access_token_env,
            config.whatsapp.phone_number_id_env,
            config.whatsapp.verify_token_env,
        ):
            ok = bool(os.environ.get(env_name, ""))
            rows.append(("env", env_name, "set" if ok else "MISSING"))
    else:
        rows.append(("node", "PATH", "found" if _node_available() else "MISSING"))
        bridge_dir = _find_bridge_dir(config.whatsapp.bridge_path)
        rows.append(("bridge", config.whatsapp.bridge_path, bridge_dir or "MISSING"))
        rows.append(
            ("session", str(home.whatsapp_session_dir), "exists" if home.whatsapp_session_dir.exists() else "absent")
        )
        creds = home.whatsapp_session_dir / "creds.json"
        rows.append(
            (
                "creds.json",
                str(creds),
                "present (paired)" if creds.exists() else "absent (run `atulya-cortex whatsapp pair`)",
            )
        )

    width = max(len(k) for k, _, _ in rows)
    for kind, key, value in rows:
        print(f"  {kind:<{width}}  {key}  ->  {value}")
    bad = any(v.startswith("MISSING") for _, _, v in rows)
    return 1 if bad else 0


def _node_available() -> bool:
    return shutil.which("node") is not None


__all__ = ["NAME", "HELP", "register", "run"]
