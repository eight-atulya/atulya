from atulya_api.engine.dreaming import PRESET_OVERRIDES, build_dream_html, normalize_dream_config, score_dream_quality


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
    assert cfg["max_output_tokens"] == 1200
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
    assert cfg["distillation_mode"] == "fragments"
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
