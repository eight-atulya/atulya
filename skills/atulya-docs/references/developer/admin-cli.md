# Admin CLI

The `atulya-admin` CLI provides administrative commands for managing your Atulya deployment, including database migrations, backup, and restore operations.

## Installation

The admin CLI is included with the `atulya-api` package:

```bash
pip install atulya-api
# or
uv add atulya-api
```

## Commands

### run-db-migration

Run database migrations to the latest version. This is useful when you want to run migrations separately from API startup (e.g., in CI/CD pipelines or before deploying a new version).

```bash
atulya-admin run-db-migration [OPTIONS]
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--schema`, `-s` | Database schema to run migrations on | `public` |

**Examples:**

```bash
# Run migrations on the default public schema
atulya-admin run-db-migration

# Run migrations on a specific tenant schema
atulya-admin run-db-migration --schema tenant_acme
```

:::tip Disabling Auto-Migrations
To disable automatic migrations on API startup, set `ATULYA_API_RUN_MIGRATIONS_ON_STARTUP=false`. This is useful when you want to run migrations as a separate step in your deployment pipeline.
:::

---

### backup

Create a backup of all Atulya data to a zip file.

```bash
atulya-admin backup OUTPUT [OPTIONS]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `OUTPUT` | Output file path (will add `.zip` extension if not present) |

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--schema`, `-s` | Database schema to backup | `public` |

**Examples:**

```bash
# Backup to a file
atulya-admin backup /backups/atulya-2024-01-15.zip

# Backup a specific tenant schema
atulya-admin backup /backups/tenant-acme.zip --schema tenant_acme
```

The backup includes:
- Memory banks and their configuration
- Documents and chunks
- Entities and their relationships
- Memory units (facts, experiences, observations)
- Entity cooccurrences and memory links

:::note Consistency
Backups are created within a database transaction with `REPEATABLE READ` isolation, ensuring a consistent snapshot across all tables.
:::

---

### restore

Restore data from a backup file. **Warning: This deletes all existing data in the target schema.**

```bash
atulya-admin restore INPUT [OPTIONS]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `INPUT` | Input backup file (.zip) |

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--schema`, `-s` | Database schema to restore to | `public` |
| `--yes`, `-y` | Skip confirmation prompt | `false` |

**Examples:**

```bash
# Restore with confirmation prompt
atulya-admin restore /backups/atulya-2024-01-15.zip

# Restore without confirmation (for scripts)
atulya-admin restore /backups/atulya-2024-01-15.zip --yes

# Restore to a specific tenant schema
atulya-admin restore /backups/tenant-acme.zip --schema tenant_acme --yes
```

:::warning Data Loss
Restore will **delete all existing data** in the target schema before importing the backup. Always verify you have a recent backup before performing a restore.
:::

---

### decommission-worker

Release all tasks owned by a worker, resetting them from "processing" back to "pending" status so they can be picked up by other workers.

```bash
atulya-admin decommission-worker WORKER_ID [OPTIONS]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `WORKER_ID` | ID of the worker to decommission |

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--schema`, `-s` | Database schema | `public` |

**Examples:**

```bash
# Before scaling down - release tasks from workers being removed
atulya-admin decommission-worker atulya-worker-4
atulya-admin decommission-worker atulya-worker-3

# Release tasks from a crashed worker
atulya-admin decommission-worker worker-2

# For a specific tenant schema
atulya-admin decommission-worker worker-1 --schema tenant_acme
```

**When to Use:**

- **Scaling down**: Before removing worker replicas in Kubernetes
- **Graceful removal**: When taking a worker offline for maintenance
- **Crash recovery**: If a worker crashed while processing tasks
- **Stuck worker**: When a worker is unresponsive

:::tip Finding Worker IDs
Worker IDs default to the hostname. In Kubernetes StatefulSets, this is the pod name (e.g., `atulya-worker-0`). You can also set a custom ID with `ATULYA_API_WORKER_ID` or `--worker-id`.
:::

---

## Environment Variables

The admin CLI uses the same environment variables as the API service. The most important one is:

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_API_DATABASE_URL` | PostgreSQL connection string | `pg0` (embedded) |

**Example:**

```bash
# Use a specific database
export ATULYA_API_DATABASE_URL=postgresql://user:pass@localhost:5432/atulya
atulya-admin backup /backups/mybackup.zip
```

