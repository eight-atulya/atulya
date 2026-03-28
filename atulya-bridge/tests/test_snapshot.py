from atulya_bridge.snapshot import collect_system_snapshot, render_memory_content, sanitize_bank_id


def test_sanitize_bank_id_normalizes_text():
    assert sanitize_bank_id("System: My MacBook Pro!") == "system-my-macbook-pro"


def test_collect_system_snapshot_has_core_fields():
    snapshot = collect_system_snapshot()
    assert snapshot.hostname
    assert snapshot.system
    assert snapshot.python_version
    assert snapshot.workspace_name
    assert isinstance(snapshot.toolchain, dict)
    assert snapshot.network_scope in {"loopback", "private-network", "public-or-routed", "unavailable"}


def test_render_memory_content_includes_sections():
    snapshot = collect_system_snapshot()
    content = render_memory_content(snapshot)
    assert "# First connection snapshot" in content
    assert "## Platform" in content
    assert snapshot.hostname in content
    assert "Network scope" in content
