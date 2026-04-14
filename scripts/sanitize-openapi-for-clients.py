#!/usr/bin/env python3
"""Prepare an OpenAPI spec for multi-language client generation.

Client generators in Rust and Go can reject or emit invalid code for object
defaults such as `default: {}`. The defaults are useful in docs and the HTTP
schema, but they are not required for generated SDK type safety. This sanitizer
removes all OpenAPI `default` values before SDK generation so release builds use
one stable, language-agnostic client spec.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def strip_defaults(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: strip_defaults(child) for key, child in value.items() if key != "default"}
    if isinstance(value, list):
        return [strip_defaults(item) for item in value]
    return value


def to_pascal_case(value: str) -> str:
    parts = []
    current = []
    for ch in value:
        if ch.isalnum():
            current.append(ch)
        elif current:
            parts.append("".join(current))
            current = []
    if current:
        parts.append("".join(current))
    if not parts:
        return "Generated"
    return "".join(part[:1].upper() + part[1:] for part in parts)


def namespace_nested_titles(spec: dict[str, Any]) -> dict[str, Any]:
    schemas = spec.get("components", {}).get("schemas", {})
    if not isinstance(schemas, dict):
        return spec

    for schema_name, schema in schemas.items():
        if isinstance(schema, dict):
            _namespace_schema_titles(schema, to_pascal_case(schema_name), [])
    return spec


def _namespace_schema_titles(value: Any, root_name: str, path: list[str]) -> None:
    if not isinstance(value, dict):
        return

    if path and "title" in value:
        value["title"] = root_name + "".join(to_pascal_case(segment) for segment in path)

    properties = value.get("properties")
    if isinstance(properties, dict):
        for property_name, property_schema in properties.items():
            _namespace_schema_titles(property_schema, root_name, [*path, property_name])

    for key, label in (("items", "item"), ("additionalProperties", "additional_property")):
        child = value.get(key)
        if isinstance(child, dict):
            _namespace_schema_titles(child, root_name, [*path, label])

    for key in ("allOf", "anyOf", "oneOf"):
        children = value.get(key)
        if isinstance(children, list):
            for index, child in enumerate(children, start=1):
                _namespace_schema_titles(child, root_name, [*path, f"{key}_{index}"])


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: sanitize-openapi-for-clients.py <input.json> <output.json>", file=sys.stderr)
        return 1

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    spec = json.loads(input_path.read_text())
    sanitized = strip_defaults(spec)
    sanitized = namespace_nested_titles(sanitized)
    output_path.write_text(json.dumps(sanitized, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
