"""gradient.py — textual gradient descent on a Program's instructions.

TextGrad's key idea: treat each string variable (prompt, instruction,
sub-prompt) as differentiable, where the "gradient" is a natural-language
critique produced by a strong LLM, and the "optimizer step" is another LLM
call that rewrites the variable to reduce the loss.

This module implements that loop for `Program.instructions`. One step:

  1. Run the current Program on a sample of `trainset`.
  2. For each failing example, ask the LM for a short critique of the
     instruction text given (input, predicted, expected).
  3. Aggregate the critiques into a single textual loss.
  4. Ask the LM to rewrite the instructions to address the loss while
     staying faithful to the Signature's intent.
  5. Evaluate the proposal on `valset` (or a held-out slice of trainset).
     If it improves, accept; otherwise keep the previous instructions.

Backends:

- `backend="local"` (default) — the LLM-critic loop described above.
- `backend="textgrad"` — defers to the real `textgrad` library when
  installed. Still uses our `LanguageEngine` for the underlying LM.

`TextGradient.optimize(program, language, trainset, metric, steps=N)` runs
N accepted or rejected proposals and returns the best Program seen.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

from plasticity.metric import EvalReport, Example, Metric, evaluate
from plasticity.program import Program

Backend = Literal["auto", "local", "textgrad"]

logger = logging.getLogger(__name__)

DEFAULT_CRITIC_SYSTEM = (
    "You are a careful grader of instructions for an LLM task. "
    "Given the task instructions, one input, one expected output, and the "
    "model's actual output, identify precisely what about the INSTRUCTIONS "
    "caused the gap. Be terse (<= 3 bullet points). Do not rewrite the "
    "instructions — only describe the gap."
)

DEFAULT_REWRITE_SYSTEM = (
    "You are an expert prompt engineer. Rewrite the INSTRUCTIONS so that "
    "the listed critiques would no longer apply, while preserving the "
    "original task intent. Output ONLY the rewritten instructions, no "
    "preamble, no commentary."
)


@dataclass
class _StepTrace:
    step: int
    proposed_instructions: str
    score_before: float
    score_after: float
    accepted: bool
    critique: str = ""


@dataclass
class GradientReport:
    """Result of one optimize() call."""

    initial: EvalReport | None
    final: EvalReport | None
    best_instructions: str
    steps: list[_StepTrace] = field(default_factory=list)
    backend_used: str = "local"

    def summary(self) -> str:
        initial = f"initial={self.initial.mean:.3f}" if self.initial else "initial=n/a"
        final = f"final={self.final.mean:.3f}" if self.final else "final=n/a"
        return f"backend={self.backend_used} steps={len(self.steps)} {initial} {final}"


class TextGradient:
    """Textual gradient optimizer over `Program.instructions`."""

    def __init__(
        self,
        *,
        critic_system: str = DEFAULT_CRITIC_SYSTEM,
        rewrite_system: str = DEFAULT_REWRITE_SYSTEM,
        critic_temperature: float = 0.3,
        rewrite_temperature: float = 0.5,
        max_critique_examples: int = 3,
    ) -> None:
        if max_critique_examples < 1:
            raise ValueError("max_critique_examples must be >= 1")
        self.critic_system = critic_system
        self.rewrite_system = rewrite_system
        self.critic_temperature = critic_temperature
        self.rewrite_temperature = rewrite_temperature
        self.max_critique_examples = max_critique_examples

    async def optimize(
        self,
        program: Program,
        language: Any,
        *,
        trainset: Sequence[Example],
        metric: Metric,
        valset: Sequence[Example] | None = None,
        steps: int = 3,
        backend: Backend = "auto",
        provider: str | None = None,
        model: str | None = None,
    ) -> tuple[Program, GradientReport]:
        """Return `(best_program, report)` after up to `steps` proposals."""

        if steps < 1:
            raise ValueError("steps must be >= 1")
        if not trainset:
            raise ValueError("trainset must be non-empty")

        backend_used = _resolve_backend(backend)
        eval_set: Sequence[Example] = valset if valset is not None else trainset

        initial_report = await evaluate(program, language, eval_set, metric, provider=provider, model=model)
        best_program = program
        best_mean = initial_report.mean
        traces: list[_StepTrace] = []

        for step in range(1, steps + 1):
            if backend_used == "textgrad":
                try:
                    proposed = await asyncio.to_thread(
                        _propose_with_textgrad,
                        best_program,
                        language,
                        list(trainset),
                        metric,
                        self,
                        provider,
                        model,
                    )
                except ImportError as exc:
                    logger.warning("textgrad unavailable (%s); falling back to local", exc)
                    backend_used = "local"
                    proposed, critique = await self._propose_local(
                        best_program,
                        language,
                        trainset,
                        metric,
                        provider=provider,
                        model=model,
                    )
                else:
                    critique = "(textgrad backend)"
            else:
                proposed, critique = await self._propose_local(
                    best_program,
                    language,
                    trainset,
                    metric,
                    provider=provider,
                    model=model,
                )

            if proposed is None:
                traces.append(
                    _StepTrace(
                        step=step,
                        proposed_instructions=best_program.instructions or "",
                        score_before=best_mean,
                        score_after=best_mean,
                        accepted=False,
                        critique=critique,
                    )
                )
                continue

            candidate_report = await evaluate(proposed, language, eval_set, metric, provider=provider, model=model)
            accepted = candidate_report.mean > best_mean
            traces.append(
                _StepTrace(
                    step=step,
                    proposed_instructions=proposed.instructions or "",
                    score_before=best_mean,
                    score_after=candidate_report.mean,
                    accepted=accepted,
                    critique=critique,
                )
            )
            if accepted:
                best_program = proposed
                best_mean = candidate_report.mean

        final_report = await evaluate(best_program, language, eval_set, metric, provider=provider, model=model)

        return best_program, GradientReport(
            initial=initial_report,
            final=final_report,
            best_instructions=best_program.instructions or best_program.signature.instructions,
            steps=traces,
            backend_used=backend_used,
        )

    async def _propose_local(
        self,
        program: Program,
        language: Any,
        trainset: Sequence[Example],
        metric: Metric,
        *,
        provider: str | None,
        model: str | None,
    ) -> tuple[Program | None, str]:
        """Produce one rewrite of `program.instructions` via an LLM critic+editor."""

        critiques: list[str] = []
        for ex in list(trainset)[: self.max_critique_examples]:
            try:
                predicted = await program.forward(language, ex.inputs, provider=provider, model=model)
            except Exception as exc:
                logger.debug("propose: forward failed: %s", exc)
                continue
            try:
                score = float(metric(predicted, ex.outputs))
            except Exception:
                score = 0.0
            if score >= 1.0:
                continue
            critique = await self._critique(
                language,
                program=program,
                inputs=ex.inputs,
                predicted=predicted,
                expected=ex.outputs,
                provider=provider,
                model=model,
            )
            if critique.strip():
                critiques.append(critique.strip())

        if not critiques:
            return None, "all examples passed the metric"

        critique_blob = "\n".join(f"- {c}" for c in critiques)
        proposal = await self._rewrite(
            language,
            instructions=program.instructions or program.signature.instructions,
            critiques=critique_blob,
            provider=provider,
            model=model,
        )
        if not proposal.strip():
            return None, critique_blob

        return program.with_instructions(proposal.strip()), critique_blob

    async def _critique(
        self,
        language: Any,
        *,
        program: Program,
        inputs: dict[str, str],
        predicted: dict[str, Any],
        expected: dict[str, str],
        provider: str | None,
        model: str | None,
    ) -> str:
        body = (
            f"INSTRUCTIONS:\n{program.instructions or program.signature.instructions}\n\n"
            f"INPUT:\n{_dump(inputs)}\n\n"
            f"EXPECTED:\n{_dump(expected)}\n\n"
            f"PREDICTED:\n{_dump({k: v for k, v in predicted.items() if not k.startswith('_')})}"
        )
        utt = await language.think(
            [
                {"role": "system", "content": self.critic_system},
                {"role": "user", "content": body},
            ],
            provider=provider,
            model=model,
            temperature=self.critic_temperature,
            max_tokens=256,
        )
        return utt.text or ""

    async def _rewrite(
        self,
        language: Any,
        *,
        instructions: str,
        critiques: str,
        provider: str | None,
        model: str | None,
    ) -> str:
        body = f"INSTRUCTIONS:\n{instructions}\n\nCRITIQUES:\n{critiques}\n\nRewrite the instructions now."
        utt = await language.think(
            [
                {"role": "system", "content": self.rewrite_system},
                {"role": "user", "content": body},
            ],
            provider=provider,
            model=model,
            temperature=self.rewrite_temperature,
            max_tokens=512,
        )
        return utt.text or ""


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


def _resolve_backend(backend: Backend) -> str:
    if backend == "local":
        return "local"
    if backend == "textgrad":
        return "textgrad"
    if backend == "auto":
        try:
            import textgrad  # type: ignore[import-not-found]  # noqa: F401

            return "textgrad"
        except ImportError:
            return "local"
    raise ValueError(f"unknown backend {backend!r}")


def _propose_with_textgrad(
    program: Program,
    language: Any,
    trainset: list[Example],
    metric: Metric,
    grad: TextGradient,
    provider: str | None,
    model: str | None,
) -> Program | None:
    """Delegate one rewrite step to the real textgrad library."""

    import textgrad as tg  # type: ignore[import-not-found]

    from plasticity.engine import build_textgrad_engine

    engine = build_textgrad_engine(language, provider=provider, model=model)
    tg.set_backward_engine(engine, override=True)

    instructions_var = tg.Variable(
        program.instructions or program.signature.instructions,
        requires_grad=True,
        role_description="instructions for the task",
    )

    # Build a simple textual loss: concatenate per-example mismatches.
    mismatch_blobs: list[str] = []
    for ex in trainset[: grad.max_critique_examples]:
        try:
            predicted = asyncio.run(program.forward(language, ex.inputs, provider=provider, model=model))
        except Exception:
            continue
        if float(metric(predicted, ex.outputs)) >= 1.0:
            continue
        mismatch_blobs.append(
            f"INPUT={_dump(ex.inputs)} EXPECTED={_dump(ex.outputs)} "
            f"PREDICTED={_dump({k: v for k, v in predicted.items() if not k.startswith('_')})}"
        )

    if not mismatch_blobs:
        return None

    loss_var = tg.Variable(
        "\n".join(mismatch_blobs),
        requires_grad=False,
        role_description="mismatches between expected and predicted outputs",
    )
    loss = tg.TextLoss(
        tg.Variable(
            "Identify and fix the gap in the instructions given these mismatches.",
            requires_grad=False,
            role_description="system prompt for computing the textual loss",
        ),
        engine=engine,
    )
    graded = loss(loss_var)
    graded.backward()

    optimizer = tg.TGD(parameters=[instructions_var])
    optimizer.step()

    return program.with_instructions(str(instructions_var.value).strip())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dump(d: dict[str, Any]) -> str:
    return "\n".join(f"  {k}: {v}" for k, v in d.items())


__all__ = ["GradientReport", "TextGradient"]
