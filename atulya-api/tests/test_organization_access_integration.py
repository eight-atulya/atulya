import uuid

import asyncpg
import httpx
import pytest
from fastapi import FastAPI

from atulya_api.api.organizations import create_organization_router
from atulya_api.auth import fq
from atulya_api.auth_service import issue_session, seed_builtin_roles


class MemoryStub:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def _get_pool(self) -> asyncpg.Pool:
        return self.pool


@pytest.mark.asyncio
async def test_last_owner_and_cross_org_are_enforced_before_resource_access(pg0_db_url):
    pool = await asyncpg.create_pool(pg0_db_url, min_size=1, max_size=3)
    owner_id = uuid.uuid4()
    first_org = uuid.uuid4()
    second_org = uuid.uuid4()
    try:
        await pool.execute(
            f"""
            INSERT INTO {fq("principals")}
                (id, email, display_name, principal_type, status, email_verified_at)
            VALUES ($1, $2, 'Integration owner', 'user', 'active', NOW())
            """,
            owner_id,
            f"owner-{owner_id.hex}@example.com",
        )
        for org_id, suffix in ((first_org, "first"), (second_org, "second")):
            await pool.execute(
                f"""
                INSERT INTO {fq("orgs")} (id, slug, name, schema_name, status)
                VALUES ($1, $2, $3, $4, 'active')
                """,
                org_id,
                f"{suffix}-{org_id.hex[:10]}",
                suffix.title(),
                f"org_{suffix}_{org_id.hex[:10]}",
            )
            await seed_builtin_roles(pool, str(org_id))

        owner_role = await pool.fetchval(
            f"SELECT id FROM {fq('roles')} WHERE org_id = $1 AND name = 'owner'",
            first_org,
        )
        admin_role = await pool.fetchval(
            f"SELECT id FROM {fq('roles')} WHERE org_id = $1 AND name = 'admin'",
            first_org,
        )
        membership_id = await pool.fetchval(
            f"""
            INSERT INTO {fq("org_memberships")} (org_id, principal_id, role_id, status)
            VALUES ($1, $2, $3, 'active') RETURNING id
            """,
            first_org,
            owner_id,
            owner_role,
        )
        await pool.execute(
            f"INSERT INTO {fq('membership_scopes')} (membership_id, scope_type, scope_id) VALUES ($1, 'org', '*')",
            membership_id,
        )
        token, _ = await issue_session(pool, str(owner_id), active_org_id=str(first_org))

        app = FastAPI()
        app.include_router(create_organization_router(MemoryStub(pool)), prefix="/v1/orgs")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            demote = await client.patch(
                f"/v1/orgs/{first_org}/members/{membership_id}",
                json={"role_id": str(admin_role)},
            )
            assert demote.status_code == 409
            assert demote.json()["detail"]["code"] == "last_owner_protected"

            cross_org = await client.get(f"/v1/orgs/{second_org}/members")
            assert cross_org.status_code == 403
            assert cross_org.json()["detail"]["code"] == "permission_denied"

        denied = await pool.fetchval(
            f"""
            SELECT COUNT(*) FROM {fq("audit_events")}
            WHERE actor_principal_id = $1 AND action = 'access.denied' AND result = 'denied'
            """,
            owner_id,
        )
        assert denied == 1
    finally:
        await pool.execute(f"DELETE FROM {fq('orgs')} WHERE id = ANY($1::uuid[])", [first_org, second_org])
        await pool.execute(f"DELETE FROM {fq('principals')} WHERE id = $1", owner_id)
        await pool.close()
