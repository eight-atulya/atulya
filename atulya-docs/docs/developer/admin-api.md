# Admin and Access Control

Atulya uses one database-backed identity and authorization model:

- Human users authenticate with email/password and opaque HTTP-only sessions.
- A global user can belong to multiple organizations.
- Organization roles provide action bundles; membership scopes limit those actions to an organization or specific memory banks.
- Services use API keys attached to service principals. Keys do not carry roles or scopes.
- Platform operators use normal sessions with `system.admin` on `system:*`.
- The emergency superuser key is reserved for internal recovery and is never configured in the control plane.

## Initial Setup

Generate independent secrets and the canonical environment block:

```bash
cd atulya-api
uv run atulya-admin generate-auth-env --environment development
```

Put the generated root block in the repository `.env`, then migrate:

```bash
uv run atulya-admin run-db-migration
```

For production, configure SMTP before startup. The API refuses to start when production verification is required and SMTP is incomplete.

Create the first platform operator interactively:

```bash
uv run atulya-admin create-platform-admin
uv run atulya-admin list-platform-admins
```

Passwords are never accepted as command arguments.

## Environment

```env
ATULYA_ENVIRONMENT=production
ATULYA_API_AUTH_MODE=database
ATULYA_API_ADMIN_ENABLED=true
ATULYA_API_AUTH_SCHEMA=public

ATULYA_API_KEY_HASH_PEPPER=<stable-generated-secret>
ATULYA_API_SESSION_HASH_PEPPER=<different-stable-generated-secret>
ATULYA_API_SUPERUSER_KEY=<offline-emergency-secret>

ATULYA_SIGNUP_MODE=public
ATULYA_AUTH_EMAIL_VERIFICATION=required
ATULYA_AUTH_EMAIL_TRANSPORT=smtp
ATULYA_AUTH_PUBLIC_URL=https://control.example.com
ATULYA_AUTH_SMTP_HOST=smtp.example.com
ATULYA_AUTH_SMTP_PORT=587
ATULYA_AUTH_SMTP_USERNAME=<username>
ATULYA_AUTH_SMTP_PASSWORD=<secret>
ATULYA_AUTH_EMAIL_FROM=Atulya <no-reply@example.com>
ATULYA_AUTH_SMTP_STARTTLS=true

ATULYA_CP_DATAPLANE_API_URL=https://api.example.com
ATULYA_CP_PUBLIC_URL=https://control.example.com
ATULYA_CP_COOKIE_SECURE=true
```

The control plane has no platform API key. It forwards the signed-in actor's session, preserving identity in audit events.

## Organization Administration

Canonical routes are under `/v1/orgs/{org_id}` and require explicit organization actions:

| Surface | Required action |
|---|---|
| Members and invitations | `admin.users` |
| Service accounts and keys | `admin.keys` |
| Roles, scopes, direct grants | `admin.grants` |
| Audit events | `admin.audit` |

The first verified workspace creator receives the immutable built-in `owner` role. The final active owner cannot be disabled or demoted. Operators and viewers require explicit bank scopes. Administrators can delegate only actions and scopes they possess.

Service keys are created at:

```text
POST /v1/orgs/{org_id}/service-accounts/{principal_id}/keys
POST /v1/orgs/{org_id}/service-accounts/{principal_id}/keys/{key_id}/rotate
DELETE /v1/orgs/{org_id}/service-accounts/{principal_id}/keys/{key_id}
```

A raw key is returned once. Rotation supports a bounded overlap window.

## Platform Administration

Canonical deployment routes are under `/v1/platform` and require `system.admin` with `system:*`:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/system/health` | Database, migration, and worker health |
| `GET/POST/PATCH` | `/orgs` | Provision, enable, or disable organizations |
| `POST` | `/orgs/{id}/retry-provisioning` | Retry a failed schema migration |
| `GET` | `/tenants/{schema}/banks` | Inspect tenant banks |
| `GET` | `/workers` | Inspect worker claims |
| `POST` | `/workers/{id}/decommission` | Release worker claims |
| `GET` | `/operations` | Filter asynchronous operations |
| `POST` | `/consolidate/{schema}` | Queue consolidation for a schema |

Legacy `/v1/admin/*` paths are deprecated aliases for one release. Legacy key mutation routes return `410 Gone`; keys must be managed through organization service accounts.

## Control Plane

- `/admin`: organization overview
- `/admin/members`: memberships and invitations
- `/admin/service-accounts`: service identities and one-time keys
- `/admin/roles`: built-in and custom action bundles
- `/admin/access`: effective RBAC/ABAC matrix and direct grants
- `/admin/audit`: actor/action/target/result history
- `/admin/platform/*`: platform-only health, organizations, workers, and operations

The Admin entry is capability-based through `/v1/auth/me`. Logout revokes the server session and clears the HTTP-only cookie.

## Production Run

1. Take a full database backup with `pg_dump`. Application-level memory-bank archives are not a substitute for an auth/schema backup.
2. Generate secrets once, store them in a secret manager, and keep both peppers stable.
3. Apply migrations before starting application replicas.
4. Configure SMTP and create the first platform admin through the CLI.
5. Verify signup, email verification, invitation acceptance, workspace switching, service-key rotation, bank isolation, worker recovery, and audit actors.
6. Monitor authentication failures, `401/403` rates, provisioning failures, and key usage.

The development reset command is deliberately destructive and refuses production:

```bash
uv run atulya-admin reset-development-auth-and-banks \
  --confirm RESET-ATULYA-AUTH-AND-BANKS
```

Rollback after that reset requires restoring the database backup.
