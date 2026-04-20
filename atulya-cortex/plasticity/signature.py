"""signature.py — declarative input/output contract for an LLM program.

A `Signature` is a named, typed shape: what inputs a program consumes, what
outputs it emits, and one instruction describing the task in plain English.

We intentionally model this as plain dataclasses rather than a DSPy subclass
so the rest of `plasticity/` can work without `dspy-ai` installed. The
`to_dspy()` adapter on the `Compiler` side is the only place that imports
DSPy.

Example:

    sig = Signature(
        name="summarize",
        instructions="Summarize the passage in one sentence.",
        inputs=[Field("passage", "The text to summarize.")],
        outputs=[Field("summary", "One-sentence summary.")],
    )

The rendered prompt for one call is:

    {instructions}

    ## {input.name}:
    {input.value}

    ## {output.name}:

with a trailing newline so the model completes the final field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class Field:
    """One named field in a Signature. `desc` shows up in the prompt prefix."""

    name: str
    desc: str = ""

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Field.name must be a non-empty string")
        # Field names must be identifiers so they can round-trip through JSON
        # and through dspy.Signature when the optional DSPy backend is used.
        if not self.name.isidentifier():
            raise ValueError(f"Field.name {self.name!r} must be a valid Python identifier")


@dataclass(frozen=True)
class Signature:
    """Declarative contract for an LLM program.

    - `name` is the identifier used for storage/telemetry.
    - `instructions` is the single system/user-prompt preamble.
    - `inputs` and `outputs` are ordered lists of `Field`s.
    """

    name: str
    instructions: str
    inputs: list[Field] = field(default_factory=list)
    outputs: list[Field] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.name.isidentifier():
            raise ValueError(f"Signature.name {self.name!r} must be a valid Python identifier")
        if not self.outputs:
            raise ValueError("Signature requires at least one output field")
        seen: set[str] = set()
        for f in list(self.inputs) + list(self.outputs):
            if f.name in seen:
                raise ValueError(f"duplicate Signature field: {f.name!r}")
            seen.add(f.name)

    @property
    def input_names(self) -> list[str]:
        return [f.name for f in self.inputs]

    @property
    def output_names(self) -> list[str]:
        return [f.name for f in self.outputs]

    def validate_inputs(self, values: Mapping[str, object]) -> None:
        missing = [n for n in self.input_names if n not in values]
        if missing:
            raise ValueError(f"Signature {self.name!r} missing inputs: {missing}")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "instructions": self.instructions,
            "inputs": [{"name": f.name, "desc": f.desc} for f in self.inputs],
            "outputs": [{"name": f.name, "desc": f.desc} for f in self.outputs],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "Signature":
        inputs = [Field(**f) for f in data.get("inputs", [])]  # type: ignore[arg-type]
        outputs = [Field(**f) for f in data.get("outputs", [])]  # type: ignore[arg-type]
        return cls(
            name=str(data["name"]),
            instructions=str(data.get("instructions", "")),
            inputs=inputs,
            outputs=outputs,
        )


__all__ = ["Field", "Signature"]
