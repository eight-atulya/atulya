"""Tests for Taste Studio validation, materialize, and retain adapters."""

from __future__ import annotations

import json

import pytest

from atulya_api.forge.exporters.atr_jsonl import AtrJsonlExporter
from atulya_api.forge.exporters.openai_chat_jsonl import OpenAIChatJsonlExporter
from atulya_api.forge.taste.errors import TasteValidationError
from atulya_api.forge.taste.materialize import materialize_taste_set, materialize_taste_sets, payload_hash
from atulya_api.forge.taste.models import TasteSet
from atulya_api.forge.taste.retain import taste_set_to_retain_item
from atulya_api.forge.taste.validation import parse_import_sets, validate_payload_for_schema


def test_validate_openai_chat_payload():
    validate_payload_for_schema(
        {"messages": [{"role": "user", "content": "hi"}]},
        "openai_chat",
    )


def test_validate_openai_chat_rejects_empty_messages():
    with pytest.raises(TasteValidationError, match="messages"):
        validate_payload_for_schema({"messages": []}, "openai_chat")


def test_validate_openai_chat_rejects_missing_role():
    with pytest.raises(TasteValidationError, match="role"):
        validate_payload_for_schema({"messages": [{"content": "hi"}]}, "openai_chat")


def test_validate_openai_chat_rejects_non_object_message():
    with pytest.raises(TasteValidationError, match="object"):
        validate_payload_for_schema({"messages": ["bad"]}, "openai_chat")


def test_validate_qa_pair_requires_both_fields():
    with pytest.raises(TasteValidationError):
        validate_payload_for_schema({"question": "only q"}, "qa_pair")
    with pytest.raises(TasteValidationError):
        validate_payload_for_schema({"answer": "only a"}, "qa_pair")


def test_validate_qa_pair_rejects_whitespace_only():
    with pytest.raises(TasteValidationError):
        validate_payload_for_schema({"question": "  ", "answer": "ok"}, "qa_pair")


def test_parse_import_rejects_both_jsonl_and_sets():
    with pytest.raises(TasteValidationError, match="not both"):
        parse_import_sets(
            schema_type="qa_pair",
            jsonl='{"question":"q","answer":"a"}',
            sets=[{"question": "q2", "answer": "a2"}],
        )


def test_validate_custom_rejects_empty():
    with pytest.raises(TasteValidationError):
        validate_payload_for_schema({}, "custom")


def test_validate_unknown_schema_type():
    with pytest.raises(TasteValidationError, match="Unknown"):
        validate_payload_for_schema({"x": 1}, "not_real")  # type: ignore[arg-type]


def test_parse_import_jsonl_skips_blank_lines():
    rows = parse_import_sets(
        schema_type="qa_pair",
        jsonl='{"question":"q","answer":"a"}\n\n{"question":"q2","answer":"a2"}',
    )
    assert len(rows) == 2


def test_parse_import_jsonl_invalid_json():
    with pytest.raises(TasteValidationError, match="line 2"):
        parse_import_sets(schema_type="qa_pair", jsonl='{"question":"q","answer":"a"}\n{broken')


def test_parse_import_jsonl_non_object_line():
    with pytest.raises(TasteValidationError, match="object"):
        parse_import_sets(schema_type="qa_pair", jsonl='"just a string"')


def test_parse_import_requires_content():
    with pytest.raises(TasteValidationError, match="requires"):
        parse_import_sets(schema_type="qa_pair")


def test_parse_import_sets_array():
    rows = parse_import_sets(
        schema_type="custom",
        sets=[{"field": "one"}, {"field": "two"}],
    )
    assert len(rows) == 2


def test_materialize_openai_chat_record():
    taste_set = TasteSet(
        id="set-1",
        dataset_id="ds-1",
        bank_id="bank-1",
        set_key="set_0001",
        source_payload={"messages": [{"role": "user", "content": "Hi"}]},
        working_payload={
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
            ]
        },
    )
    record = materialize_taste_set(
        taste_set,
        schema_type="openai_chat",
        dataset_id="ds-1",
        bank_id="bank-1",
    )
    assert record.recipe_id == "taste_studio"
    assert record.quality.exportable is True
    assert record.labels.answer == "Hello"
    assert len(record.timeline.sessions[0].turns) == 2


