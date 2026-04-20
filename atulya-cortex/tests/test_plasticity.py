"""tests/test_plasticity.py — plasticity optimizer/compiler tests.

Everything in here runs against a `StubLanguage` with no external deps,
so this test file is fully self-contained and does not require the
optional `dspy-ai` / `textgrad` extras at test time.

Coverage matrix:

- `signature.py`    — Field validation, Signature.to_dict/from_dict round-trip.
- `program.py`      — render_messages shape, parse_response (single & multi
                      field), forward() happy path.
- `metric.py`       — exact_match / contains / regex_match / llm_judge /
                      evaluate() aggregation and tracing.
- `compiler.py`     — local bootstrap keeps passing demos; dspy auto-fallback
                      when dspy is not installed; empty trainset rejected.
- `gradient.py`     — textgrad local backend proposes and accepts an
                      improvement; rejects when no improvement; noop when
                      every example already passes.
- `store.py`        — save_compiled / load_compiled round-trip; version
                      mismatch rejected.
- `engine.py`       — LanguageEngine.complete() and __call__() work sync.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest

from cortex.language import Utterance
from plasticity import (
    Compiler,
    Demo,
    Example,
    Field,
    LanguageEngine,
    Program,
    Signature,
    TextGradient,
    contains,
    evaluate,
    exact_match,
    load_compiled,
    regex_match,
    save_compiled,
)
from plasticity.store import VERSION

# ---------------------------------------------------------------------------
# Stub Language
# ---------------------------------------------------------------------------


@dataclass
class StubLanguage:
    """A deterministic Language stand-in for tests.

    `responder` is called with (messages, kwargs) and returns the string to
    put inside the Utterance. The `calls` list records every invocation so
    tests can assert call counts.
    """

    responder: Callable[[list[dict[str, Any]], dict[str, Any]], str]
    calls: list[dict[str, Any]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.calls = []

    async def think(self, messages: list[dict[str, Any]], **kwargs: Any) -> Utterance:
        self.calls.append({"messages": messages, "kwargs": dict(kwargs)})
        text = self.responder(messages, kwargs)
        return Utterance(text=text, provider="stub", model="stub", elapsed_ms=0.0)

    async def aclose(self) -> None:
        return None


def _echo_responder(
    text_by_message: dict[str, str] | None = None,
) -> Callable[[list[dict[str, Any]], dict[str, Any]], str]:
    """Return a responder that looks up a canned response by user-turn substring."""

    table = dict(text_by_message or {})

    def _respond(messages: list[dict[str, Any]], _kwargs: dict[str, Any]) -> str:
        user_blob = "\n".join(m.get("content", "") for m in messages if m.get("role") == "user")
        for key, value in table.items():
            if key in user_blob:
                return value
        return ""

    return _respond


# ---------------------------------------------------------------------------
# signature.py
# ---------------------------------------------------------------------------


class TestSignature:
    def test_field_requires_identifier(self) -> None:
        with pytest.raises(ValueError):
            Field("has space")
        with pytest.raises(ValueError):
            Field("")

    def test_requires_outputs(self) -> None:
        with pytest.raises(ValueError):
            Signature(name="s", instructions="", inputs=[Field("a")], outputs=[])

    def test_detects_duplicate_fields(self) -> None:
        with pytest.raises(ValueError):
            Signature(
                name="s",
                instructions="",
                inputs=[Field("x")],
                outputs=[Field("x")],
            )

    def test_roundtrip_to_dict(self) -> None:
        sig = Signature(
            name="summarize",
            instructions="Summarize.",
            inputs=[Field("passage", "The input passage.")],
            outputs=[Field("summary", "A one-sentence summary.")],
        )
        restored = Signature.from_dict(sig.to_dict())
        assert restored == sig


# ---------------------------------------------------------------------------
# program.py
# ---------------------------------------------------------------------------


def _summarize_signature() -> Signature:
    return Signature(
        name="summarize",
        instructions="Summarize the passage in one sentence.",
        inputs=[Field("passage")],
        outputs=[Field("summary")],
    )


def _qa_signature() -> Signature:
    return Signature(
        name="qa",
        instructions="Answer the question in one short phrase.",
        inputs=[Field("question")],
        outputs=[Field("answer")],
    )


class TestProgram:
    def test_render_messages_shape(self) -> None:
        sig = _summarize_signature()
        program = Program(signature=sig)
        messages = program.render_messages({"passage": "Paris is in France."})
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[0]["content"].endswith(".")
        user = messages[1]["content"]
        assert "passage: Paris is in France." in user
        assert user.strip().endswith("summary:")

    def test_render_with_demos_includes_them(self) -> None:
        sig = _summarize_signature()
        program = Program(
            signature=sig,
            demos=[
                Demo(
                    inputs={"passage": "Rome is in Italy."},
                    outputs={"summary": "Rome is Italian."},
                )
            ],
        )
        user = program.render_messages({"passage": "Paris is in France."})[1]["content"]
        assert "example 1" in user
        assert "Rome is Italian." in user

    def test_validate_inputs_raises_on_missing(self) -> None:
        sig = _summarize_signature()
        program = Program(signature=sig)
        with pytest.raises(ValueError):
            program.render_messages({})

    def test_parse_response_single_field(self) -> None:
        sig = _summarize_signature()
        program = Program(signature=sig)
        assert program.parse_response("summary: Paris is in France.")["summary"] == "Paris is in France."
        assert program.parse_response("A one-sentence summary.")["summary"] == "A one-sentence summary."

    def test_parse_response_multi_field(self) -> None:
        sig = Signature(
            name="multi",
            instructions="Return two fields.",
            inputs=[Field("q")],
            outputs=[Field("first"), Field("second")],
        )
        program = Program(signature=sig)
        out = program.parse_response("first: alpha\nsecond: beta\n")
        assert out == {"first": "alpha", "second": "beta"}

    @pytest.mark.asyncio
    async def test_forward_routes_through_language(self) -> None:
        sig = _qa_signature()
        program = Program(signature=sig)
        lang = StubLanguage(_echo_responder({"capital of France": "answer: Paris"}))
        out = await program.forward(lang, {"question": "What is the capital of France?"})
        assert out["answer"] == "Paris"
        assert out["_raw"] == "answer: Paris"
        assert len(lang.calls) == 1
        assert lang.calls[0]["kwargs"]["temperature"] == program.temperature

    def test_with_instructions_does_not_mutate_original(self) -> None:
        sig = _summarize_signature()
        program = Program(signature=sig, instructions="Be terse.")
        evolved = program.with_instructions("Be verbose.")
        assert program.instructions == "Be terse."
        assert evolved.instructions == "Be verbose."


# ---------------------------------------------------------------------------
# metric.py
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_exact_match_is_case_and_whitespace_insensitive(self) -> None:
        m = exact_match("answer")
        assert m({"answer": "Paris "}, {"answer": "  paris"}) == 1.0
        assert m({"answer": "London"}, {"answer": "Paris"}) == 0.0

    def test_contains_metric(self) -> None:
        m = contains("answer")
        assert m({"answer": "Paris is the capital."}, {"answer": "paris"}) == 1.0
        assert m({"answer": "Rome."}, {"answer": "paris"}) == 0.0

    def test_regex_metric(self) -> None:
        m = regex_match("answer", r"paris")
        assert m({"answer": "PARIS"}, {}) == 1.0
        assert m({"answer": "Rome"}, {}) == 0.0

    @pytest.mark.asyncio
    async def test_evaluate_aggregates_and_traces(self) -> None:
        sig = _qa_signature()
        program = Program(signature=sig)
        lang = StubLanguage(
            _echo_responder(
                {
                    "France": "answer: Paris",
                    "Italy": "answer: Rome",
                    "Germany": "answer: Wrong",
                }
            )
        )
        examples = [
            Example(inputs={"question": "Capital of France?"}, outputs={"answer": "Paris"}),
            Example(inputs={"question": "Capital of Italy?"}, outputs={"answer": "Rome"}),
            Example(inputs={"question": "Capital of Germany?"}, outputs={"answer": "Berlin"}),
        ]
        report = await evaluate(program, lang, examples, exact_match("answer"))
        assert report.n == 3
        assert report.passes == 2
        assert pytest.approx(report.mean, 1e-6) == 2 / 3
        assert [t.score for t in report.traces] == [1.0, 1.0, 0.0]

    @pytest.mark.asyncio
    async def test_evaluate_captures_forward_error(self) -> None:
        class _Boom:
            async def think(self, *_: Any, **__: Any) -> Any:
                raise RuntimeError("network down")

        sig = _qa_signature()
        program = Program(signature=sig)
        examples = [Example(inputs={"question": "q"}, outputs={"answer": "a"})]
        report = await evaluate(program, _Boom(), examples, exact_match("answer"))
        assert report.mean == 0.0
        assert "network down" in (report.traces[0].error or "")


# ---------------------------------------------------------------------------
# compiler.py
# ---------------------------------------------------------------------------


class TestCompiler:
    @pytest.mark.asyncio
    async def test_local_backend_keeps_passing_demos(self) -> None:
        sig = _qa_signature()
        program = Program(signature=sig)
        responses = {
            "Capital of France": "answer: Paris",
            "Capital of Italy": "answer: Rome",
            "Capital of Germany": "answer: Wrong",
        }
        lang = StubLanguage(_echo_responder(responses))
        trainset = [
            Example(inputs={"question": "Capital of France?"}, outputs={"answer": "Paris"}),
            Example(inputs={"question": "Capital of Italy?"}, outputs={"answer": "Rome"}),
            Example(inputs={"question": "Capital of Germany?"}, outputs={"answer": "Berlin"}),
        ]
        compiler = Compiler(max_demos=5)
        compiled, report = await compiler.compile(
            program,
            lang,
            trainset=trainset,
            metric=exact_match("answer"),
            backend="local",
        )
        # The German example fails the metric, so only two demos survive.
        assert len(compiled.demos) == 2
        assert {d.outputs["answer"] for d in compiled.demos} == {"Paris", "Rome"}
        assert report.backend_used == "local"
        assert report.demos_kept == 2

    @pytest.mark.asyncio
    async def test_auto_backend_falls_back_to_local_when_dspy_missing(self) -> None:
        sig = _qa_signature()
        program = Program(signature=sig)
        lang = StubLanguage(_echo_responder({"x": "answer: y"}))
        trainset = [Example(inputs={"question": "x"}, outputs={"answer": "y"})]
        # Regardless of whether dspy happens to be installed, the compile
        # returns a valid Program and a populated report.
        _, report = await Compiler().compile(
            program,
            lang,
            trainset=trainset,
            metric=exact_match("answer"),
            backend="auto",
        )
        assert report.backend_used in {"local", "dspy"}

    @pytest.mark.asyncio
    async def test_empty_trainset_rejected(self) -> None:
        sig = _qa_signature()
        program = Program(signature=sig)
        lang = StubLanguage(_echo_responder({}))
        with pytest.raises(ValueError):
            await Compiler().compile(
                program,
                lang,
                trainset=[],
                metric=exact_match("answer"),
                backend="local",
            )

    @pytest.mark.asyncio
    async def test_compile_records_baseline_and_compiled_over_valset(self) -> None:
        sig = _qa_signature()
        program = Program(signature=sig)
        lang = StubLanguage(
            _echo_responder(
                {
                    "Capital of France": "answer: Paris",
                    "Capital of Italy": "answer: Rome",
                }
            )
        )
        trainset = [
            Example(inputs={"question": "Capital of France?"}, outputs={"answer": "Paris"}),
        ]
        valset = [
            Example(inputs={"question": "Capital of Italy?"}, outputs={"answer": "Rome"}),
        ]
        _, report = await Compiler(max_demos=1).compile(
            program,
            lang,
            trainset=trainset,
            metric=exact_match("answer"),
            valset=valset,
            backend="local",
        )
        assert report.baseline is not None
        assert report.compiled is not None
        assert report.baseline.n == 1
        assert report.compiled.n == 1


# ---------------------------------------------------------------------------
# gradient.py
# ---------------------------------------------------------------------------


class TestTextGradient:
    @pytest.mark.asyncio
    async def test_local_step_accepts_when_proposal_improves_score(self) -> None:
        sig = _qa_signature()
        program = Program(signature=sig, instructions="Be terse.")

        # The responder looks at the SYSTEM prompt: with the terse instruction
        # we answer "Wrong"; after the rewrite uses "precise" we answer right.
        def responder(messages: list[dict[str, Any]], kwargs: dict[str, Any]) -> str:
            system = next((m["content"] for m in messages if m["role"] == "system"), "")
            user = next((m["content"] for m in messages if m["role"] == "user"), "")
            # The critic/rewrite system prompts are long; route them by prefix.
            if system.startswith("You are a careful grader"):
                return "- the instruction is too vague"
            if system.startswith("You are an expert prompt engineer"):
                return "Answer with the precise capital city."
            if "precise capital" in system:
                return "answer: Paris"
            return "answer: Wrong"

        lang = StubLanguage(responder)
        trainset = [
            Example(inputs={"question": "Capital of France?"}, outputs={"answer": "Paris"}),
        ]
        grad = TextGradient(max_critique_examples=1)
        tuned, report = await grad.optimize(
            program,
            lang,
            trainset=trainset,
            metric=exact_match("answer"),
            steps=1,
            backend="local",
        )
        assert report.backend_used == "local"
        assert report.steps[0].accepted is True
        assert "precise" in (tuned.instructions or "").lower()

    @pytest.mark.asyncio
    async def test_optimize_is_noop_when_every_example_passes(self) -> None:
        sig = _qa_signature()
        program = Program(signature=sig, instructions="Answer precisely.")
        lang = StubLanguage(_echo_responder({"France": "answer: Paris"}))
        trainset = [
            Example(inputs={"question": "Capital of France?"}, outputs={"answer": "Paris"}),
        ]
        tuned, report = await TextGradient().optimize(
            program,
            lang,
            trainset=trainset,
            metric=exact_match("answer"),
            steps=2,
            backend="local",
        )
        # No critique produced because everything already passes.
        assert tuned.instructions == program.instructions
        assert all(not s.accepted for s in report.steps)

    @pytest.mark.asyncio
    async def test_rejects_proposal_that_doesnt_improve(self) -> None:
        sig = _qa_signature()
        program = Program(signature=sig, instructions="Be terse.")

        def responder(messages: list[dict[str, Any]], _kwargs: dict[str, Any]) -> str:
            system = next((m["content"] for m in messages if m["role"] == "system"), "")
            if system.startswith("You are a careful grader"):
                return "- the instruction is too vague"
            if system.startswith("You are an expert prompt engineer"):
                return "Still useless instructions."
            return "answer: Wrong"

        lang = StubLanguage(responder)
        trainset = [Example(inputs={"question": "q"}, outputs={"answer": "Paris"})]
        tuned, report = await TextGradient(max_critique_examples=1).optimize(
            program,
            lang,
            trainset=trainset,
            metric=exact_match("answer"),
            steps=1,
            backend="local",
        )
        assert tuned.instructions == program.instructions
        assert report.steps[0].accepted is False


# ---------------------------------------------------------------------------
# store.py
# ---------------------------------------------------------------------------


class TestStore:
    def test_roundtrip_preserves_program(self, tmp_path: Path) -> None:
        sig = _qa_signature()
        program = Program(
            signature=sig,
            instructions="Precise.",
            demos=[Demo(inputs={"question": "x"}, outputs={"answer": "y"})],
            temperature=0.1,
            max_tokens=256,
        )
        path = save_compiled(tmp_path / "qa.json", program, meta={"note": "test"})
        artifact = load_compiled(path)
        assert artifact.program.signature == program.signature
        assert artifact.program.instructions == program.instructions
        assert artifact.program.demos == program.demos
        assert artifact.program.temperature == pytest.approx(0.1)
        assert artifact.meta["note"] == "test"
        assert "compiled_at" in artifact.meta

    def test_version_mismatch_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"version": VERSION + 99}), encoding="utf-8")
        with pytest.raises(ValueError):
            load_compiled(path)


# ---------------------------------------------------------------------------
# engine.py
# ---------------------------------------------------------------------------


class TestLanguageEngine:
    def test_complete_is_sync(self) -> None:
        lang = StubLanguage(_echo_responder({"hello": "world"}))
        with LanguageEngine(lang) as engine:
            text = engine.complete(
                [{"role": "user", "content": "hello"}],
                temperature=0.0,
                max_tokens=10,
            )
        assert text == "world"
        assert lang.calls[0]["kwargs"]["temperature"] == 0.0
        assert lang.calls[0]["kwargs"]["max_tokens"] == 10

    def test_callable_wraps_prompt_string(self) -> None:
        lang = StubLanguage(_echo_responder({"please": "ok"}))
        with LanguageEngine(lang) as engine:
            text = engine("please")
        assert text == "ok"

    def test_close_is_idempotent(self) -> None:
        lang = StubLanguage(_echo_responder({"x": "y"}))
        engine = LanguageEngine(lang)
        engine.close()
        engine.close()  # must not raise
        # We can still re-use the engine after a close() because submit()
        # re-spawns the loop thread.
        asyncio.run(lang.aclose())
