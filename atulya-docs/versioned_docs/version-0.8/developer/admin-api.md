# Admin API Reference

> **Security model**: RBAC (role-based) + ABAC (bank allowlist).  
> **Default state**: disabled. Set `ATULYA_API_ADMIN_ENABLED=true` to mount routes.

---

## Setup

### 1. Generate a superuser key

```bash
openssl rand -hex 32
```

### 2. Configure environment

```env
# atulya-api
ATULYA_API_ADMIN_ENABLED=true
ATULYA_API_SUPERUSER_KEY=<generated-key>
ATULYA_API_SUPERUSER_SCHEMA=public   # schema the superuser context uses

# atulya-control-plane (server-side only — never sent to browser)
ATULYA_CP_ADMIN_API_KEY=<same-key>
```

### 3. Apply the api_keys migration

```bash
alembic upgrade 080109b0cbdc
```

---

## Authentication

All `/v1/admin/*` endpoints require the superuser key in one of:

| Method | Header |
|--------|--------|
| Bearer token | `Authorization: Bearer <key>` |
| Direct header | `X-Api-Key: <key>` |

Any key that does not match the superuser key returns **403 Forbidden**.

---

## Endpoints

All endpoints are prefixed `/v1/admin`.

### System

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/system/health` | DB pool stats, migration version, worker count |

### Tenants

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/tenants` | List all tenants with bank counts |
| `GET` | `/tenants/{schema}/banks` | List banks in a schema |

### Workers

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/workers?schema=` | List workers with pending/stuck counts |
| `POST` | `/workers/{worker_id}/decommission` | Release stuck tasks. Use `__all_stuck__` to clear all. |

Body for `decommission`:
```json
{ "release_stuck": true }
```
- `release_stuck=true` (default): reset tasks to `pending` so another worker picks them up.
- `release_stuck=false`: detach worker claim only.

### Operations

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/operations?schema=&status=&limit=` | List async operations. Limit max 500. |

### Bulk Consolidation

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/consolidate/{schema}` | Enqueue consolidation for all banks in schema |

### API Keys

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api-keys` | List all keys (redacted — no raw key) |
| `POST` | `/api-keys` | Create key — returns `raw_key` **once** |
| `DELETE` | `/api-keys/{id}` | Revoke key |
| `PATCH` | `/api-keys/{id}` | Update name or expiry |

Create API key body:
```json
{
  "name": "ci-runner",
  "role": "user",
  "schema_name": "tenant_a",
  "allowed_bank_ids": ["bank-1", "bank-2"],
  "expires_at": "2026-12-31T00:00:00Z"
}
```

Roles: `superuser` > `admin` > `user` (hierarchical — each role has all permissions of lower roles).

---

## Security Notes

| Property | Implementation |
|----------|---------------|
| Timing-safe comparison | `hmac.compare_digest()` on all key checks |
| Key storage | SHA-256 hash stored; raw key never persisted |
| Raw key exposure | Returned once at creation; not retrievable again |
| Route mount | Safe-by-default (`admin_enabled=False`); opt-in per deployment |
| Key rotation | Revoke old key via `DELETE /api-keys/{id}`, create new via `POST /api-keys` |
| ABAC enforcement | `TenantContext.can_access_bank(bank_id)` — superusers bypass allowlists |

---

## Role Reference

| Role | `is_superuser` | Can manage tenants | Bank allowlist enforced |
|------|---------------|-------------------|------------------------|
| `superuser` | ✓ | ✓ | ✗ (bypass) |
| `admin` | ✗ | ✗ | ✓ |
| `user` | ✗ | ✗ | ✓ |

---

## Key Rotation Procedure

1. Create new key: `POST /v1/admin/api-keys` → capture `raw_key`.
2. Update consumers with the new key.
3. Revoke old key: `DELETE /v1/admin/api-keys/{old-id}`.
4. Confirm: `GET /v1/admin/api-keys` shows old key with `revoked_at` set.

---

## Admin UI

Available at `/admin` in the control plane when `ATULYA_CP_ADMIN_API_KEY` is set.

Pages:
- `/admin` — System health
- `/admin/tenants` — Tenant list + bank counts
- `/admin/tenants/{schema}` — Banks in a schema
- `/admin/workers` — Worker status with stuck highlight
- `/admin/operations` — Cross-schema operation log
- `/admin/api-keys` — Key list (read-only; mutations via API)
