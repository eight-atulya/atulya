import uuid

import asyncpg
import pytest

from atulya_api.auth import fq, generate_api_key, hash_secret, hash_session_token, key_prefix
from atulya_api.auth_service import issue_session, resolve_identity, seed_builtin_roles


@pytest.mark.asyncio
async def test_sessions_and_service_keys_resolve_the_same_policy_shape(pg0_db_url):
    connection = await asyncpg.connect(pg0_db_url)
    token = None
    org_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    service_id = uuid.uuid4()
    second_org_id = uuid.uuid4()
    slug = f"auth-test-{org_id.hex[:12]}"
    try:
        async with connection.transaction():
            await connection.execute(
                f"""
                INSERT INTO {fq("orgs")} (id, slug, name, schema_name, status)
                VALUES ($1, $2, 'Auth integration', $3, 'active')
                """,
                org_id,
                slug,
                f"org_{org_id.hex[:12]}",
            )
            await seed_builtin_roles(connection, str(org_id))
            owner_role = await connection.fetchval(
                f"SELECT id FROM {fq('roles')} WHERE org_id = $1 AND name = 'owner'",
                org_id,
            )
            service_role = await connection.fetchval(
                f"SELECT id FROM {fq('roles')} WHERE org_id = $1 AND name = 'service'",
                org_id,
            )
            await connection.execute(
                f"""
                INSERT INTO {fq("principals")}
                    (id, email, display_name, principal_type, status, email_verified_at)
                VALUES ($1, $2, 'Owner', 'user', 'active', NOW()),
                       ($3, NULL, 'Indexer', 'service', 'active', NULL)
                """,
                owner_id,
                f"owner-{org_id.hex}@example.com",
                service_id,
            )
            owner_membership = await connection.fetchval(
                f"""
                INSERT INTO {fq("org_memberships")} (org_id, principal_id, role_id, status)
                VALUES ($1, $2, $3, 'active') RETURNING id
                """,
                org_id,
                owner_id,
                owner_role,
            )
            service_membership = await connection.fetchval(
                f"""
                INSERT INTO {fq("org_memberships")} (org_id, principal_id, role_id, status)
                VALUES ($1, $2, $3, 'active') RETURNING id
                """,
                org_id,
                service_id,
                service_role,
            )
            await connection.execute(
                f"INSERT INTO {fq('membership_scopes')} (membership_id, scope_type, scope_id) VALUES ($1, 'org', '*')",
                owner_membership,
            )
            await connection.execute(
                f"INSERT INTO {fq('membership_scopes')} (membership_id, scope_type, scope_id) VALUES ($1, 'bank', 'bank-a')",
                service_membership,
            )
            await connection.execute(
                f"""
                INSERT INTO {fq("access_grants")}
                    (org_id, subject_type, subject_id, action, scope_type, scope_id)
                VALUES ($1, 'principal', $2, 'memory.recall', 'bank', 'bank-a')
                """,
                org_id,
                str(service_id),
            )

            token, _ = await issue_session(
                connection,
                str(owner_id),
                active_org_id=str(org_id),
            )
            raw_key = generate_api_key()
            await connection.execute(
                f"""
                INSERT INTO {fq("api_keys")}
                    (key_hash, name, principal_id, key_prefix, hash_version)
                VALUES ($1, 'Indexer key', $2, $3, 2)
                """,
                hash_secret(raw_key),
                service_id,
                key_prefix(raw_key),
            )

        human = await resolve_identity(connection, token)
        service = await resolve_identity(connection, raw_key)

        assert human is not None
        assert human.active_org_id == str(org_id)
        assert human.can("bank.delete", org_id=str(org_id), bank_id="any-bank")
        assert service is not None
        assert service.active_org_id == human.active_org_id
        assert service.schema_name == human.schema_name
        assert service.can("memory.recall", org_id=str(org_id), bank_id="bank-a")
        assert not service.can("memory.recall", org_id=str(org_id), bank_id="bank-b")

        # A service key is scoped to one service principal membership. If
        # corrupted or legacy data gives that principal two active memberships,
        # resolution must fail closed instead of selecting an arbitrary org.
        await connection.execute(
            f"""
            INSERT INTO {fq("orgs")} (id, slug, name, schema_name, status)
            VALUES ($1, $2, 'Second org', $3, 'active')
            """,
            second_org_id,
            f"auth-test-second-{second_org_id.hex[:12]}",
            f"org_second_{second_org_id.hex[:12]}",
        )
        await seed_builtin_roles(connection, str(second_org_id))
        second_service_role = await connection.fetchval(
            f"SELECT id FROM {fq('roles')} WHERE org_id = $1 AND name = 'service'",
            second_org_id,
        )
        await connection.execute(
            f"""
            INSERT INTO {fq("org_memberships")} (org_id, principal_id, role_id, status)
            VALUES ($1, $2, $3, 'active')
            """,
            second_org_id,
            service_id,
            second_service_role,
        )
        assert await resolve_identity(connection, raw_key) is None

        await connection.execute(
            f"UPDATE {fq('principal_sessions')} SET revoked_at = NOW() WHERE token_hash = $1",
            hash_session_token(token),
        )
        assert await resolve_identity(connection, token) is None
    finally:
        await connection.execute(f"DELETE FROM {fq('orgs')} WHERE id = ANY($1::uuid[])", [org_id, second_org_id])
        await connection.execute(f"DELETE FROM {fq('principals')} WHERE id = ANY($1::uuid[])", [owner_id, service_id])
        await connection.close()
