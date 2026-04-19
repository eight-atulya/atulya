"""Unit tests for StructuredDocument schema, renderer, parser, and delta op
application.

Covers:
- Block/Section/Document Pydantic schema (validation, extra=forbid, defaults)
- Slugify + make_unique_id stability
- Deterministic byte-stable render
- Lenient parser (round-trips, implicit Overview, separator handling)
- apply_operations (every op type happy path + every invalid case)
- "Sections not mentioned by any op are physically unchanged" invariant
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atulya_api.engine.reflect.delta_ops import (
    AddSectionOp,
    AppendBlockOp,
    AppliedDelta,
    DeltaOperationList,
    InsertBlockOp,
    RemoveBlockOp,
    RemoveSectionOp,
    RenameSectionOp,
    ReplaceBlockOp,
    ReplaceSectionBlocksOp,
    apply_operations,
)
from atulya_api.engine.reflect.structured_doc import (
    BulletListBlock,
    CodeBlock,
    OrderedListBlock,
    ParagraphBlock,
    Section,
    StructuredDocument,
    make_unique_id,
    parse_markdown,
    render_block,
    render_document,
    render_section,
    slugify_heading,
)


# ----- Schema (10 tests) ----------------------------------------------------


class TestBlockSchema:
    def test_paragraph_block_basic(self):
        b = ParagraphBlock(text="hello")
        assert b.type == "paragraph"
        assert b.text == "hello"

    def test_paragraph_block_rejects_extra(self):
        with pytest.raises(ValidationError):
            ParagraphBlock(text="x", foo="y")  # type: ignore[call-arg]

    def test_bullet_list_default_items_empty(self):
        b = BulletListBlock()
        assert b.items == []

    def test_ordered_list_holds_items(self):
        b = OrderedListBlock(items=["a", "b"])
        assert b.items == ["a", "b"]

    def test_code_block_default_language_empty(self):
        b = CodeBlock(text="print(1)")
        assert b.language == ""
        assert b.text == "print(1)"


class TestSectionSchema:
    def test_section_default_level_2(self):
        s = Section(id="x", heading="Hello")
        assert s.level == 2
        assert s.blocks == []

    def test_section_rejects_level_out_of_range(self):
        with pytest.raises(ValidationError):
            Section(id="x", heading="H", level=7)

    def test_section_rejects_level_below_one(self):
        with pytest.raises(ValidationError):
            Section(id="x", heading="H", level=0)


class TestDocumentSchema:
    def test_document_version_pinned(self):
        d = StructuredDocument()
        assert d.version == 1

    def test_document_section_lookup(self):
        s = Section(id="abc", heading="A")
        d = StructuredDocument(sections=[s])
        assert d.section_by_id("abc") is s
        assert d.section_index("abc") == 0
        assert d.section_by_id("missing") is None
        assert d.section_index("missing") is None


# ----- Slug helpers (4 tests) -----------------------------------------------


class TestSlugify:
    def test_slugify_basic(self):
        assert slugify_heading("Stop Conditions") == "stop-conditions"

    def test_slugify_strips_punctuation(self):
        assert slugify_heading("Inputs & Context!") == "inputs-context"

    def test_slugify_empty_falls_back(self):
        assert slugify_heading("???") == "section"

    def test_make_unique_id_disambiguates(self):
        assert make_unique_id("foo", set()) == "foo"
        assert make_unique_id("foo", {"foo"}) == "foo-2"
        assert make_unique_id("foo", {"foo", "foo-2"}) == "foo-3"


# ----- Renderer (6 tests) ---------------------------------------------------


class TestRenderer:
    def test_render_paragraph(self):
        assert render_block(ParagraphBlock(text="hello\n")) == "hello"

    def test_render_bullet_list(self):
        out = render_block(BulletListBlock(items=["a", "b"]))
        assert out == "- a\n- b"

    def test_render_ordered_list(self):
        out = render_block(OrderedListBlock(items=["x", "y", "z"]))
        assert out == "1. x\n2. y\n3. z"

    def test_render_code_block(self):
        out = render_block(CodeBlock(language="python", text="print(1)"))
        assert out == "```python\nprint(1)\n```"

    def test_render_section_heading_blank_line_block(self):
        s = Section(id="x", heading="X", level=2, blocks=[ParagraphBlock(text="hi")])
        assert render_section(s) == "## X\n\nhi"

    def test_render_document_byte_stable(self):
        d = StructuredDocument(
            sections=[
                Section(id="a", heading="A", blocks=[ParagraphBlock(text="alpha")]),
                Section(id="b", heading="B", blocks=[ParagraphBlock(text="beta")]),
            ]
        )
        first = render_document(d)
        second = render_document(d)
        assert first == second
        assert first.endswith("\n")
        assert "## A\n\nalpha\n\n## B\n\nbeta\n" == first


# ----- Parser (8 tests) -----------------------------------------------------


class TestParser:
    def test_parse_empty_returns_empty_doc(self):
        d = parse_markdown("")
        assert d.sections == []

    def test_parse_pre_heading_content_wrapped_in_overview(self):
        d = parse_markdown("Some intro paragraph.\n\n# H1\n\nbody")
        assert d.sections[0].heading == "Overview"
        assert d.sections[0].id == "overview"
        assert d.sections[1].heading == "H1"

    def test_parse_assigns_unique_ids_for_duplicate_headings(self):
        d = parse_markdown("## Notes\n\nfirst\n\n## Notes\n\nsecond")
        assert [s.id for s in d.sections] == ["notes", "notes-2"]

    def test_parse_bullet_list(self):
        d = parse_markdown("## L\n\n- a\n- b\n- c")
        block = d.sections[0].blocks[0]
        assert isinstance(block, BulletListBlock)
        assert block.items == ["a", "b", "c"]

    def test_parse_ordered_list(self):
        d = parse_markdown("## L\n\n1. one\n2. two")
        block = d.sections[0].blocks[0]
        assert isinstance(block, OrderedListBlock)
        assert block.items == ["one", "two"]

    def test_parse_code_block(self):
        d = parse_markdown("## L\n\n```python\nprint(1)\n```")
        block = d.sections[0].blocks[0]
        assert isinstance(block, CodeBlock)
        assert block.language == "python"
        assert block.text == "print(1)"

    def test_parse_treats_horizontal_rule_as_separator(self):
        d = parse_markdown("## A\n\nalpha\n\n---\n\n## B\n\nbeta")
        headings = [s.heading for s in d.sections]
        assert headings == ["A", "B"]
        # No separator content leaks into either section as a paragraph
        for s in d.sections:
            for b in s.blocks:
                assert not (isinstance(b, ParagraphBlock) and "---" in b.text)

    def test_parse_render_round_trip(self):
        original = (
            "## A\n\nalpha\n\n## B\n\n- x\n- y\n\n## C\n\n```python\ncode\n```\n"
        )
        d = parse_markdown(original)
        rendered = render_document(d)
        assert rendered == original


# ----- apply_operations (11 happy + invalid tests) --------------------------


def _doc_two_sections() -> StructuredDocument:
    return StructuredDocument(
        sections=[
            Section(
                id="alpha",
                heading="Alpha",
                blocks=[
                    ParagraphBlock(text="a1"),
                    ParagraphBlock(text="a2"),
                ],
            ),
            Section(
                id="beta",
                heading="Beta",
                blocks=[ParagraphBlock(text="b1")],
            ),
        ]
    )


class TestApplyOperations:
    def test_empty_op_list_is_no_op(self):
        doc = _doc_two_sections()
        outcome = apply_operations(doc, [])
        assert isinstance(outcome, AppliedDelta)
        assert outcome.changed is False
        assert render_document(outcome.document) == render_document(doc)

    def test_append_block(self):
        doc = _doc_two_sections()
        outcome = apply_operations(
            doc,
            [AppendBlockOp(section_id="alpha", block=ParagraphBlock(text="a3"))],
        )
        assert outcome.changed is True
        assert len(outcome.document.section_by_id("alpha").blocks) == 3

    def test_insert_block(self):
        doc = _doc_two_sections()
        outcome = apply_operations(
            doc,
            [
                InsertBlockOp(
                    section_id="alpha", index=1, block=ParagraphBlock(text="middle")
                )
            ],
        )
        section = outcome.document.section_by_id("alpha")
        texts = [b.text for b in section.blocks]
        assert texts == ["a1", "middle", "a2"]

    def test_replace_block(self):
        doc = _doc_two_sections()
        outcome = apply_operations(
            doc,
            [
                ReplaceBlockOp(
                    section_id="alpha", index=0, block=ParagraphBlock(text="a1-new")
                )
            ],
        )
        section = outcome.document.section_by_id("alpha")
        assert section.blocks[0].text == "a1-new"

    def test_remove_block(self):
        doc = _doc_two_sections()
        outcome = apply_operations(doc, [RemoveBlockOp(section_id="alpha", index=0)])
        section = outcome.document.section_by_id("alpha")
        assert len(section.blocks) == 1
        assert section.blocks[0].text == "a2"

    def test_add_section_appended_when_no_after_id(self):
        doc = _doc_two_sections()
        outcome = apply_operations(
            doc,
            [
                AddSectionOp(
                    heading="Gamma",
                    blocks=[ParagraphBlock(text="g1")],
                )
            ],
        )
        ids = [s.id for s in outcome.document.sections]
        assert ids == ["alpha", "beta", "gamma"]
        applied_entry = outcome.applied[0]
        assert applied_entry["assigned_id"] == "gamma"

    def test_add_section_after_specified(self):
        doc = _doc_two_sections()
        outcome = apply_operations(
            doc,
            [
                AddSectionOp(
                    heading="Middle",
                    after_section_id="alpha",
                    blocks=[ParagraphBlock(text="m1")],
                )
            ],
        )
        ids = [s.id for s in outcome.document.sections]
        assert ids == ["alpha", "middle", "beta"]

    def test_add_section_disambiguates_id(self):
        doc = _doc_two_sections()
        outcome = apply_operations(
            doc,
            [AddSectionOp(heading="Alpha", blocks=[])],
        )
        ids = [s.id for s in outcome.document.sections]
        assert ids == ["alpha", "beta", "alpha-2"]

    def test_remove_section(self):
        doc = _doc_two_sections()
        outcome = apply_operations(doc, [RemoveSectionOp(section_id="beta")])
        ids = [s.id for s in outcome.document.sections]
        assert ids == ["alpha"]

    def test_replace_section_blocks(self):
        doc = _doc_two_sections()
        outcome = apply_operations(
            doc,
            [
                ReplaceSectionBlocksOp(
                    section_id="alpha",
                    blocks=[BulletListBlock(items=["new1", "new2"])],
                )
            ],
        )
        section = outcome.document.section_by_id("alpha")
        assert len(section.blocks) == 1
        assert isinstance(section.blocks[0], BulletListBlock)
        # heading and id preserved
        assert section.heading == "Alpha"
        assert section.id == "alpha"

    def test_rename_section_preserves_id(self):
        doc = _doc_two_sections()
        outcome = apply_operations(
            doc,
            [RenameSectionOp(section_id="alpha", new_heading="Aleph")],
        )
        section = outcome.document.section_by_id("alpha")
        assert section.heading == "Aleph"
        assert section.id == "alpha"


# ----- Invalid op handling (no-op, recorded in skipped) ---------------------


class TestApplyOperationsSkipsInvalid:
    def test_unknown_section_id_skips(self):
        doc = _doc_two_sections()
        outcome = apply_operations(
            doc,
            [AppendBlockOp(section_id="missing", block=ParagraphBlock(text="x"))],
        )
        assert outcome.applied == []
        assert len(outcome.skipped) == 1
        assert "unknown section_id" in outcome.skipped[0]["reason"]
        # Document unchanged
        assert render_document(outcome.document) == render_document(doc)

    def test_index_out_of_range_replace_skips(self):
        doc = _doc_two_sections()
        outcome = apply_operations(
            doc,
            [
                ReplaceBlockOp(
                    section_id="alpha", index=99, block=ParagraphBlock(text="x")
                )
            ],
        )
        assert outcome.applied == []
        assert len(outcome.skipped) == 1

    def test_insert_index_at_end_allowed(self):
        doc = _doc_two_sections()
        outcome = apply_operations(
            doc,
            [InsertBlockOp(section_id="alpha", index=2, block=ParagraphBlock(text="end"))],
        )
        assert len(outcome.applied) == 1
        section = outcome.document.section_by_id("alpha")
        assert section.blocks[-1].text == "end"

    def test_add_section_after_missing_skips(self):
        doc = _doc_two_sections()
        outcome = apply_operations(
            doc,
            [AddSectionOp(heading="Z", after_section_id="nope")],
        )
        assert outcome.applied == []
        assert len(outcome.skipped) == 1


# ----- Preservation invariant ----------------------------------------------


class TestPreservationInvariant:
    def test_sections_not_mentioned_are_byte_identical(self):
        """The core promise: any section not targeted by any op renders byte-identical."""
        doc = _doc_two_sections()
        before_beta = render_section(doc.section_by_id("beta"))

        outcome = apply_operations(
            doc,
            [
                AppendBlockOp(section_id="alpha", block=ParagraphBlock(text="new")),
                AddSectionOp(heading="Gamma", blocks=[ParagraphBlock(text="g")]),
            ],
        )
        after_beta = render_section(outcome.document.section_by_id("beta"))
        assert before_beta == after_beta

    def test_original_document_not_mutated(self):
        doc = _doc_two_sections()
        original_render = render_document(doc)
        apply_operations(
            doc,
            [
                ReplaceSectionBlocksOp(
                    section_id="alpha",
                    blocks=[ParagraphBlock(text="replaced")],
                )
            ],
        )
        assert render_document(doc) == original_render


# ----- DeltaOperationList JSON round-trip (text-mode JSON path) ------------


class TestDeltaOperationListJSON:
    def test_empty_operations_validates(self):
        op_list = DeltaOperationList.model_validate_json('{"operations": []}')
        assert op_list.operations == []

    def test_append_block_op_round_trip_via_json(self):
        text = (
            '{"operations": [{"op": "append_block", "section_id": "x", '
            '"block": {"type": "paragraph", "text": "hello"}}]}'
        )
        op_list = DeltaOperationList.model_validate_json(text)
        assert len(op_list.operations) == 1
        op = op_list.operations[0]
        assert isinstance(op, AppendBlockOp)
        assert op.section_id == "x"
        assert isinstance(op.block, ParagraphBlock)
        assert op.block.text == "hello"

    def test_unknown_op_discriminator_rejected(self):
        with pytest.raises(ValidationError):
            DeltaOperationList.model_validate_json(
                '{"operations": [{"op": "yeet", "section_id": "x"}]}'
            )

    def test_extra_field_rejected_on_op(self):
        with pytest.raises(ValidationError):
            DeltaOperationList.model_validate_json(
                '{"operations": [{"op": "remove_section", '
                '"section_id": "x", "bogus": 1}]}'
            )
