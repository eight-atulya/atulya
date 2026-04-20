"""compiler.py — demo-bootstrap compiler for Programs.

Implements DSPy's `BootstrapFewShot` paradigm:

  0. Start with a Program that has empty demos and the raw instructions.
  1. Run it against each training example.
  2. Keep the examples where the metric fires as few-shot demonstrations.
  3. (Optional) Augment with *teacher-generated* demos: ask the LM itself
     to produce `outputs` from `inputs`, accept only those that pass metric.
  4. Return a new Program with the top-k demos attached.

Two backends:

- `backend="local"` (default) — no external deps.
- `backend="dspy"` — drives `dspy.teleprompt.BootstrapFewShot.compile()`;
  requires `dspy-ai` and converts the Signature/Program round-trip.

Why both: DSPy's MIPROv2 / BootstrapFewShotWithRandomSearch can beat a
handwritten bootstrap on small trainsets, but (a) dspy is an optional
dep, and (b) the local path is enough to ship a useful first-version on
gemma-3-4b.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

from plasticity.metric import EvalReport, Example, Metric, evaluate
from plasticity.program import Demo, Program

Backend = Literal["auto", "local", "dspy"]

logger = logging.getLogger(__name__)


@dataclass
class BootstrapReport:
    """What Compiler.compile() returns alongside the optimized Program."""

    baseline: EvalReport | None
    compiled: EvalReport | None
    demos_kept: int
    backend_used: str
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        base = f"baseline={self.baseline.mean:.3f}" if self.baseline else "baseline=n/a"
        comp = f"compiled={self.compiled.mean:.3f}" if self.compiled else "compiled=n/a"
        return f"backend={self.backend_used} demos={self.demos_kept} {base} {comp}"


class Compiler:
    """Bootstrap few-shot compiler."""

    def __init__(
        self,
        *,
        max_demos: int = 4,
        max_bootstraps: int = 8,
        min_score: float = 1.0,
        shuffle: bool = False,
    ) -> None:
        if max_demos < 0:
            raise ValueError("max_demos must be non-negative")
        if max_bootstraps < 1:
            raise ValueError("max_bootstraps must be >= 1")
        self.max_demos = max_demos
        self.max_bootstraps = max_bootstraps
        self.min_score = min_score
        self.shuffle = shuffle

    async def compile(
        self,
        program: Program,
        language: Any,
        *,
        trainset: Sequence[Example],
        metric: Metric,
        valset: Sequence[Example] | None = None,
        backend: Backend = "auto",
        provider: str | None = None,
        model: str | None = None,
    ) -> tuple[Program, BootstrapReport]:
        """Return `(compiled_program, report)`.

        - `trainset` drives the demo search.
        - `valset` (optional) drives baseline vs compiled scoring.
        """

        if not trainset:
            raise ValueError("Compiler.compile requires a non-empty trainset")

        backend_used = _resolve_backend(backend)
        notes: list[str] = []

        baseline: EvalReport | None = None
        if valset is not None:
            baseline = await evaluate(program, language, valset, metric, provider=provider, model=model)
            notes.append(f"baseline over valset: {baseline.summary()}")

        if backend_used == "dspy":
            try:
                compiled = await asyncio.to_thread(
                    _compile_with_dspy,
                    program,
                    language,
                    list(trainset),
                    metric,
                    self,
                    provider,
                    model,
                )
            except ImportError as exc:
                notes.append(f"dspy unavailable ({exc}); falling back to local backend")
                backend_used = "local"
                compiled = await self._compile_local(
                    program,
                    language,
                    trainset,
                    metric,
                    provider=provider,
                    model=model,
                    notes=notes,
                )
        else:
            compiled = await self._compile_local(
                program,
                language,
                trainset,
                metric,
                provider=provider,
                model=model,
                notes=notes,
            )

        compiled_report: EvalReport | None = None
        if valset is not None:
            compiled_report = await evaluate(compiled, language, valset, metric, provider=provider, model=model)
            notes.append(f"compiled over valset: {compiled_report.summary()}")

        report = BootstrapReport(
            baseline=baseline,
            compiled=compiled_report,
            demos_kept=len(compiled.demos),
            backend_used=backend_used,
            notes=notes,
        )
        return compiled, report

    async def _compile_local(
        self,
        program: Program,
        language: Any,
        trainset: Sequence[Example],
        metric: Metric,
        *,
        provider: str | None,
        model: str | None,
        notes: list[str],
    ) -> Program:
        """Local bootstrap: try each trainset example up to `max_bootstraps`
        total, keep the ones that pass `metric` as few-shot demos."""

        examples = list(trainset)
        if self.shuffle:
            import random

            random.shuffle(examples)

        picked: list[tuple[float, Demo]] = []
        attempts = 0
        for ex in examples:
            if len(picked) >= self.max_demos:
                break
            if attempts >= self.max_bootstraps:
                break
            attempts += 1
            try:
                predicted = await program.forward(
                    language,
                    ex.inputs,
                    provider=provider,
                    model=model,
                )
            except Exception as exc:
                notes.append(f"local: forward failed on example: {type(exc).__name__}: {exc}")
                continue
            try:
                score = float(metric(predicted, ex.outputs))
            except Exception as exc:
                notes.append(f"local: metric raised on example: {type(exc).__name__}: {exc}")
                continue

            # A trainset example IS ground truth — if it passes the metric,
            # we keep its gold outputs (not the predicted ones) as the demo.
            if score >= self.min_score:
                demo = Demo(
                    inputs={k: str(v) for k, v in ex.inputs.items()},
                    outputs={k: str(v) for k, v in ex.outputs.items()},
                )
                picked.append((score, demo))

        # Deterministic demo order: original trainset order, truncated.
        kept = [d for _, d in picked[: self.max_demos]]
        notes.append(f"local: kept {len(kept)}/{len(examples)} demos after {attempts} bootstraps")
        return program.with_demos(kept)


# ---------------------------------------------------------------------------
# Backend resolution
# ---------------------------------------------------------------------------


def _resolve_backend(backend: Backend) -> str:
    if backend == "local":
        return "local"
    if backend == "dspy":
        return "dspy"
    if backend == "auto":
        try:
            import dspy  # type: ignore[import-not-found]  # noqa: F401

            return "dspy"
        except ImportError:
            return "local"
    raise ValueError(f"unknown backend {backend!r}")


def _compile_with_dspy(
    program: Program,
    language: Any,
    trainset: list[Example],
    metric: Metric,
    compiler: Compiler,
    provider: str | None,
    model: str | None,
) -> Program:
    """Run DSPy's BootstrapFewShot on our Program. Returns a new Program with demos."""

    import dspy  # type: ignore[import-not-found]
    from dspy.teleprompt import BootstrapFewShot  # type: ignore[import-not-found]

    from plasticity.engine import build_dspy_lm

    lm = build_dspy_lm(language, provider=provider, model=model)
    dspy.configure(lm=lm)

    sig = program.signature
    input_fields = {f.name: dspy.InputField(desc=f.desc) for f in sig.inputs}
    output_fields = {f.name: dspy.OutputField(desc=f.desc) for f in sig.outputs}
    sig_cls = type(
        sig.name,
        (dspy.Signature,),
        {
            "__doc__": program.instructions or sig.instructions,
            **input_fields,
            **output_fields,
        },
    )

    class _Module(dspy.Module):  # type: ignore[misc,no-any-unimported]
        def __init__(self) -> None:
            super().__init__()
            self.predict = dspy.Predict(sig_cls)

        def forward(self, **kwargs: Any) -> Any:
            return self.predict(**kwargs)

    def _dspy_metric(example: Any, prediction: Any, *_: Any, **__: Any) -> float:
        pred = {name: getattr(prediction, name, "") for name in sig.output_names}
        gold = {name: getattr(example, name, "") for name in sig.output_names}
        return float(metric(pred, gold))

    dspy_trainset = [dspy.Example(**ex.inputs, **ex.outputs).with_inputs(*sig.input_names) for ex in trainset]
    tele = BootstrapFewShot(
        metric=_dspy_metric,
        max_bootstrapped_demos=compiler.max_demos,
        max_rounds=1,
    )
    compiled_module = tele.compile(_Module(), trainset=dspy_trainset)

    # Extract demos from the compiled Predict module.
    raw_demos = getattr(compiled_module.predict, "demos", []) or []
    demos: list[Demo] = []
    for d in raw_demos[: compiler.max_demos]:
        demos.append(
            Demo(
                inputs={n: str(getattr(d, n, "")) for n in sig.input_names},
                outputs={n: str(getattr(d, n, "")) for n in sig.output_names},
            )
        )
    return program.with_demos(demos)


__all__ = ["BootstrapReport", "Compiler"]
