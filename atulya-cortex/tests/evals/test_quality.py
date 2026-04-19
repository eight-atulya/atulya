"""tests/evals/test_quality.py — small-LLM correctness eval suite.

25 fixtures across 5 categories (factual, math, code, instruction-following,
reasoning) hammered against one or two model configurations. Pass criterion
per fixture: the assistant's reply contains *any one* of `must_contain`
substrings (case-insensitive) and contains *none* of `must_not_contain`.

Default behavior (CI-friendly):
- Without `CORTEX_EVAL=1` we run **stub mode**: a deterministic in-process
  Language that returns the first `must_contain` substring of each fixture.
  This validates the eval harness end-to-end without an LLM.

Live mode:
- `CORTEX_EVAL=1` plus a `CORTEX_EVAL_PROVIDER` env var (e.g. `lm-studio`,
  `ollama`, `openai`) runs against the live provider. The model is taken
  from `CORTEX_EVAL_MODEL`, defaulting to the provider's default model.

The pass-rate threshold is configurable via `CORTEX_EVAL_MIN_PASS_RATE`
(default 0.7 in live mode, 1.0 in stub mode).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from cortex.language import Language, Provider, Utterance

FIXTURES_PATH = Path(__file__).parent / "fixtures.json"


def _load_fixtures() -> list[dict[str, Any]]:
    return json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))


def _hit(reply: str, fixture: dict[str, Any]) -> bool:
    text = reply.lower()
    must = [s.lower() for s in fixture.get("must_contain", [])]
    must_not = [s.lower() for s in fixture.get("must_not_contain", [])]
    if must and not any(s in text for s in must):
        return False
    if any(s in text for s in must_not):
        return False
    return True


class _StubLanguage:
    """Returns the first must_contain substring; perfect score by construction."""

    def __init__(self, fixtures: list[dict[str, Any]]) -> None:
        self._lookup = {f["user"]: f for f in fixtures}

    async def think(self, messages: list[dict[str, Any]], **kwargs: Any) -> Utterance:
        user_msg = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        fixture = self._lookup.get(user_msg)
        text = (fixture or {}).get("must_contain", [""])[0] or "ok"
        return Utterance(
            text=text,
            provider="stub",
            model="stub",
            elapsed_ms=0.1,
            usage={"total_tokens": 1},
        )


def _provider_from_env() -> Provider | None:
    p = os.environ.get("CORTEX_EVAL_PROVIDER", "").strip().lower()
    if not p:
        return None
    model = os.environ.get("CORTEX_EVAL_MODEL", "").strip() or None
    if p == "lm-studio":
        return Provider.lm_studio(model=model or "google/gemma-3-4b")
    if p == "ollama":
        return Provider.ollama(model=model or "gemma3:4b")
    if p == "vllm":
        return Provider.vllm(model=model or "google/gemma-3-4b-it")
    if p == "openai":
        return Provider.openai(model=model or "gpt-4o-mini")
    if p == "groq":
        return Provider.groq(model=model or "llama-3.1-8b-instant")
    if p == "openrouter":
        return Provider.openrouter(model=model or "google/gemma-3-4b-it")
    raise pytest.fail.Exception(f"unknown CORTEX_EVAL_PROVIDER={p!r}")


@pytest.mark.asyncio
async def test_eval_suite_meets_pass_rate_threshold() -> None:
    fixtures = _load_fixtures()
    assert len(fixtures) >= 25, f"need ≥25 fixtures, have {len(fixtures)}"

    live = os.environ.get("CORTEX_EVAL") == "1"
    if live:
        provider = _provider_from_env()
        assert provider is not None, "CORTEX_EVAL=1 requires CORTEX_EVAL_PROVIDER"
        language: Any = Language([provider])
        threshold = float(os.environ.get("CORTEX_EVAL_MIN_PASS_RATE", "0.7"))
    else:
        language = _StubLanguage(fixtures)
        threshold = float(os.environ.get("CORTEX_EVAL_MIN_PASS_RATE", "1.0"))

    passed = 0
    failed: list[tuple[str, str]] = []
    try:
        for f in fixtures:
            messages = [
                {
                    "role": "system",
                    "content": "You are a precise small-model assistant. Be terse.",
                },
                {"role": "user", "content": f["user"]},
            ]
            try:
                utt = await language.think(messages, temperature=0.0, max_tokens=64)
                ok = _hit(utt.text, f)
            except Exception as exc:
                ok = False
                utt_text = f"<error: {type(exc).__name__}: {exc}>"
            else:
                utt_text = utt.text
            if ok:
                passed += 1
            else:
                failed.append((f["id"], utt_text[:120]))
    finally:
        if live and hasattr(language, "aclose"):
            await language.aclose()

    pass_rate = passed / len(fixtures)
    assert pass_rate >= threshold, (
        f"pass rate {pass_rate:.2%} < threshold {threshold:.2%}\n"
        + "\n".join(f"  - {fid}: {reply!r}" for fid, reply in failed[:10])
    )
