"""
File storage abstraction for retain uploads and codebase archives.

Purpose:
    Uniform async interface for storing binary artifacts referenced by
    ``file_storage_key`` / ``source_archive_storage_key`` columns across banks,
    documents, and codebase snapshots.

Trigger path:
    - ``MemoryEngine`` selects an implementation from ``ATULYA_API_FILE_STORAGE``
      (PostgreSQL default, or S3/GCS/Azure) at init.
    - Retain file upload, document download, memory repo restore/copy paths call
      ``store`` / ``retrieve`` / ``delete`` / ``get_download_url``.

Inputs:
    - ``key``: logical path (e.g. ``banks/{bank_id}/files/{id}.pdf``).
    - ``file_data``: raw bytes on write.
    - Optional ``metadata`` (backend-specific; not all implementations persist it).

Outputs:
    - ``store`` returns the storage key (usually echo of input key).
    - ``retrieve`` returns bytes; ``get_download_url`` returns API path or presigned URL.

Side effects:
    - External object store or PostgreSQL ``file_storage`` BYTEA rows.

Mutability:
    - Keys are overwrite-on-conflict in PostgreSQL backend; object stores follow
      put semantics.

Impact radius:
    - Memory repo restore must remap storage keys when copying across banks.
    - Deleting banks/documents without deleting orphaned blobs leaks storage.

Failure modes:
    - ``FileNotFoundError`` on missing keys (callers must handle).
    - Backend-specific network/auth errors propagate from cloud providers.

Maintenance notes:
    Good: add a backend by subclassing ``FileStorage`` and wiring factory in engine.
    Bad: bypass this interface and write BYTEA directly — breaks S3 deployments.
"""

from abc import ABC, abstractmethod


class FileStorage(ABC):
    """
    Async contract for durable binary artifact storage.

    Purpose:
        Isolate retain/repo/codebase flows from the concrete storage medium.

    Trigger path:
        Resolved once per ``MemoryEngine`` and passed into retain and repo services.

    Maintenance notes:
        All methods are bank-scoped only by key convention — enforcement is caller-side.
    """

    @abstractmethod
    async def store(
        self,
        file_data: bytes,
        key: str,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """
        Store file and return storage key.

        Args:
            file_data: Raw file bytes
            key: Storage key (e.g., "banks/{bank_id}/files/{file_id}.pdf")
            metadata: Optional metadata to store with file

        Returns:
            Storage key that can be used to retrieve the file
        """
        pass

    @abstractmethod
    async def retrieve(self, key: str) -> bytes:
        """
        Retrieve file by storage key.

        Args:
            key: Storage key

        Returns:
            File data as bytes

        Raises:
            FileNotFoundError: If file does not exist
        """
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        """
        Delete file by storage key.

        Args:
            key: Storage key
        """
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """
        Check if file exists.

        Args:
            key: Storage key

        Returns:
            True if file exists, False otherwise
        """
        pass

    @abstractmethod
    async def get_download_url(self, key: str, expires_in: int = 3600) -> str:
        """
        Get a URL for downloading the file.

        For PostgreSQL storage, this might be a relative API path.
        For S3, this would be a pre-signed URL.

        Args:
            key: Storage key
            expires_in: Expiration time in seconds (may be ignored for some backends)

        Returns:
            Download URL or path
        """
        pass
