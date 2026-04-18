"""Deterministic file role classifier.

Maps a normalized file path (POSIX, archive-relative) to a FileRole using
multi-language path/name rules. Pure function, no I/O, fully testable.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import PurePosixPath


class FileRole(str, Enum):
    """Coarse classification of what a file is for in a codebase.

    Used by the significance scorer and auto-route policy.
    """

    ENTRYPOINT = "entrypoint"
    API_ROUTE = "api_route"
    CONFIG = "config"
    SCHEMA_MODEL = "schema_model"
    MIGRATION = "migration"
    PUBLIC_LIB = "public_lib"
    SHARED_UTIL = "shared_util"
    TEST = "test"
    FIXTURE = "fixture"
    DOCS = "docs"
    GENERATED = "generated"
    VENDORED = "vendored"
    BOILERPLATE = "boilerplate"
    UNKNOWN = "unknown"


_VENDORED_PARTS = {
    "node_modules",
    "vendor",
    "third_party",
    "third-party",
    ".venv",
    "venv",
    "site-packages",
    ".tox",
    ".eggs",
    "bower_components",
    "jspm_packages",
}

_GENERATED_PARTS = {
    "generated",
    "__generated__",
    "build",
    "dist",
    ".next",
    ".nuxt",
    ".turbo",
    ".svelte-kit",
    "out",
    "target",
    "coverage",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

_DOCS_PARTS = {"docs", "doc", "documentation"}
_FIXTURE_PARTS = {"fixtures", "__fixtures__", "testdata", "test-data"}
_TEST_PARTS = {"tests", "test", "__tests__", "spec", "specs"}

_ENTRYPOINT_NAMES = {
    "main.py",
    "__main__.py",
    "app.py",
    "server.py",
    "cli.py",
    "manage.py",
    "run.py",
    "wsgi.py",
    "asgi.py",
    "index.ts",
    "index.tsx",
    "index.js",
    "index.jsx",
    "index.mjs",
    "main.ts",
    "main.tsx",
    "main.js",
    "main.go",
    "main.rs",
    "program.cs",
}

_BOILERPLATE_NAMES = {
    "license",
    "licence",
    "license.md",
    "license.txt",
    "notice",
    "notice.md",
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
    ".prettierrc",
    ".eslintrc",
    ".eslintrc.json",
    ".eslintrc.js",
    ".dockerignore",
    ".npmignore",
    "code_of_conduct.md",
    "contributing.md",
    "security.md",
    "changelog.md",
    "authors",
    "authors.md",
    ".gitkeep",
    "py.typed",
}

_CONFIG_NAMES = {
    "settings.py",
    "config.py",
    "configuration.py",
    "conf.py",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "requirements-dev.txt",
    "pipfile",
    "pipfile.lock",
    "poetry.lock",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "tsconfig.json",
    "jsconfig.json",
    "vite.config.ts",
    "vite.config.js",
    "next.config.js",
    "next.config.ts",
    "next.config.mjs",
    "tailwind.config.js",
    "tailwind.config.ts",
    "webpack.config.js",
    "rollup.config.js",
    "esbuild.config.js",
    "babel.config.js",
    ".babelrc",
    "go.mod",
    "go.sum",
    "cargo.toml",
    "cargo.lock",
    "composer.json",
    "composer.lock",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "makefile",
}

_DOCS_EXTS = {".md", ".mdx", ".rst", ".txt", ".adoc"}

_GENERATED_NAME_RE = re.compile(
    r".*("
    r"\.min\."
    r"|\.bundle\."
    r"|\.generated\."
    r"|\.gen\."
    r"|_pb2\."
    r"|_pb\."
    r"|\.pb\."
    r"|\.tsbuildinfo$"
    r")",
    re.IGNORECASE,
)

_API_ROUTE_PARTS = {
    "api",
    "apis",
    "routes",
    "router",
    "routers",
    "controllers",
    "controller",
    "handlers",
    "endpoints",
    "views",
    "resolvers",
}

_API_ROUTE_NAME_RE = re.compile(
    r"(routes?|router|controller|handler|endpoint|view|resolver|api)\.[a-z]+$",
    re.IGNORECASE,
)

_SCHEMA_MODEL_NAME_RE = re.compile(
    r"(models?|schemas?|types?|entities|entity|dto|interfaces?)\.[a-z]+$",
    re.IGNORECASE,
)

_SCHEMA_MODEL_PARTS = {
    "models",
    "schemas",
    "types",
    "entities",
    "dto",
    "dtos",
    "interfaces",
}

_SHARED_UTIL_PARTS = {"utils", "util", "helpers", "helper", "common", "shared", "lib"}

_TEST_FILE_RE = re.compile(
    r"^(test_.*|.*_test\.[a-z]+|.*\.test\.[a-z]+|.*\.spec\.[a-z]+)$",
    re.IGNORECASE,
)


def classify_file_role(path: str) -> FileRole:
    """Classify a normalized POSIX path into a FileRole.

    Path is expected to be archive-relative (no leading slash).
    Order matters: vendored/generated/boilerplate take precedence so that
    obviously-noise paths cannot accidentally be tagged as something
    interesting via a deeper rule.
    """

    if not path:
        return FileRole.UNKNOWN

    pure = PurePosixPath(path)
    parts_lower = [part.lower() for part in pure.parts]
    parts_set = set(parts_lower)
    name_lower = pure.name.lower()
    suffix_lower = pure.suffix.lower()

    if parts_set & _VENDORED_PARTS:
        return FileRole.VENDORED
    if parts_set & _GENERATED_PARTS:
        return FileRole.GENERATED
    if _GENERATED_NAME_RE.match(name_lower):
        return FileRole.GENERATED

    if name_lower in _BOILERPLATE_NAMES:
        return FileRole.BOILERPLATE

    if "alembic" in parts_lower and "versions" in parts_lower:
        return FileRole.MIGRATION
    if "migrations" in parts_lower:
        return FileRole.MIGRATION

    if parts_set & _FIXTURE_PARTS:
        return FileRole.FIXTURE
    if parts_set & _TEST_PARTS:
        return FileRole.TEST
    if _TEST_FILE_RE.match(name_lower):
        return FileRole.TEST

    if parts_set & _DOCS_PARTS:
        return FileRole.DOCS
    if suffix_lower in _DOCS_EXTS:
        return FileRole.DOCS

    if name_lower in _CONFIG_NAMES:
        return FileRole.CONFIG
    if suffix_lower in {".toml", ".yaml", ".yml", ".ini", ".cfg", ".env"}:
        return FileRole.CONFIG

    if name_lower in _ENTRYPOINT_NAMES:
        return FileRole.ENTRYPOINT

    if parts_set & _API_ROUTE_PARTS:
        return FileRole.API_ROUTE
    if _API_ROUTE_NAME_RE.search(name_lower):
        return FileRole.API_ROUTE

    if parts_set & _SCHEMA_MODEL_PARTS:
        return FileRole.SCHEMA_MODEL
    if _SCHEMA_MODEL_NAME_RE.search(name_lower):
        return FileRole.SCHEMA_MODEL

    if parts_set & _SHARED_UTIL_PARTS:
        return FileRole.SHARED_UTIL

    if len(pure.parts) <= 2 and suffix_lower in {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java"}:
        return FileRole.PUBLIC_LIB

    return FileRole.UNKNOWN


def is_dismiss_role(role: FileRole) -> bool:
    """Roles that should generally be auto-dismissed unless overridden."""

    return role in {FileRole.GENERATED, FileRole.VENDORED, FileRole.BOILERPLATE}


def is_high_value_role(role: FileRole) -> bool:
    """Roles that earn an auto-memory promotion when paired with a
    symbol-kind chunk above the high-significance threshold."""

    return role in {
        FileRole.ENTRYPOINT,
        FileRole.API_ROUTE,
        FileRole.CONFIG,
        FileRole.SCHEMA_MODEL,
        FileRole.MIGRATION,
        FileRole.PUBLIC_LIB,
    }


def role_weight(role: FileRole) -> float:
    """Per-role weight for the significance score (0..1)."""

    weights = {
        FileRole.ENTRYPOINT: 0.95,
        FileRole.API_ROUTE: 0.9,
        FileRole.CONFIG: 0.7,
        FileRole.SCHEMA_MODEL: 0.85,
        FileRole.MIGRATION: 0.55,
        FileRole.PUBLIC_LIB: 0.7,
        FileRole.SHARED_UTIL: 0.5,
        FileRole.DOCS: 0.35,
        FileRole.TEST: 0.2,
        FileRole.FIXTURE: 0.05,
        FileRole.GENERATED: 0.0,
        FileRole.VENDORED: 0.0,
        FileRole.BOILERPLATE: 0.05,
        FileRole.UNKNOWN: 0.4,
    }
    return weights.get(role, 0.4)
