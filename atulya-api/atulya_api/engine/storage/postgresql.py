"""
PostgreSQL BYTEA file storage (zero-config default).

Purpose:
    Store uploaded files inline in the ``file_storage`` table for single-node and
    dev deployments without object-store credentials.

Trigger path:
    Default when ``ATULYA_API_FILE_STORAGE=postgresql`` or unset; constructed in
    ``MemoryEngine`` with ``pool_getter`` and tenant ``schema_getter``.

Inputs:
    - ``pool_getter``: returns shared ``asyncpg.Pool``.
    - ``schema`` / ``schema_getter``: multi-tenant table qualification.

Outputs / side effects:
    - INSERT ... ON CONFLICT UPDATE on ``file_storage(storage_key, data)``.
    - ``get_download_url`` returns a relative API path (auth at HTTP layer).

Mutability:
    ``store`` overwrites existing keys (upsert).

Impact radius:
    Large files bloat PostgreSQL backups and replication; repo clone/copy may
    duplicate BYTEA rows when storage keys are remapped.

Performance:
    Suitable for small/medium files (<~10MB); high volume or large blobs should
    use ``S3FileStorage``.

Maintenance notes:
    Good: keep keys stable and referenced from DB columns only.
    Bad: store multi-GB archives here in production — use object storage instead.
"""

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

from .base import FileStorage

logger = logging.getLogger(__name__)


def fq_table(table: str, schema: str | None = None) -> str:
    """Get fully-qualified table name with optional schema prefix."""
    if schema:
        return f'"{schema}".{table}'
    return table


class PostgreSQLFileStorage(FileStorage):
    """
    BYTEA-backed ``FileStorage`` using the shared API database pool.

    Purpose:
        Transactionally co-locate file bytes with bank metadata for embedded pg0
        and simple deployments.

    Side effects:
        Acquires pool connections per operation; one round-trip per method.

    Failure modes:
        ``FileNotFoundError`` when ``retrieve`` finds no row.

    Maintenance notes:
        ``schema_getter`` must match the tenant context of the calling request.
    """

    def __init__(
        self,
        pool_getter: Callable[[], "asyncpg.Pool"],
        schema: str | None = None,
        schema_getter: Callable[[], str] | None = None,
    ):
        """
        Initialize PostgreSQL file storage.

        Args:
            pool_getter: Function that returns asyncpg connection pool
            schema: Static database schema (fallback for single-tenant / tests)
            schema_getter: Callable returning current schema at query time (for multi-tenant)
        """
        self._pool_getter = pool_getter
        self._static_schema = schema
        self._schema_getter = schema_getter

    @property
    def _schema(self) -> str | None:
        """Resolve schema dynamically per-request when schema_getter is provided."""
        if self._schema_getter:
            return self._schema_getter()
        return self._static_schema

    async def store(
        self,
        file_data: bytes,
        key: str,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Store file in PostgreSQL."""
        pool = self._pool_getter()

        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {fq_table("file_storage", self._schema)}
                (storage_key, data)
                VALUES ($1, $2)
                ON CONFLICT (storage_key) DO UPDATE SET
                    data = EXCLUDED.data
                """,
                key,
                file_data,
            )

        logger.debug(f"Stored file {key} ({len(file_data)} bytes) in PostgreSQL")
        return key

    async def retrieve(self, key: str) -> bytes:
        """Retrieve file from PostgreSQL."""
        pool = self._pool_getter()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT data FROM {fq_table("file_storage", self._schema)}
                WHERE storage_key = $1
                """,
                key,
            )

            if not row:
                raise FileNotFoundError(f"File not found: {key}")

            return bytes(row["data"])

    async def delete(self, key: str) -> None:
        """Delete file from PostgreSQL."""
        pool = self._pool_getter()

        async with pool.acquire() as conn:
            result = await conn.execute(
                f"""
                DELETE FROM {fq_table("file_storage", self._schema)}
                WHERE storage_key = $1
                """,
                key,
            )

            # Check if anything was deleted
            if result == "DELETE 0":
                logger.warning(f"Attempted to delete non-existent file: {key}")

    async def exists(self, key: str) -> bool:
        """Check if file exists in PostgreSQL."""
        pool = self._pool_getter()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT 1 FROM {fq_table("file_storage", self._schema)}
                WHERE storage_key = $1
                """,
                key,
            )

            return row is not None

    async def get_download_url(self, key: str, expires_in: int = 3600) -> str:
        """
        Get download URL for PostgreSQL-stored file.

        Returns an API endpoint path (not a pre-signed URL since the file
        is stored in the database). The expires_in parameter is ignored
        for PostgreSQL storage.
        """
        # Return API path for download endpoint
        # (expires_in ignored for database storage - auth handled at API level)
        return f"/v1/default/files/download/{key}"
