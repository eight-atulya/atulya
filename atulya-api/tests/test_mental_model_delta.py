"""Plumbing tests for delta-mode mental model refresh.

Mocks ``reflect_async`` and ``_reflect_llm_config.call`` so the tests run in
sub-second time and don't depend on a live LLM. The eval class
(``TestDeltaRefreshGeminiEval``) exercises a real LLM and is gated on
``ATULYA_RUN_GEMINI_EVALS=1``.

Asserts the structural guarantees that make delta mode safe for production:
- mode=full path never invokes the delta call,
- empty structured_content forces full fallback,
- subsequent delta refresh produces byte-identical untouched sections,
- source_query change forces full rebuild,
- empty reflect candidate preserves the previous content (regression for the
  destroying-working-document bug),
- delta-call failure falls back to the candidate markdown.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from atulya_api import RequestContext
from atulya_api.engine.memory_engine import MemoryEngine
from atulya_api.engine.reflect.structured_doc import (
    BulletListBlock,
    ParagraphBlock,
    Section,
    StructuredDocument,
    parse_markdown,
    render_document,
)
from atulya_api.engine.response_models import ReflectResult


def _two_section_doc() -> StructuredDocument:
    return StructuredDocument(
        sections=[
            Section(
                id="members",
                heading="Members",
                blocks=[BulletListBlock(items=["Alice — frontend", "Bob — backend"])],
            ),
            Section(
                id="rituals",
                heading="Rituals",
                blocks=[ParagraphBlock(text="Daily standup at 9am.")],
            ),
        ]
    )


def _stub_reflect_result(text: str) -> ReflectResult:
    return ReflectResult(
        text=text,
        based_on={
            "world": [
                {
                    "id": str(uuid.uuid4()),
                    "text": "Carol just joined as a junior engineer.",
                    "type": "world",
                    "context": None,
                }
            ]
        },
    )


class TestDeltaRefreshPlumbing:
    """Mocked-LLM tests for the full/delta branching surface."""

    @pytest.mark.asyncio
    async def test_full_mode_calls_reflect_only(
        self, memory: MemoryEngine, request_context: RequestContext
    ):
        """``mode=full`` (default trigger) never invokes the delta LLM call."""
        bank_id = f"test-mm-delta-full-{uuid.uuid4().hex[:8]}"
        await memory.get_bank_profile(bank_id, request_context=request_context)

        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team",
            source_query="who is on the team?",
            content="## Members\n\n- Alice\n",
            trigger={"mode": "full", "refresh_after_consolidation": False},
            request_context=request_context,
        )

        candidate = "## Members\n\n- Alice\n- Bob\n"
        with (
            patch.object(memory, "reflect_async", new=AsyncMock(return_value=_stub_reflect_result(candidate))),
            patch.object(memory._reflect_llm_config, "call", new=AsyncMock(return_value="{\"operations\": []}")) as delta_call,
        ):
            updated = await memory.refresh_mental_model(
                bank_id, mm["id"], request_context=request_context
            )

        assert updated is not None
        assert delta_call.await_count == 0
        assert updated["content"] == candidate
        assert updated["last_refreshed_source_query"] == "who is on the team?"
        assert updated["structured_content"] is not None

        await memory.delete_bank(bank_id, request_context=request_context)

    @pytest.mark.asyncio
    async def test_delta_mode_first_refresh_falls_back_to_full(
        self, memory: MemoryEngine, request_context: RequestContext
    ):
        """``mode=delta`` with no stored ``structured_content`` falls back to full."""
        bank_id = f"test-mm-delta-first-{uuid.uuid4().hex[:8]}"
        await memory.get_bank_profile(bank_id, request_context=request_context)

        # Create with empty content so the delta-eligibility check fails on
        # both content and structured_content.
        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team",
            source_query="who is on the team?",
            content="",
            trigger={"mode": "delta", "refresh_after_consolidation": False},
            request_context=request_context,
        )

        candidate = "## Members\n\n- Alice\n"
        with (
            patch.object(memory, "reflect_async", new=AsyncMock(return_value=_stub_reflect_result(candidate))),
            patch.object(memory._reflect_llm_config, "call", new=AsyncMock(return_value="{\"operations\": []}")) as delta_call,
        ):
            updated = await memory.refresh_mental_model(
                bank_id, mm["id"], request_context=request_context
            )

        assert updated is not None
        assert delta_call.await_count == 0
        assert updated["content"] == candidate
        # Structured baseline parsed from the candidate markdown.
        assert updated["structured_content"] is not None
        assert any(s["heading"] == "Members" for s in updated["structured_content"]["sections"])

        await memory.delete_bank(bank_id, request_context=request_context)

    @pytest.mark.asyncio
    async def test_delta_mode_subsequent_refresh_uses_ops(
        self, memory: MemoryEngine, request_context: RequestContext
    ):
        """Populated structured_content + unchanged source_query → delta path runs.

        Asserts that sections not touched by any op come through byte-identical.
        """
        bank_id = f"test-mm-delta-ops-{uuid.uuid4().hex[:8]}"
        await memory.get_bank_profile(bank_id, request_context=request_context)

        seed_doc = _two_section_doc()
        seed_markdown = render_document(seed_doc)

        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team",
            source_query="team composition and rituals",
            content=seed_markdown,
            trigger={"mode": "delta", "refresh_after_consolidation": False},
            request_context=request_context,
        )

        # Seed structured_content + last_refreshed_source_query so the
        # eligibility check passes.
        await memory.update_mental_model(
            bank_id,
            mm["id"],
            structured_content=seed_doc.model_dump(),
            last_refreshed_source_query="team composition and rituals",
            request_context=request_context,
        )

        rendered_rituals_before = "## " + seed_doc.sections[1].heading + "\n\nDaily standup at 9am."

        delta_response = (
            '{"operations": [{"op": "append_block", "section_id": "members", '
            '"block": {"type": "bullet_list", "items": ["Carol \\u2014 junior engineer"]}}]}'
        )

        with (
            patch.object(memory, "reflect_async", new=AsyncMock(return_value=_stub_reflect_result("ignored candidate"))),
            patch.object(memory._reflect_llm_config, "call", new=AsyncMock(return_value=delta_response)) as delta_call,
        ):
            updated = await memory.refresh_mental_model(
                bank_id, mm["id"], request_context=request_context
            )

        assert updated is not None
        assert delta_call.await_count == 1
        assert "Carol" in updated["content"]
        # Rituals section is rendered byte-identical (no LLM re-emission).
        assert rendered_rituals_before in updated["content"]
        assert updated["reflect_response"]["delta_succeeded"] is True

        await memory.delete_bank(bank_id, request_context=request_context)

    @pytest.mark.asyncio
    async def test_source_query_change_forces_full(
        self, memory: MemoryEngine, request_context: RequestContext
    ):
        """If ``source_query`` differs from ``last_refreshed_source_query``, fall back to full."""
        bank_id = f"test-mm-delta-sqchange-{uuid.uuid4().hex[:8]}"
        await memory.get_bank_profile(bank_id, request_context=request_context)

        seed_doc = _two_section_doc()
        seed_markdown = render_document(seed_doc)

        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team",
            source_query="updated query about the team",
            content=seed_markdown,
            trigger={"mode": "delta", "refresh_after_consolidation": False},
            request_context=request_context,
        )

        # Stored last_refreshed_source_query is intentionally the OLD query.
        await memory.update_mental_model(
            bank_id,
            mm["id"],
            structured_content=seed_doc.model_dump(),
            last_refreshed_source_query="old query about the team",
            request_context=request_context,
        )

        candidate = "## Members\n\n- Alice\n- Bob\n- Carol\n"
        with (
            patch.object(memory, "reflect_async", new=AsyncMock(return_value=_stub_reflect_result(candidate))),
            patch.object(memory._reflect_llm_config, "call", new=AsyncMock(return_value="{\"operations\": []}")) as delta_call,
        ):
            updated = await memory.refresh_mental_model(
                bank_id, mm["id"], request_context=request_context
            )

        assert updated is not None
        assert delta_call.await_count == 0
        assert updated["content"] == candidate
        assert updated["last_refreshed_source_query"] == "updated query about the team"

        await memory.delete_bank(bank_id, request_context=request_context)

    @pytest.mark.asyncio
    async def test_empty_candidate_preserves_existing(
        self, memory: MemoryEngine, request_context: RequestContext
    ):
        """Empty reflect answer must NOT destroy existing content."""
        bank_id = f"test-mm-delta-empty-{uuid.uuid4().hex[:8]}"
        await memory.get_bank_profile(bank_id, request_context=request_context)

        seed_doc = _two_section_doc()
        seed_markdown = render_document(seed_doc)

        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team",
            source_query="team",
            content=seed_markdown,
            trigger={"mode": "delta", "refresh_after_consolidation": False},
            request_context=request_context,
        )
        await memory.update_mental_model(
            bank_id,
            mm["id"],
            structured_content=seed_doc.model_dump(),
            last_refreshed_source_query="team",
            request_context=request_context,
        )

        with (
            patch.object(memory, "reflect_async", new=AsyncMock(return_value=_stub_reflect_result(""))),
            patch.object(memory._reflect_llm_config, "call", new=AsyncMock()) as delta_call,
        ):
            updated = await memory.refresh_mental_model(
                bank_id, mm["id"], request_context=request_context
            )

        assert updated is not None
        # Delta call must NOT have fired — empty candidate guard short-circuits early.
        assert delta_call.await_count == 0
        # Content preserved byte-for-byte.
        assert updated["content"] == seed_markdown
        # Structured content preserved (still two sections).
        assert updated["structured_content"] is not None
        assert len(updated["structured_content"]["sections"]) == 2
        assert updated["reflect_response"].get("refresh_skipped") == "empty_candidate"
        # Source-query tracker still bumped so future no-op refreshes can
        # consult it without an off-by-one.
        assert updated["last_refreshed_source_query"] == "team"

        await memory.delete_bank(bank_id, request_context=request_context)

    @pytest.mark.asyncio
    async def test_delta_call_failure_falls_back_to_candidate(
        self, memory: MemoryEngine, request_context: RequestContext
    ):
        """A delta LLM exception must fall back to the reflect candidate."""
        bank_id = f"test-mm-delta-fallback-{uuid.uuid4().hex[:8]}"
        await memory.get_bank_profile(bank_id, request_context=request_context)

        seed_doc = _two_section_doc()
        seed_markdown = render_document(seed_doc)

        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team",
            source_query="team",
            content=seed_markdown,
            trigger={"mode": "delta", "refresh_after_consolidation": False},
            request_context=request_context,
        )
        await memory.update_mental_model(
            bank_id,
            mm["id"],
            structured_content=seed_doc.model_dump(),
            last_refreshed_source_query="team",
            request_context=request_context,
        )

        candidate = "## Members\n\n- Alice\n- Bob\n- Carol\n"
        with (
            patch.object(memory, "reflect_async", new=AsyncMock(return_value=_stub_reflect_result(candidate))),
            patch.object(
                memory._reflect_llm_config,
                "call",
                new=AsyncMock(side_effect=RuntimeError("delta LLM exploded")),
            ),
        ):
            updated = await memory.refresh_mental_model(
                bank_id, mm["id"], request_context=request_context
            )

        assert updated is not None
        # Final content == candidate; structured baseline parsed from it.
        assert updated["content"] == candidate
        assert updated["reflect_response"].get("delta_succeeded") is False
        assert "delta_error" in updated["reflect_response"]
        baseline = parse_markdown(candidate)
        assert updated["structured_content"] == baseline.model_dump()

        await memory.delete_bank(bank_id, request_context=request_context)


# ---------------------------------------------------------------------------
# Real-LLM eval tests (gated on ATULYA_RUN_GEMINI_EVALS=1).
# ---------------------------------------------------------------------------


_run_evals = os.getenv("ATULYA_RUN_GEMINI_EVALS") == "1"


@pytest.mark.skipif(not _run_evals, reason="ATULYA_RUN_GEMINI_EVALS!=1 — skipping real-LLM evals")
class TestDeltaRefreshGeminiEval:
    """End-to-end refresh against a real LLM (Gemini preferred, OpenAI fallback)."""

    @pytest.fixture(autouse=True)
    def _eval_provider_env(self, monkeypatch):
        # If the ambient memory fixture's provider isn't a real cloud LLM, the
        # eval would hit a local model and the assertions would be flaky.
        # We document but don't enforce — the tests skip unless the operator
        # opts in via the env flag.
        yield

    @pytest.mark.asyncio
    async def test_delta_preserves_unchanged_section_byte_identical(
        self, memory: MemoryEngine, request_context: RequestContext
    ):
        bank_id = f"test-mm-eval-preserve-{uuid.uuid4().hex[:8]}"
        await memory.get_bank_profile(bank_id, request_context=request_context)

        seed_doc = _two_section_doc()
        seed_markdown = render_document(seed_doc)

        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team",
            source_query="team composition and rituals",
            content=seed_markdown,
            trigger={"mode": "delta", "refresh_after_consolidation": False},
            request_context=request_context,
        )
        await memory.update_mental_model(
            bank_id,
            mm["id"],
            structured_content=seed_doc.model_dump(),
            last_refreshed_source_query="team composition and rituals",
            request_context=request_context,
        )

        await memory.retain_batch_async(
            bank_id=bank_id,
            contents=[{"content": "Carol joined the team last week as a junior engineer."}],
            request_context=request_context,
        )
        await memory.wait_for_background_tasks()

        rendered_rituals_before = "## " + seed_doc.sections[1].heading + "\n\nDaily standup at 9am."

        updated = await memory.refresh_mental_model(
            bank_id, mm["id"], request_context=request_context
        )

        assert updated is not None
        assert rendered_rituals_before in updated["content"], (
            "Rituals section must remain byte-identical after a delta refresh "
            "that only adds info to Members"
        )

        await memory.delete_bank(bank_id, request_context=request_context)

    @pytest.mark.asyncio
    async def test_delta_appends_to_correct_section(
        self, memory: MemoryEngine, request_context: RequestContext
    ):
        bank_id = f"test-mm-eval-append-{uuid.uuid4().hex[:8]}"
        await memory.get_bank_profile(bank_id, request_context=request_context)

        seed_doc = _two_section_doc()
        seed_markdown = render_document(seed_doc)

        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team",
            source_query="team composition",
            content=seed_markdown,
            trigger={"mode": "delta", "refresh_after_consolidation": False},
            request_context=request_context,
        )
        await memory.update_mental_model(
            bank_id,
            mm["id"],
            structured_content=seed_doc.model_dump(),
            last_refreshed_source_query="team composition",
            request_context=request_context,
        )

        await memory.retain_batch_async(
            bank_id=bank_id,
            contents=[{"content": "Dave joined as a senior engineer this month."}],
            request_context=request_context,
        )
        await memory.wait_for_background_tasks()

        updated = await memory.refresh_mental_model(
            bank_id, mm["id"], request_context=request_context
        )

        assert updated is not None
        applied = updated["reflect_response"].get("delta_applied") or []
        assert applied, "expected at least one applied op"
        # The append should target the Members section, not Rituals.
        assert all(
            entry.get("section_id") in (None, "members") or entry.get("op") == "add_section"
            for entry in applied
        ), f"unexpected ops touched non-members section: {applied}"

        await memory.delete_bank(bank_id, request_context=request_context)

    @pytest.mark.asyncio
    async def test_full_mode_regenerates_from_scratch(
        self, memory: MemoryEngine, request_context: RequestContext
    ):
        bank_id = f"test-mm-eval-full-{uuid.uuid4().hex[:8]}"
        await memory.get_bank_profile(bank_id, request_context=request_context)

        seed_markdown = "## Existing\n\nold content.\n"
        mm = await memory.create_mental_model(
            bank_id=bank_id,
            name="Team",
            source_query="who is on the team?",
            content=seed_markdown,
            trigger={"mode": "full", "refresh_after_consolidation": False},
            request_context=request_context,
        )

        await memory.retain_batch_async(
            bank_id=bank_id,
            contents=[
                {"content": "Eve is a software engineer who joined in 2025."},
                {"content": "Frank is a product manager."},
            ],
            request_context=request_context,
        )
        await memory.wait_for_background_tasks()

        updated = await memory.refresh_mental_model(
            bank_id, mm["id"], request_context=request_context
        )

        assert updated is not None
        # Full mode should not carry the old "Existing" heading verbatim — the
        # reflect synthesis writes from scratch.
        assert updated["reflect_response"].get("delta_attempted", False) is False

        await memory.delete_bank(bank_id, request_context=request_context)
