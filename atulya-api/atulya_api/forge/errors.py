"""Forge-specific errors with user-facing messages."""

from __future__ import annotations


class ForgeError(Exception):
    """Base error for Data Forge operations."""

    def __init__(self, message: str, *, code: str = "forge_error", details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class ForgeValidationError(ForgeError):
    """Raised when ingest or job configuration is invalid before execution."""

    def __init__(self, message: str, *, field: str | None = None, details: dict | None = None):
        super().__init__(message, code="forge_validation_error", details=details)
        self.field = field


class ForgeExportError(ForgeError):
    """Raised when export cannot produce output."""

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message, code="forge_export_error", details=details)
