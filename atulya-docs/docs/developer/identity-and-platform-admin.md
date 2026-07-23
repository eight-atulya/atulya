---
sidebar_label: Identity and Platform Admin
sidebar_position: 5
---

# Identity and Platform Admin

This page answers the first setup question: **how does a person reach the platform admin page?**

The short answer is:

1. Configure the API and control plane.
2. Create a platform admin in the database with `atulya-admin`.
3. Sign in at `/login`.
4. Open `/admin/platform`.

There is no `PLATFORM_ADMIN=true` user setting. Platform access is a database permission attached to a human account.

## Who Can Open Which Page?

| Person | Sign-in method | Access |
| --- | --- | --- |
| Platform operator | Email/password session | Deployment health, organizations, workers, and operations under `/admin/platform/*` |
| Organization owner or admin | Email/password session | Their organization, members, service accounts, roles, grants, audit, and allowed banks |
| Bank operator or viewer | Email/password session | Only the memory banks assigned to them |
| Service or agent | API key | Only the actions and banks assigned to its service account |

The UI hides links that the current person cannot use. The API checks the same permission again, so a hidden link is not the security boundary.

## The Three Configuration Groups

### 1. API environment

Put these values in the repository root `.env` or in your deployment secret manager:

| Variable | Set by | Purpose |
| --- | --- | --- |
| `ATULYA_API_DATABASE_URL` | Developer or operator | Database used by the API and CLI |
| `ATULYA_API_AUTH_MODE=database` | Generated block | Turns on the canonical database auth system |
| `ATULYA_API_ADMIN_ENABLED=true` | Generated block | Mounts platform and legacy admin routes |
| `ATULYA_API_KEY_HASH_PEPPER` | Generated once | Protects stored API-key hashes |
| `ATULYA_API_SESSION_HASH_PEPPER` | Generated once | Protects stored session hashes |
| `ATULYA_API_SUPERUSER_KEY` | Generated once | Offline emergency recovery only; never put in the UI |
| `ATULYA_API_AUTH_SCHEMA=public` | Generated block | Platform schema containing identity and access tables |
| `ATULYA_SIGNUP_MODE` | Operator choice | `public`, `bootstrap`, or `disabled` |
| Email settings | Operator | Verification and password-recovery delivery |

The two peppers are different and must remain stable. Changing one invalidates the credentials it protects. Store them like database passwords, not in source control.

The generated block does **not** replace application settings such as `ATULYA_API_DATABASE_URL` or your LLM provider keys. Those remain deployment-specific.

### 2. Control plane environment

Put these values in the root `.env` when using `scripts/dev/start.sh`, or in `atulya-control-plane/.env.local` when starting Next.js directly:

```env
ATULYA_CP_DATAPLANE_API_URL=http://localhost:8888
ATULYA_CP_PUBLIC_URL=http://localhost:9999
ATULYA_CP_COOKIE_SECURE=false
ATULYA_CP_ALLOW_DATAPLANE_API_KEY_FALLBACK=false
```

For HTTPS production, use the public HTTPS URLs and set `ATULYA_CP_COOKIE_SECURE=true`.

The control plane stores only the user's opaque session in an HTTP-only cookie. It does not receive or use the emergency platform key.

### 3. Database identity

The first platform operator is created by a CLI command. The command creates:

- a verified human identity;
- an Argon2 password hash;
- a `system.admin` permission with `system:*` scope;
- an audit event.

No password or platform permission is stored in an environment variable.

## Generate the Values

Run this once for a new environment:

```bash
cd atulya-api
uv run atulya-admin generate-auth-env --environment development
```

For production:

```bash
uv run atulya-admin generate-auth-env \
  --environment production \
  --dataplane-url https://api.example.com \
  --api-port 8888 \
  --control-plane-port 9999
```

The command generates random values for:

```text
ATULYA_API_SUPERUSER_KEY
ATULYA_API_KEY_HASH_PEPPER
ATULYA_API_SESSION_HASH_PEPPER
```

It also prints the auth mode, email mode, cookie setting, ports, and control-plane API URL. Copy the output into the secret manager or environment files for that deployment. Generate these values once per environment, then reuse the same values on every API replica.

Before using the CLI, set the database URL in the same environment:

```env
ATULYA_API_DATABASE_URL=postgresql://user:password@host:5432/atulya
```

