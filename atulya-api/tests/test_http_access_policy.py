from atulya_api.api.access_policy import bank_id_from_payload, bank_id_from_request, required_action


def test_auth_and_admin_surfaces_use_their_own_dependencies():
    assert required_action("POST", "/v1/auth/login") is None
    assert required_action("GET", "/v1/orgs/org-id/members") is None
    assert required_action("GET", "/v1/platform/system/health") is None


def test_memory_and_bank_routes_map_to_canonical_actions():
    assert required_action("POST", "/v1/banks/bank-1/memories/retain") == "memory.retain"
    assert required_action("POST", "/v1/banks/bank-1/recall") == "memory.recall"
    assert required_action("DELETE", "/v1/banks/bank-1") == "bank.delete"
    assert required_action("PATCH", "/v1/banks/bank-1/config") == "bank.config"


def test_forge_brain_and_webhook_routes_are_not_implicit_bank_writes():
    assert required_action("GET", "/v1/banks/bank-1/forge/jobs") == "forge.read"
    assert required_action("POST", "/v1/banks/bank-1/forge/jobs") == "forge.run"
    assert required_action("GET", "/v1/banks/bank-1/forge/export") == "forge.export"
    assert required_action("GET", "/v1/banks/bank-1/brain/status") == "brain.read"
    assert required_action("POST", "/v1/banks/bank-1/brain/learn") == "brain.write"
    assert required_action("DELETE", "/v1/banks/bank-1/webhooks/hook-1") == "webhook.manage"


def test_bank_id_can_be_resolved_from_path_or_query():
    assert bank_id_from_request({"bank_id": "path-bank"}, {"bank_id": "query-bank"}) == "path-bank"
    assert bank_id_from_request({}, {"agent_id": "legacy-bank"}) == "legacy-bank"


def test_bank_id_can_be_resolved_from_json_payload():
    assert bank_id_from_payload({"bank_id": "bank-a"}) == "bank-a"
    assert bank_id_from_payload({"request": {"agent_id": "bank-b"}}) == "bank-b"
    assert bank_id_from_payload([{"bank_id": "bank-a"}]) is None
