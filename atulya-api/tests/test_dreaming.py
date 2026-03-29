from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio

from atulya_api.engine.dreaming import (
    PRESET_OVERRIDES,
    build_dream_html,
    compute_novelty_score,
    infer_maturity_tier,
    normalize_dream_config,
    score_dream_quality,
)
from atulya_api.engine.memory_engine import MemoryEngine
from atulya_api.engine.task_backend import SyncTaskBackend


class _FakeEmbeddings:
    def __init__(self, dimension: int = 384):
        self._dimension = dimension

    @property
    def provider_name(self) -> str:
        return "test"

    @property
    def dimension(self) -> int:
        return self._dimension

    async def initialize(self) -> None:
        return None

    def encode(self, texts: list[str]) -> list[list[float]]:
        rows: list[list[float]] = []
        for text in texts:
            seed = sum(ord(ch) for ch in (text or ""))
            rows.append([float((seed + i) % 17) / 17.0 for i in range(self._dimension)])
        return rows


class _FakeCrossEncoder:
    @property
    def provider_name(self) -> str:
        return "test"

    async def initialize(self) -> None:
        return None

    async def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        return [0.5 for _ in pairs]


@pytest_asyncio.fixture(scope="function")
async def dream_memory(pg0_db_url, query_analyzer):
    mem = MemoryEngine(
        db_url=pg0_db_url,
        memory_llm_provider="mock",
        memory_llm_api_key="",
        memory_llm_model="mock",
        embeddings=_FakeEmbeddings(),
        cross_encoder=_FakeCrossEncoder(),
        query_analyzer=query_analyzer,
        pool_min_size=1,
        pool_max_size=5,
        run_migrations=False,
        task_backend=SyncTaskBackend(),
        skip_llm_verification=True,
    )
    await mem.initialize()
    yield mem
    try:
        if mem._pool and not mem._pool._closing:
            await mem.close()
    except Exception:
        pass


def test_normalize_dream_config_applies_bounds():
    cfg = normalize_dream_config(
        {
            "top_k": 99,
            "max_input_tokens": 10,
            "max_output_tokens": 99999,
            "cooldown_minutes": 1,
            "cron_interval_minutes": 99999,
            "quality_threshold": 9,
            "distillation_mode": "not-valid",
            "distillation_max_fragments": 999,
            "min_recall_results": 0,
            "max_artifact_bytes": 9999999,
            "value_focus": {"money": 10, "time": -1, "happiness": 2.5},
        }
    )
    assert cfg["top_k"] == 8
    assert cfg["max_input_tokens"] == 128
    assert cfg["max_output_tokens"] == 1600
    assert cfg["cooldown_minutes"] == 5
    assert cfg["cron_interval_minutes"] == 24 * 60
    assert cfg["quality_threshold"] == 1.0
    assert cfg["distillation_mode"] == "off"
    assert cfg["distillation_max_fragments"] == 10
    assert cfg["min_recall_results"] == 1
    assert cfg["max_artifact_bytes"] == 120_000
    assert cfg["value_focus"]["money"] == 3.0
    assert cfg["value_focus"]["time"] == 0.0
    assert cfg["value_focus"]["happiness"] == 2.5


def test_score_dream_quality_prefers_structured_text():
    weak = "ok"
    strong = (
        "Pattern: user behavior is stabilizing.\n"
        "Next: likely increase in usage.\n"
        "What-if: if context changes, risk rises.\n"
        "Action: verify with one follow-up."
    )
    assert score_dream_quality(strong, top_k=4) > score_dream_quality(weak, top_k=1)


def test_build_dream_html_contains_metadata():
    html_doc = build_dream_html(
        bank_id="bank-1",
        run_type="dream",
        generated_text="Meaningful insight",
        quality_score=0.8,
    )
    assert "bank=bank-1" in html_doc
    assert "Meaningful insight" in html_doc


def test_build_dream_html_respects_max_bytes():
    html_doc = build_dream_html(
        bank_id="bank-1",
        run_type="dream",
        generated_text="x" * 50000,
        quality_score=0.8,
        max_bytes=5000,
    )
    assert len(html_doc.encode("utf-8")) <= 5050