Never commit `.env`, generated secrets, SMTP passwords, or database URLs.

## Create the First Platform Operator

Apply the auth migration, then create the person who will operate the deployment:

```bash
cd atulya-api
uv run atulya-admin run-db-migration
uv run atulya-admin create-platform-admin
```

The CLI prompts for the email, name, and password. The password is hidden and must be at least 12 characters. It is never accepted as a command-line argument.

Useful checks:

```bash
uv run atulya-admin list-platform-admins
uv run atulya-admin revoke-platform-admin --email operator@example.com
```

Revocation removes the platform permission and ends the person's active sessions. To restore access, create or grant it through the controlled operator workflow.

## Start and Sign In

With the root `.env` configured:

```bash
./scripts/dev/start.sh
```

Open:

```text
http://localhost:9999/login
```

Sign in with the platform operator email and password. Then open:

```text
http://localhost:9999/admin/platform
```

The page is allowed only when the same signed-in identity has both:

```text
action: system.admin
scope:  system:*
```

`ATULYA_API_ADMIN_ENABLED=true` makes the API routes available. It does not give a person access. The database permission gives the person access.

## Request Flow

The browser never sends the emergency key. The request path is:

```text
Browser login
    -> control-plane login route
    -> API POST /v1/auth/login
    -> API verifies password and creates a session
    -> control plane sets HTTP-only atulya_session cookie

Browser GET /admin/platform
    -> control plane reads the cookie on the server
    -> API GET /v1/auth/me resolves identity and permissions
    -> UI shows platform navigation only for system.admin/system:*

Platform action
    -> control plane forwards Authorization: Bearer <session>
    -> API resolves the session again
    -> API checks system.admin and system:*
    -> API runs the action and writes the real actor to the audit log
```

The important property is that the API makes the final decision. A person cannot gain access by typing a hidden URL or changing a browser request.

## Permission Check

The backend follows one small decision path:

```text
if session is missing or expired:
    return 401

if action == system.admin and scope == system:*:
    allow platform operation

if active organization membership and matching action and bank scope:
    allow organization operation

otherwise:
    write denied audit event
    return 403
```

Organization administrators do not need platform access to manage their own memory banks. Platform pages are for deployment operations. Organization pages are for members, service accounts, roles, grants, audit, and bank-level work inside that organization.

## Production Checklist

- Set `ATULYA_ENVIRONMENT=production` and `ATULYA_API_AUTH_MODE=database`.
- Use a managed secret store for the database URL, both peppers, the emergency key, SMTP password, and provider keys.
- Set `ATULYA_AUTH_EMAIL_TRANSPORT=smtp` and complete every SMTP variable before API startup.
- Set `ATULYA_AUTH_PUBLIC_URL`, `ATULYA_CP_PUBLIC_URL`, and `ATULYA_CP_DATAPLANE_API_URL` to the real HTTPS URLs.
- Set `ATULYA_CP_COOKIE_SECURE=true`.
- Keep `ATULYA_CP_ALLOW_DATAPLANE_API_KEY_FALLBACK=false`.
- Create platform operators with the CLI, not by editing SQL or environment variables.
- Run migrations before starting API replicas.
- Keep `ATULYA_API_SUPERUSER_KEY` out of browser, Next.js, and client-side variables.
- Confirm `/v1/auth/me`, `/admin/platform`, logout, audit events, and a denied organization request before opening external traffic.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Platform page says access denied | Run `list-platform-admins`, confirm the signed-in email, then sign out and sign in again. |
| Platform routes return not found | Set `ATULYA_API_ADMIN_ENABLED=true` and restart the API. |
| Browser says `API key is required` after login | Confirm the control plane points to the API, the session cookie is enabled, and `ATULYA_CP_ALLOW_DATAPLANE_API_KEY_FALLBACK=false`; restart both services after env changes. |
| Cookie is not kept locally | Use `ATULYA_CP_COOKIE_SECURE=false` for local HTTP. Use `true` only behind HTTPS. |
| Production API refuses to start | Complete SMTP settings when verification is required, and set both stable auth peppers. |
| A service key cannot access a bank | Attach the key to a service principal and grant that principal the action and matching bank scope. A key does not carry permissions by itself. |

For endpoint details, see [Admin and Access Control](./admin-api). For command options, see [Admin CLI](./admin-cli).
