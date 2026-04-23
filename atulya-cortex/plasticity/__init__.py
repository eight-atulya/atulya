"""plasticity — the cortex's optimizer / compiler for LLM programs.

Neuroplasticity is the brain's ability to rewire itself through experience.
This package is the atulya-cortex analog: it takes a small declarative LLM
program (`Signature` + instructions + demos), a labeled dataset, and a metric,
and returns an *improved* program by either:

- **Compiling** — sampling good demonstrations from the trainset (DSPy's
  BootstrapFewShot paradigm). When the `dspy-ai` extra is installed we drive
  DSPy's real optimizers; otherwise we fall back to a local bootstrap loop
  that is good enough for small local LLMs.

- **Gradient-ing** — treating the natural-language *instructions* as a
  trainable variable and stepping them via a textual critique → proposal
  loop (TextGrad's paradigm). When `textgrad` is installed we defer to its
  engine; otherwise we run an LLM-critic fallback that is bounded and
  deterministic enough to use on a 4B local model.

Design constraints (match the biomimetic charter):
- Concept-per-file. Nothing in here depends on `dspy` or `textgrad` at
  import time; those are optional runtime upgrades.
- The only LLM surface we know about is `cortex.language.Language`. No
  hard-coded provider names anywhere in this package.
- Compiled programs round-trip through plain JSON so they can live under
  `~/.atulya/cortex/plasticity/` next to the other profile state.

Naming voice: `plasticity.compile`, `plasticity.gradient_step`,
`plasticity.evaluate`. The thing we *produce* is a `Program`; the thing
that produces it is a `Compiler` or a `TextGradient`.
"""

from __future__ import annotations

from plasticity.compiler import BootstrapReport, Compiler
from plasticity.attention_network import (
    AttentionDecision,
    AttentionEntity,
    AttentionWeights,
    hash_binary_with_brain_metadata,
    persist_ip_as_binary,
    ping_local_model,
    request_structured_response,
    route_entities,
    score_entity,
)
from plasticity.engine import (
    LanguageEngine,
    build_dspy_lm,
    build_textgrad_engine,
)
from plasticity.gradient import GradientReport, TextGradient
from plasticity.metric import (
    EvalReport,
    Example,
    contains,
    evaluate,
    exact_match,
    llm_judge,
    regex_match,
)
from plasticity.program import Demo, Program
from plasticity.signature import Field, Signature
from plasticity.store import load_compiled, save_compiled

__all__ = [
    "BootstrapReport",
    "Compiler",
    "AttentionDecision",
    "AttentionEntity",
    "AttentionWeights",
    "Demo",
    "EvalReport",
    "Example",
    "Field",
    "GradientReport",
    "LanguageEngine",
    "Program",
    "Signature",
    "TextGradient",
    "build_dspy_lm",
    "build_textgrad_engine",
    "hash_binary_with_brain_metadata",
    "contains",
    "evaluate",
    "exact_match",
    "llm_judge",
    "load_compiled",
    "persist_ip_as_binary",
    "ping_local_model",
    "regex_match",
    "request_structured_response",
    "route_entities",
    "save_compiled",
    "score_entity",
]