def test_materialize_qa_pair_labels():
    taste_set = TasteSet(
        id="set-1",
        dataset_id="ds-1",
        bank_id="bank-1",
        set_key="set_0001",
        source_payload={"question": "Q", "answer": "A seed"},
        working_payload={"question": "Q edited", "answer": "A working"},
    )
    record = materialize_taste_set(
        taste_set, schema_type="qa_pair", dataset_id="ds-1", bank_id="bank-1"
    )
    assert record.labels.answer == "A working"
    assert record.labels.gold_answer == "A seed"


def test_materialize_empty_content_not_exportable():
    taste_set = TasteSet(
        id="set-1",
        dataset_id="ds-1",
        bank_id="bank-1",
        set_key="set_0001",
        source_payload={"question": " ", "answer": " "},
        working_payload={"question": " ", "answer": " "},
    )
    record = materialize_taste_set(
        taste_set, schema_type="qa_pair", dataset_id="ds-1", bank_id="bank-1"
    )
    assert record.quality.exportable is False
    assert "empty_content" in record.quality.issues


def test_materialize_custom_schema():
    taste_set = TasteSet(
        id="set-1",
        dataset_id="ds-1",
        bank_id="bank-1",
        set_key="set_0001",
        source_payload={"label": "positive"},
        working_payload={"label": "positive", "score": 0.9},
    )
    record = materialize_taste_set(
        taste_set, schema_type="custom", dataset_id="ds-1", bank_id="bank-1"
    )
    assert record.quality.exportable is True
    assert "score" in record.timeline.sessions[0].turns[0].content


def test_materialize_export_openai_jsonl():
    taste_set = TasteSet(
        id="set-1",
        dataset_id="ds-1",
        bank_id="bank-1",
        set_key="set_0001",
        source_payload={"messages": [{"role": "user", "content": "Hi"}]},
        working_payload={
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
            ]
        },
    )
    record = materialize_taste_set(
        taste_set,
        schema_type="openai_chat",
        dataset_id="ds-1",
        bank_id="bank-1",
    )
    manifest = OpenAIChatJsonlExporter().export([record])
    lines = [json.loads(line) for line in (manifest.content or "").strip().splitlines()]
    assert lines[0]["messages"][1]["content"] == "Hello"


def test_materialize_batch_preserves_order():
    sets = [
        TasteSet(
            id=f"s{i}",
            dataset_id="ds",
            bank_id="b",
            set_key=f"k{i}",
            source_payload={"question": f"q{i}", "answer": f"a{i}"},
            working_payload={"question": f"q{i}", "answer": f"a{i}"},
        )
        for i in range(3)
    ]
    records = materialize_taste_sets(sets, schema_type="qa_pair", dataset_id="ds", bank_id="b")
    manifest = AtrJsonlExporter().export(records)
    lines = [json.loads(line) for line in (manifest.content or "").strip().splitlines()]
    assert len(lines) == 3
    assert lines[0]["tasks"][0]["query"] == "k0"


def test_payload_hash_changes_when_content_changes():
    a = payload_hash({"question": "a", "answer": "b"})
    b = payload_hash({"question": "a", "answer": "c"})
    assert a != b


def test_retain_adapter_openai_chat():
    item = taste_set_to_retain_item(
        TasteSet(
            id="s1",
            dataset_id="d1",
            bank_id="b1",
            set_key="set_0001",
            source_payload={"messages": [{"role": "user", "content": "Hi"}]},
            working_payload={
                "messages": [
                    {"role": "user", "content": "Hi"},
                    {"role": "assistant", "content": "Hello"},
                ]
            },
            taste_tags=["tone:concise"],
        ),
        schema_type="openai_chat",
        dataset_id="d1",
    )
    assert "taste:dataset:d1" in item["tags"]
    assert "source:taste_studio" in item["tags"]
    turns = json.loads(item["content"])
    assert turns[1]["role"] == "assistant"


def test_retain_adapter_qa_pair():
    item = taste_set_to_retain_item(
        TasteSet(
            id="s1",
            dataset_id="d1",
            bank_id="b1",
            set_key="set_0001",
            source_payload={"question": "Q", "answer": "A"},
            working_payload={"question": "Q", "answer": "A"},
        ),
        schema_type="qa_pair",
        dataset_id="d1",
    )
    turns = json.loads(item["content"])
    assert turns[0]["content"] == "Q"
    assert turns[1]["content"] == "A"


def test_retain_adapter_custom_json():
    item = taste_set_to_retain_item(
        TasteSet(
            id="s1",
            dataset_id="d1",
            bank_id="b1",
            set_key="set_0001",
            source_payload={"x": 1},
            working_payload={"x": 1, "y": 2},
        ),
        schema_type="custom",
        dataset_id="d1",
    )
    assert '"y": 2' in item["content"]
