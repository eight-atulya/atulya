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


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: sanitize-openapi-for-clients.py <input.json> <output.json>", file=sys.stderr)
        return 1

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    spec = json.loads(input_path.read_text())
    sanitized = strip_defaults(spec)
    output_path.write_text(json.dumps(sanitized, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
