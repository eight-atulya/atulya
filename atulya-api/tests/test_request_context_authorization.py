from atulya_api.models import RequestContext


def test_internal_context_keeps_explicit_schema_for_authorized_jobs():
    context = RequestContext(internal=True, schema_name="org_acme", role="superuser")

    assert context.schema_name == "org_acme"
    assert context.internal is True


def test_system_internal_context_is_explicitly_privileged():
    from atulya_api.auth import can_perform

    context = RequestContext.system_internal(schema_name="org_acme")

    assert context.role == "superuser"
    assert context.schema_name == "org_acme"
    assert context.action_scopes == {"system.admin": ["system:*"]}
    assert can_perform(context, "bank.write", "bank-a") is True


def test_task_authorization_envelope_does_not_include_raw_credentials():
    context = RequestContext(
        api_key="atulya_sess_secret",
        schema_name="org_acme",
        principal_id="principal",
        allowed_actions=["bank.write"],
        action_scopes={"bank.write": ["bank:one"]},
    )

    envelope = context.to_task_authorization()

    assert "api_key" not in envelope
    assert envelope["schema_name"] == "org_acme"
    assert envelope["action_scopes"] == {"bank.write": ["bank:one"]}
