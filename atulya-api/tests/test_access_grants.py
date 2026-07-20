from atulya_api.auth import can_perform
from atulya_api.models import RequestContext


def test_owner_role_has_org_scope_for_bank_actions():
    ctx = RequestContext(role="owner", principal_id="principal-1", action_scopes={})

    assert can_perform(ctx, "bank.delete", "bank-a") is True


def test_viewer_requires_bank_scope():
    ctx = RequestContext(
        role="viewer",
        principal_id="principal-1",
        action_scopes={"bank.read": ["bank:bank-a"], "memory.recall": ["bank:bank-a"]},
    )

    assert can_perform(ctx, "bank.read", "bank-a") is True
    assert can_perform(ctx, "bank.read", "bank-b") is False
    assert can_perform(ctx, "bank.write", "bank-a") is False


def test_legacy_api_key_allowlist_still_works():
    ctx = RequestContext(role="user", allowed_bank_ids=["bank-a"])

    assert can_perform(ctx, "memory.recall", "bank-a") is True
    assert can_perform(ctx, "memory.recall", "bank-b") is False


def test_service_role_has_no_implicit_actions():
    ctx = RequestContext(role="service", principal_id="svc-1", action_scopes={})

    assert can_perform(ctx, "memory.retain", "bank-a") is False