def test_preset_defaults_are_available():
    assert set(PRESET_OVERRIDES.keys()) == {"balanced_org", "lean_local", "risk_guard", "exec_strategy"}


def test_preset_application_and_override_priority():
    cfg = normalize_dream_config({"preset": "lean_local", "max_output_tokens": 777})
    # Preset applies
    assert cfg["preset"] == "lean_local"
    assert cfg["value_focus"]["time"] == 1.4
    # Explicit override still wins
    assert cfg["max_output_tokens"] == 777


def test_memoryfact_compat_field_name_fact_type():
    class Fact:
        def __init__(self):
            self.id = "abc"
            self.fact_type = "world"
            self.text = "hello"

    r = Fact()
    fact_type = getattr(r, "fact_type", None) or getattr(r, "type", None) or "unknown"
    assert fact_type == "world"


def test_compute_novelty_and_maturity():
    novelty = compute_novelty_score("Anurag will likely validate the coffee preference soon", ["Bank will validate coffee preference soon"])
    assert 0.0 <= novelty < 0.6
    assert infer_maturity_tier(evidence_count=2, recurring_entities=1, contradiction_count=0, confirmed_predictions=0) == "sparse"
    assert infer_maturity_tier(evidence_count=8, recurring_entities=3, contradiction_count=1, confirmed_predictions=2) == "mature"


async def _enable_dream_mode(memory, bank_id: str, request_context):
    await memory.get_bank_profile(bank_id, request_context=request_context)
    await memory._config_resolver.update_bank_config(
        bank_id,
        {
            "dream": {
                "enabled": True,
                "trance_enabled": True,
                "top_k": 4,
                "min_recall_results": 2,
                "novelty_threshold": 0.58,
                "quality_threshold": 0.5,
            }
        },
        request_context,
    )


def _fake_memory_fact(idx: int, text: str, *, entities: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"mem-{idx}",
        text=text,
        fact_type="observation",
        entities=entities,
        created_at=datetime.now(UTC),
        occurred_start=None,
        mentioned_at=None,
    )


@pytest.mark.asyncio
async def test_dream_generation_low_signal_persists_explicit_run(dream_memory, request_context, monkeypatch):
    bank_id = f"dream-low-signal-{uuid4().hex[:8]}"
    await _enable_dream_mode(dream_memory, bank_id, request_context)

    async def fake_recall_async(*args, **kwargs):
        return SimpleNamespace(results=[_fake_memory_fact(1, "Coffee matters to the user", entities=["coffee"])])

    async def fake_graph_intelligence(*args, **kwargs):
        return {"nodes": [], "change_events": []}

    monkeypatch.setattr(dream_memory, "recall_async", fake_recall_async)
    monkeypatch.setattr(dream_memory, "get_graph_intelligence", fake_graph_intelligence)

    await dream_memory._handle_dream_generation(
        {"bank_id": bank_id, "trigger_source": "manual", "run_type": "dream"}
    )
    items = await dream_memory.list_dream_artifacts(bank_id, request_context=request_context)
    assert items[0]["status"] == "low_signal"
    assert "enough stable evidence" in (items[0]["summary"] or "").lower()
    assert items[0]["predictions"] == []


@pytest.mark.asyncio
async def test_dream_generation_failed_llm_does_not_emit_fake_artifact(dream_memory, request_context, monkeypatch):
    bank_id = f"dream-failed-llm-{uuid4().hex[:8]}"
    await _enable_dream_mode(dream_memory, bank_id, request_context)

    async def fake_recall_async(*args, **kwargs):
        return SimpleNamespace(
            results=[
                _fake_memory_fact(1, "Anurag prefers black coffee for focus", entities=["Anurag", "coffee"]),
                _fake_memory_fact(2, "The team is optimizing for fast iteration", entities=["team"]),
            ]
        )

    async def fake_graph_intelligence(*args, **kwargs):
        return {"nodes": [{"status_reason": "Team behavior is stabilizing."}], "change_events": []}

    monkeypatch.setattr(dream_memory, "recall_async", fake_recall_async)
    monkeypatch.setattr(dream_memory, "get_graph_intelligence", fake_graph_intelligence)
    dream_memory._reflect_llm_config.set_mock_exception(RuntimeError("dream llm failed"))

    await dream_memory._handle_dream_generation(
        {"bank_id": bank_id, "trigger_source": "manual", "run_type": "dream"}
    )
    items = await dream_memory.list_dream_artifacts(bank_id, request_context=request_context)
    assert items[0]["status"] == "failed_llm"
    assert "dream llm failed" in (items[0]["failure_reason"] or "")
    assert items[0]["narrative_html"] is None


