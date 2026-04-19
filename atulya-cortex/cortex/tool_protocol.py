"""tool_protocol.py — the inner language of the deliberating cortex.

The cortex *thinks* by talking to a language model. To bridge from that
inner monologue to actual motor behaviour, the model must be able to name
a desire to act ("I want to read this file") and we must be able to read
its words back as that desire. This module defines that contract.

Why XML-shaped tags
-------------------

We target small local models (gemma-4-e2b, llama-3.2-3b, qwen2.5-3b).
Those models are unreliable at emitting OpenAI-style `tool_calls` JSON,
but they are very reliable at copy-pasting tag templates we showed them
in the system prompt. So our wire format is::

    <tool name="bash">{"command": "date"}</tool>

One tag per turn. The body is JSON. Tool name is the registered name on
the `Hand` motor. Anything outside the tag is treated as prose for the
operator (used for "I'll check that — one sec"). When the model wants to
finish the deliberation and reply to the user, it simply omits the tag.

Token discipline
----------------

The cortex deliberation loop replays previous tool calls + results back
to the model, which can blow the context budget on small LLMs. Every
helper here is conservative:

- `render_tool_catalogue` keeps each tool to a single short line.
- `render_tool_result` truncates output bodies past `max_chars` and
  notes how many bytes were dropped.
- `parse_tool_call` returns None on the very first malformed tag instead
  of looping looking for a "good" one — small models that emit
  malformed tags will keep emitting them; better to stop and synthesise
  a final answer than to spin in a parsing loop.

Naming voice: `parse_tool_call`, `render_tool_catalogue`,
`render_tool_result`, `render_protocol_block`. All pure functions; the
deliberation loop in `Cortex._deliberate` orchestrates them.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)

# Match `<tool name="...">...</tool>` non-greedily so the first complete
# tag wins. We accept either single or double quotes around the name to
# survive small-model quoting drift, and tolerate whitespace between
# attributes. Body is captured raw — JSON parsing happens downstream so
# we can give the model a clear error string if it produces malformed JSON.
_TOOL_TAG_RE = re.compile(
    r"<tool\s+name\s*=\s*[\"']([A-Za-z0-9_.-]+)[\"']\s*>(.*?)</tool>",
    re.DOTALL,
)

# Hard caps on the protocol surface to keep small models on rails.
MAX_RESULT_CHARS = 1500
MAX_PROSE_CHARS = 600


@dataclass(frozen=True)
class ToolCall:
    """A parsed `<tool>` invocation from a model utterance.

    `prose_before` and `prose_after` capture any text the model emitted
    around the tag; the deliberation loop usually displays the
    `prose_before` segment to the operator as a "thinking" line so the
    chat doesn't go silent during multi-step reasoning.
    """

    name: str
    arguments: Mapping[str, Any]
    prose_before: str = ""
    prose_after: str = ""

    def to_action_payload(self) -> dict[str, Any]:
        """Render this call as the payload an `Intent(kind="tool_call")` carries.

        Matches the contract the `Hand` motor expects so the same payload
        works whether the deliberation loop dispatches directly or whether
        a future Router-style wrapper relays it through Reply.
        """

        return {"name": self.name, "arguments": dict(self.arguments)}


@dataclass(frozen=True)
class ToolSpec:
    """One tool entry exposed to the model in the system-prompt catalogue.

    `name` and `signature` are mandatory. `description` is optional but
    strongly recommended — small models pick the right tool much more
    often when each line includes a one-clause "use this when..." note.
    `example_args` is rendered next to the signature so the model has a
    canonical JSON template to copy.
    """

    name: str
    signature: str
    description: str = ""
    example_args: Mapping[str, Any] | None = None


def parse_tool_call(text: str) -> ToolCall | None:
    """Extract the first valid `<tool>` invocation from a model utterance.

    Returns None when:
    - no tag is present (the model decided to reply, not to act)
    - a tag is present but the body isn't valid JSON

    Returning None on bad JSON is deliberate. The deliberation loop reads
    `None` as "the model is done acting; treat the text as a reply." That
    means a single malformed tag won't trap us in a retry loop — instead
    we surface the model's prose to the operator, who can then re-ask.
    """

    if not text:
        return None
    match = _TOOL_TAG_RE.search(text)
    if match is None:
        return None
    name = match.group(1).strip()
    body = match.group(2).strip()
    try:
        # Some small models wrap their JSON in ```json fences — strip them.
        body = _strip_code_fences(body)
        args = json.loads(body) if body else {}
    except json.JSONDecodeError as exc:
        logger.debug("tool_protocol: malformed JSON in %s tag: %s; raw=%r", name, exc, body)
        return None
    if not isinstance(args, Mapping):
        # Defensive: a model that emits `[1,2,3]` as the body has lost the
        # plot; we return None and let the loop synthesise a final reply.
        return None

    prose_before = text[: match.start()].strip()
    prose_after = text[match.end() :].strip()
    if len(prose_before) > MAX_PROSE_CHARS:
        prose_before = prose_before[: MAX_PROSE_CHARS - 3] + "..."
    return ToolCall(
        name=name,
        arguments=dict(args),
        prose_before=prose_before,
        prose_after=prose_after,
    )


def _strip_code_fences(s: str) -> str:
    """Trim ```json ... ``` and ``` ... ``` wrappers small models love.

    Idempotent on un-fenced strings; safe on partial fences.
    """

    s = s.strip()
    if s.startswith("```"):
        # Drop the opening fence and any language tag on its line.
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1 :]
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()


def render_protocol_block(tools: Iterable[ToolSpec]) -> str:
    """Build the `## Tools` system-prompt section.

    Returns an empty string when no tools are available, so callers can
    just append it to the system prompt without conditionals. Length is
    bounded by the number of registered tools — keep it under ~12 to
    stay friendly to small models.
    """

    specs = list(tools)
    if not specs:
        return ""
    lines: list[str] = [
        "## Tools",
        "You can act on the world by emitting ONE tag per turn:",
        '  <tool name="TOOL_NAME">{"arg": "value"}</tool>',
        "After your tag, STOP. The system runs the tool and shows you the result",
        "as <tool_result>...</tool_result>. Then you may emit another tool tag",
        "OR write your final reply to the user (no tag).",
        "",
        "Available tools:",
    ]
    for spec in specs:
        lines.append(_render_spec_line(spec))
    lines.extend(
        [
            "",
            "Rules:",
            "1. Emit at most ONE tool tag per turn.",
            "2. Tool body MUST be valid JSON (no comments, no trailing commas).",
            "3. If you have enough information, just answer — do not invent tool calls.",
            "4. Never include tags in your final reply to the user.",
        ]
    )
    return "\n".join(lines)


def _render_spec_line(spec: ToolSpec) -> str:
    line = f"- {spec.name}({spec.signature})"
    if spec.description:
        line += f" — {spec.description}"
    if spec.example_args is not None:
        try:
            example = json.dumps(spec.example_args, ensure_ascii=False)
        except TypeError:
            example = str(spec.example_args)
        line += f'\n    example: <tool name="{spec.name}">{example}</tool>'
    return line


def render_tool_result(
    name: str,
    *,
    ok: bool,
    output: Any,
    detail: str | None = None,
    max_chars: int = MAX_RESULT_CHARS,
) -> str:
    """Render a `Hand` `ActionResult` as a `<tool_result>` block.

    The body is the JSON-serialised output for success, or the failure
    detail for error. Truncation appends a `... [+N bytes]` suffix so the
    model can see it was cut off.
    """

    header = f'<tool_result name="{name}" status="{"ok" if ok else "error"}">'
    footer = "</tool_result>"
    if ok:
        body = _safe_json(output)
    else:
        body = (detail or "tool failed").strip() or "tool failed"
    if len(body) > max_chars:
        dropped = len(body) - max_chars
        body = body[:max_chars] + f"\n... [+{dropped} bytes truncated]"
    return f"{header}\n{body}\n{footer}"


def _safe_json(value: Any) -> str:
    """Try to render `value` as compact JSON; fall back to repr."""

    try:
        return json.dumps(value, ensure_ascii=False, indent=None, sort_keys=False)
    except (TypeError, ValueError):
        return repr(value)


__all__ = [
    "MAX_PROSE_CHARS",
    "MAX_RESULT_CHARS",
    "ToolCall",
    "ToolSpec",
    "parse_tool_call",
    "render_protocol_block",
    "render_tool_result",
]
