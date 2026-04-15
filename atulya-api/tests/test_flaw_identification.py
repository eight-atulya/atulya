from atulya_api.engine.flaw_identification import _detect_cycle


def test_detect_cycle_returns_loop_path():
    adjacency = {
        "a": {"b"},
        "b": {"c"},
        "c": {"a"},
    }
    cycles = _detect_cycle(adjacency)
    assert cycles
    assert cycles[0][0] in {"a", "b", "c"}