@pytest.mark.asyncio
async def test_dream_generation_quality_threshold_marks_failed_validation(
    dream_memory, request_context, monkeypatch
):
    bank_id = f"dream-failed-validation-{uuid4().hex[:8]}"
    await _enable_dream_mode(dream_memory, bank_id, request_context)
    current = await dream_memory._config_resolver.resolve_full_config(bank_id, request_context)
    await dream_memory._config_resolver.update_bank_config(
        bank_id,
        {"dream": {**current.dream, "quality_threshold": 0.95}},
        request_context,
    )

    async def fake_recall_async(*args, **kwargs):
        return SimpleNamespace(
            results=[
                _fake_memory_fact(1, "Anurag prefers black coffee for focus", entities=["Anurag", "coffee"]),
                _fake_memory_fact(2, "The team runs short validation loops before shipping", entities=["team"]),
            ]
        )

    async def fake_graph_intelligence(*args, **kwargs):
        return {"nodes": [{"status_reason": "One focus pattern is visible."}], "change_events": []}

    monkeypatch.setattr(dream_memory, "recall_async", fake_recall_async)
    monkeypatch.setattr(dream_memory, "get_graph_intelligence", fake_graph_intelligence)
    dream_memory._reflect_llm_config.set_mock_response(
        {
            "summary": "There may be an emerging focus ritual, but the evidence is still thin.",
            "hypotheses": ["A focus ritual may be forming."],
            "predicted_next_events": [
                {
                    "title": "Coffee keeps appearing in focus sessions",
                    "description": "The next few work memories may mention coffee before work.",
                    "target_ref": "Anurag",
                    "target_kind": "entity",
                    "horizon": "near_term",
                    "confidence": 0.62,
                    "success_criteria": ["A new memory mentions coffee before work"],
                    "expiration_window_days": 14,
                }
            ],
            "predicted_state_changes": ["Preparation rituals become slightly more visible."],
            "growth_hypotheses": [],
            "risks": ["The pattern may be over-read from too little data."],
            "opportunities": ["Gather a few more sessions before codifying the pattern."],
            "recommended_validations": ["Check the next three work-session memories."],
            "promotion_proposals": [
                {
                    "proposal_type": "observation",
                    "title": "Tentative ritual candidate",
                    "content": "Coffee may be a pre-focus ritual, but this needs more proof.",
                    "confidence": 0.58,
                    "tags": ["dream"],
                    "supporting_evidence_ids": ["mem-1"],
                    "review_status": "proposed",
                }
            ],
            "narrative": "A possible pattern is visible, but it is not strong enough yet.",
        }
    )

    await dream_memory._handle_dream_generation(
        {"bank_id": bank_id, "trigger_source": "manual", "run_type": "dream"}
    )
    items = await dream_memory.list_dream_artifacts(bank_id, request_context=request_context)
    assert items[0]["status"] == "failed_validation"
    assert items[0]["promotion_proposals"] == []
    assert "Raise the dream quality above 0.95" in " ".join(items[0]["signals"]["recommended_validations"])


