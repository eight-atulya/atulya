"""metric.py — scoring functions and evaluation runners for Programs.

A metric is `Callable[[predicted: dict, expected: dict], float]` returning a
value in `[0.0, 1.0]`. Built-ins:

- `exact_match(field)` — 1.0 if the predicted field equals the expected
  field (case-insensitive, whitespace-normalized).
- `contains(field)` — 1.0 if the expected substring appears in the
  predicted field.
- `regex_match(field, pattern)` — 1.0 if the pattern matches the prediction.
- `llm_judge(language, field, rubric)` — ask an LLM to score the prediction
  on [0.0, 1.0] against a rubric. Used sparingly; costs one LM call per
  example.

`evaluate(program, language, examples, metric)` is the runner every compiler
and gradient step uses. It returns an `EvalReport` with per-example traces
so callers can introspect failures without re-running.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Sequence

from plasticity.program import Program

Metric = Callable[[Mapping[str, Any], Mapping[str, Any]], float]


@dataclass(frozen=True)
class Example:
    """One labeled training or eval row."""

    inputs: dict[str, str]
    outputs: dict[str, str]
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Example":
        return cls(
            inputs=dict(data.get("inputs", {})),
            outputs=dict(data.get("outputs", {})),
            meta=dict(data.get("meta", {})),
        )


@dataclass
class _Trace:
    example: Example
    predicted: dict[str, Any]
    score: float
    error: str | None = None


@dataclass
class EvalReport:
    """Result of one evaluate() run."""

    scores: list[float]
    traces: list[_Trace]

    @property
    def n(self) -> int:
        return len(self.scores)

    @property
    def mean(self) -> float:
        if not self.scores:
            return 0.0
        return sum(self.scores) / len(self.scores)

    @property
    def passes(self) -> int:
        return sum(1 for s in self.scores if s >= 1.0)

    def summary(self) -> str:
        if not self.scores:
            return "n=0"
        return f"n={self.n} mean={self.mean:.3f} pass@1={self.passes}/{self.n}"


# ---------------------------------------------------------------------------
# Built-in metrics
# ---------------------------------------------------------------------------


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def exact_match(field_name: str) -> Metric:
    def _m(pred: Mapping[str, Any], gold: Mapping[str, Any]) -> float:
        return 1.0 if _norm(pred.get(field_name)) == _norm(gold.get(field_name)) else 0.0

    return _m


def contains(field_name: str) -> Metric:
    def _m(pred: Mapping[str, Any], gold: Mapping[str, Any]) -> float:
        expected = _norm(gold.get(field_name))
        got = _norm(pred.get(field_name))
        return 1.0 if expected and expected in got else 0.0

    return _m


def regex_match(field_name: str, pattern: str, *, flags: int = re.IGNORECASE) -> Metric:
    rx = re.compile(pattern, flags)

    def _m(pred: Mapping[str, Any], gold: Mapping[str, Any]) -> float:
        return 1.0 if rx.search(str(pred.get(field_name, ""))) else 0.0

    return _m


def llm_judge(
    language: Any,
    field_name: str,
    rubric: str,
    *,
    provider: str | None = None,
    temperature: float = 0.0,
) -> Metric:
    """Metric that delegates scoring to an LLM. 1 LM call per evaluate-row."""

    prompt = (
        "You are an exacting grader. Score the PREDICTION against the EXPECTED "
        "value on a scale from 0.0 to 1.0 using the RUBRIC. Return ONLY a "
        "number between 0.0 and 1.0 on the first line.\n\n"
        "RUBRIC:\n{rubric}\n\nPREDICTION:\n{pred}\n\nEXPECTED:\n{gold}\n"
    )

    def _m(pred: Mapping[str, Any], gold: Mapping[str, Any]) -> float:
        body = prompt.format(
            rubric=rubric,
            pred=pred.get(field_name, ""),
            gold=gold.get(field_name, ""),
        )

        async def _call() -> str:
            utt = await language.think(
                [{"role": "user", "content": body}],
                provider=provider,
                temperature=temperature,
                max_tokens=16,
            )
            return utt.text or ""

        try:
            text = asyncio.get_event_loop().run_until_complete(_call())
        except RuntimeError:
            text = asyncio.new_event_loop().run_until_complete(_call())

        m = re.search(r"(\d(?:\.\d+)?)", text)
        if not m:
            return 0.0
        try:
            return max(0.0, min(1.0, float(m.group(1))))
        except ValueError:
            return 0.0

    return _m


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def evaluate(
    program: Program,
    language: Any,
    examples: Sequence[Example],
    metric: Metric,
    *,
    provider: str | None = None,
    model: str | None = None,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> EvalReport:
    """Run `program` on each example, score with `metric`, return a report."""

    scores: list[float] = []
    traces: list[_Trace] = []
    for i, ex in enumerate(examples):
        err: str | None = None
        try:
            predicted = await program.forward(
                language,
                ex.inputs,
                provider=provider,
                model=model,
            )
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            predicted = {}
        try:
            score = float(metric(predicted, ex.outputs))
        except Exception as exc:
            err = err or f"{type(exc).__name__}: {exc}"
            score = 0.0
        score = max(0.0, min(1.0, score))
        scores.append(score)
        traces.append(_Trace(example=ex, predicted=predicted, score=score, error=err))
        if on_progress is not None:
            await on_progress(i + 1, len(examples))
    return EvalReport(scores=scores, traces=traces)


__all__ = [
    "EvalReport",
    "Example",
    "Metric",
    "contains",
    "evaluate",
    "exact_match",
    "llm_judge",
    "regex_match",
]
