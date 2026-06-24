"""Taste Studio errors."""

from __future__ import annotations

from typing import Any


class TasteError(Exception):
    def __init__(self, message: str, *, code: str = "taste_error", details: dict[str, Any] | None = None) -> None:
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(message)


class TasteValidationError(TasteError):
    def __init__(self, message: str, *, field: str | None = None, details: dict[str, Any] | None = None) -> None:
        merged = dict(details or {})
        if field:
            merged["field"] = field
        super().__init__(message, code="taste_validation_error", details=merged)
        self.field = field


class TasteNotFoundError(TasteError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="taste_not_found", details=details)