@pytest.mark.asyncio
async def test_dream_generation_stores_predictions_and_reviewable_proposals(
    dream_memory, request_context, monkeypatch
):
    bank_id = f"dream-success-{uuid4().hex[:8]}"
    await _enable_dream_mode(dream_memory, bank_id, request_context)

    async def fake_recall_async(*args, **kwargs):
        return SimpleNamespace(
            results=[
                _fake_memory_fact(1, "Anurag chooses black coffee before deep work", entities=["Anurag", "coffee"]),
                _fake_memory_fact(2, "Repeated work sessions happen after the coffee ritual", entities=["Anurag"]),
                _fake_memory_fact(3, "Fast validation loops reduce rework for the team", entities=["team"]),
            ]
        )

    async def fake_graph_intelligence(*args, **kwargs):
        return {
            "nodes": [{"status_reason": "Anurag's preference trend is stable."}],
            "change_events": [{"change_type": "change", "summary": "Focus rituals are becoming more repeatable."}],
        }

    monkeypatch.setattr(dream_memory, "recall_async", fake_recall_async)
    monkeypatch.setattr(dream_memory, "get_graph_intelligence", fake_graph_intelligence)
    dream_memory._reflect_llm_config.set_mock_response(
        {
            "summary": "A repeatable focus ritual is forming around coffee and fast validation.",
            "hypotheses": ["The bank is converging on a stable focus ritual for deep work."],
            "predicted_next_events": [
                {
                    "title": "Coffee ritual remains part of focus sessions",
                    "description": "Future deep-work memories will keep referencing black coffee before execution.",
                    "target_ref": "Anurag",
                    "target_kind": "entity",
                    "horizon": "near_term",
                    "confidence": 0.81,
                    "success_criteria": ["A new observation mentions black coffee before work"],
                    "expiration_window_days": 14,
                }
            ],
            "predicted_state_changes": ["Focus sessions become more intentional and easier to start."],
            "growth_hypotheses": [
                {
                    "title": "Ritualized preparation",
                    "description": "A stable ritual is helping the bank convert intent into action with less hesitation.",
                    "confidence": 0.73,
                    "signals": ["coffee before work", "fast validation loops"],
                }
            ],
            "risks": ["Overfitting to one ritual could hide emerging contradictions."],
            "opportunities": ["The bank can formalize this ritual into a reusable mental model."],
            "recommended_validations": ["Check the next few focus-session memories for the same sequence."],
            "promotion_proposals": [
                {
                    "proposal_type": "mental_model",
                    "title": "Focus ritual for execution",
                    "content": "When a focused session matters, the bank benefits from a short preparation ritual and one fast validation loop.",
                    "confidence": 0.75,
                    "tags": ["dream", "focus"],
                    "supporting_evidence_ids": ["mem-1", "mem-2"],
                    "review_status": "proposed",
                }
            ],
            "narrative": "The dream points to a bank that is becoming more deliberate and faster at starting meaningful work.",
        }
    )

    await dream_memory._handle_dream_generation(
        {"bank_id": bank_id, "trigger_source": "manual", "run_type": "dream"}
    )
    items = await dream_memory.list_dream_artifacts(bank_id, request_context=request_context)
    run = items[0]
    assert run["predictions"][0]["title"] == "Coffee ritual remains part of focus sessions"
    assert run["promotion_proposals"][0]["title"] == "Focus ritual for execution"
    assert run["growth_hypotheses"][0]["title"] == "Ritualized preparation"

    proposal = run["promotion_proposals"][0]
    reviewed = await dream_memory.review_dream_proposal(
        bank_id,
        proposal["proposal_id"],
        action="approve",
        note="Promote this to a reusable model",
        request_context=request_context,
    )
    assert reviewed["review_status"] == "approved"
    mental_models = await dream_memory.list_mental_models(bank_id, request_context=request_context)
    assert any(model["name"] == "Focus ritual for execution" for model in mental_models)

    prediction = run["predictions"][0]
    outcome = await dream_memory.update_dream_prediction_outcome(
        bank_id,
        prediction["prediction_id"],
        status="confirmed",
        note="Validated in the latest work session",
        evidence_ids=["mem-1"],
        request_context=request_context,
    )
    assert outcome["prediction"]["status"] == "confirmed"
    assert outcome["outcome"]["status"] == "confirmed"
