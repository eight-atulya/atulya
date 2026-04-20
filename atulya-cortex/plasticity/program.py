"""program.py — a compiled/compilable LLM program.

A `Program` is `(Signature, instructions, demos)`. It renders to an
OpenAI-style messages array, calls a `cortex.language.Language`, and parses
the returned text back into a field-keyed dict.

The prompt is deliberately simple so it works on small local LLMs
(gemma-3-4b on LM Studio, Ollama, etc.):

    <instructions>

    ---
    (demo 1)
    Input:
      <field_a>: ...
      <field_b>: ...
    Output:
      <field_c>: ...

    (demo N)
    ...
    ---
    Now respond.
    Input:
      <field_a>: ...
    Output:
      <field_c>:

The parser is forgiving: it extracts each output field by looking for
"`<name>:`" at the start of a line and reading up to the next field header
or end-of-text. Programs with one output field just take the whole reply.

Naming voice: `program.forward(**inputs)` is the verb. The result is a
dict keyed by the Signature's output names, plus a `_raw` sidechannel with
the full LM utterance for debugging.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from plasticity.signature import Signature


@dataclass(frozen=True)
class Demo:
    """One few-shot example. Values must cover every input and output name."""

    inputs: dict[str, str]
    outputs: dict[str, str]


@dataclass
class Program:
    """A runnable (Signature, instructions, demos) triple."""

    signature: Signature
    instructions: str | None = None
    demos: list[Demo] = field(default_factory=list)
    temperature: float = 0.2
    max_tokens: int = 512

    def render_messages(self, inputs: Mapping[str, str]) -> list[dict[str, Any]]:
        """Render a chat-completions messages array for one call."""

        self.signature.validate_inputs(inputs)
        system_text = (self.instructions or self.signature.instructions).strip()
        user_parts: list[str] = []

        if self.demos:
            user_parts.append("Examples:\n")
            for i, demo in enumerate(self.demos, start=1):
                user_parts.append(f"--- example {i} ---")
                user_parts.append("Input:")
                for f in self.signature.inputs:
                    user_parts.append(f"  {f.name}: {demo.inputs.get(f.name, '')}")
                user_parts.append("Output:")
                for f in self.signature.outputs:
                    user_parts.append(f"  {f.name}: {demo.outputs.get(f.name, '')}")
                user_parts.append("")

        user_parts.append("Now respond.")
        user_parts.append("Input:")
        for f in self.signature.inputs:
            user_parts.append(f"  {f.name}: {inputs.get(f.name, '')}")
        user_parts.append("Output:")
        # Nudge the model to start with the first output field.
        if self.signature.outputs:
            user_parts.append(f"  {self.signature.outputs[0].name}:")

        user = "\n".join(user_parts)
        return [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user},
        ]

    def parse_response(self, text: str) -> dict[str, str]:
        """Pull each output field out of a raw LM reply."""

        names = self.signature.output_names
        if not names:
            return {}
        if len(names) == 1:
            return {names[0]: _strip_field_prefix(text, names[0]).strip()}

        # Multi-field: scan the text for "  <name>:" headers in any order.
        pattern = re.compile(
            r"(?m)^\s*("
            + "|".join(re.escape(n) for n in names)
            + r")\s*:\s*(.*?)(?=^\s*(?:"
            + "|".join(re.escape(n) for n in names)
            + r")\s*:|\Z)",
            re.DOTALL,
        )
        out: dict[str, str] = {}
        for m in pattern.finditer(text):
            key = m.group(1)
            val = m.group(2).strip()
            if key not in out:
                out[key] = val
        for n in names:
            out.setdefault(n, "")
        return out

    async def forward(
        self,
        language: Any,
        inputs: Mapping[str, str],
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Run one LLM call through `language.think` and parse the result."""

        messages = self.render_messages(inputs)
        utterance = await language.think(
            messages,
            provider=provider,
            model=model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        parsed = self.parse_response(utterance.text or "")
        parsed["_raw"] = utterance.text or ""
        return parsed

    def with_instructions(self, instructions: str) -> "Program":
        return Program(
            signature=self.signature,
            instructions=instructions,
            demos=list(self.demos),
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

    def with_demos(self, demos: list[Demo]) -> "Program":
        return Program(
            signature=self.signature,
            instructions=self.instructions,
            demos=list(demos),
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "signature": self.signature.to_dict(),
            "instructions": self.instructions,
            "demos": [{"inputs": d.inputs, "outputs": d.outputs} for d in self.demos],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Program":
        sig = Signature.from_dict(data["signature"])
        demos = [Demo(inputs=dict(d["inputs"]), outputs=dict(d["outputs"])) for d in data.get("demos", [])]
        return cls(
            signature=sig,
            instructions=data.get("instructions"),
            demos=demos,
            temperature=float(data.get("temperature", 0.2)),
            max_tokens=int(data.get("max_tokens", 512)),
        )


def _strip_field_prefix(text: str, name: str) -> str:
    """For single-output programs, tolerate the model starting with '<name>:'."""

    m = re.match(rf"\s*{re.escape(name)}\s*:\s*(.*)$", text, re.DOTALL)
    return m.group(1) if m else text


__all__ = ["Demo", "Program"]
