"""affect.py — the amygdala. Tags every turn with an affective signature.

Why a brain needs this
----------------------

Neocortex consolidation is *gated by affect*. Boring, predictable turns
("ok thanks", "got it") barely deserve to be remembered, while
emotionally charged or surprising turns ("I quit my job", "we're getting
divorced", "the bug is fixed!!!") deserve immediate semantic encoding.
Without an affect signal, the consolidation pass would either drown in
noise or miss the signal entirely.

The amygdala in real brains computes valence + arousal in tens of
milliseconds, ahead of conscious processing. Our `score_text` is a pure
heuristic that runs in microseconds — no LLM, no network — so it can
tag every single turn without budget anxiety. An optional `Augmentor`
hook lets you swap in a real model later (e.g. a tiny sentiment model
exported from atulya-embed) without rewriting callers.

Output: `Affect(valence, arousal, salience)`
- valence  in [-1, +1]   negative ... positive
- arousal  in [0, 1]     calm ... excited
- salience in [0, 1]     ignore ... must-remember

`salience` is the integrator the consolidation pass reads. It blends
arousal, |valence|, and length/novelty heuristics into a single
"how badly should I remember this" score.

Naming voice: `score_text` is the core verb; `Affect` the noun.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable

# Word lists chosen for speed not subtlety. We score on stems so that
# "frustrated", "frustrating", "frustration" all hit the same bucket.
# A real brain has a far richer prior; this is the smallest table that
# is still useful in practice across the typical operator-to-cortex
# transcript.
_POS_STEMS: frozenset[str] = frozenset(
    {
        "love", "great", "amazing", "awesome", "fantastic", "happy", "glad",
        "thank", "thanks", "appreciate", "good", "nice", "wonderful", "yes",
        "yay", "win", "won", "fixed", "solved", "works", "working", "perfect",
        "excited", "exciting", "brilliant", "beautiful", "cool", "calm",
        "proud", "succeed", "success", "done",
    }
)
_NEG_STEMS: frozenset[str] = frozenset(
    {
        "hate", "angry", "anger", "frustrat", "annoy", "annoying", "sad",
        "depress", "tired", "exhaust", "broken", "broke", "fail", "failed",
        "failing", "bug", "error", "crash", "stuck", "lost", "lose", "wrong",
        "bad", "worse", "worst", "no", "not", "never", "nothing", "nobody",
        "shit", "fuck", "damn", "hell", "screw", "useless", "stupid",
        "fear", "afraid", "scared", "worried", "worry", "anxious", "panic",
        "die", "dying", "dead", "kill",
    }
)
_HIGH_AROUSAL_STEMS: frozenset[str] = frozenset(
    {
        "urgent", "asap", "now", "emergency", "critical", "immediately",
        "shit", "fuck", "wow", "omg", "amazing", "awful", "terrible", "panic",
        "hurry", "rush", "quick", "fast", "alarm", "scream", "shock",
    }
)

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z']+")
_QUESTION_RE = re.compile(r"\?")
_EXCLAIM_RE = re.compile(r"!")


@dataclass(frozen=True)
class Affect:
    """One turn's affective signature. All scores are bounded floats."""

    valence: float
    arousal: float
    salience: float
    triggers: tuple[str, ...] = ()  # which stems fired, for debugging

    def to_dict(self) -> dict[str, object]:
        """JSON-friendly form for episode persistence."""

        return {
            "valence": round(self.valence, 4),
            "arousal": round(self.arousal, 4),
            "salience": round(self.salience, 4),
            "triggers": list(self.triggers),
        }

    @classmethod
    def neutral(cls) -> "Affect":
        return cls(valence=0.0, arousal=0.0, salience=0.0, triggers=())


Augmentor = Callable[[str], Awaitable["Affect | None"]]
"""Async hook for swapping in a real sentiment model later. The default
heuristic runs first and only delegates when the augmentor is wired."""


def _tokens(text: str) -> list[str]:
    return [m.group(0).lower() for m in _WORD_RE.finditer(text)]


def _stem_hits(tokens: Iterable[str], stems: frozenset[str]) -> list[str]:
    """Find tokens that *start with* any stem (cheap stemmer).

    We use prefix matching rather than full-form matching so that
    "frustrated"/"frustrating"/"frustration" all hit the "frustrat" stem
    without us maintaining a giant lemma table.
    """

    hits: list[str] = []
    for tok in tokens:
        for stem in stems:
            if tok.startswith(stem):
                hits.append(tok)
                break
    return hits


def score_text(text: str) -> Affect:
    """Score a single text body. Pure, deterministic, microsecond-cheap.

    The output is *intentionally coarse* — three floats and a list of
    triggering stems. Downstream code (consolidation, recall) reads only
    `salience` to make priority decisions; the other fields are for
    debug, dashboards, and future affective adaptation of the persona.
    """

    if not text:
        return Affect.neutral()

    body = text.strip()
    if not body:
        return Affect.neutral()

    tokens = _tokens(body)
    if not tokens:
        return Affect.neutral()

    pos = _stem_hits(tokens, _POS_STEMS)
    neg = _stem_hits(tokens, _NEG_STEMS)
    arousal_hits = _stem_hits(tokens, _HIGH_AROUSAL_STEMS)

    n = max(1, len(tokens))
    # Valence: signed normalised hit-density. Bounded to keep one
    # outlier word from saturating the channel.
    raw_val = (len(pos) - len(neg)) / n
    valence = max(-1.0, min(1.0, raw_val * 4.0))  # scale so 25% hit-rate = ±1

    # Arousal: mix of high-arousal stems, exclamation marks, and ALL CAPS
    # (which is body-language for shouting in chat).
    excl = len(_EXCLAIM_RE.findall(body))
    cap_ratio = sum(1 for c in body if c.isupper()) / max(1, sum(1 for c in body if c.isalpha()))
    arousal = min(
        1.0,
        len(arousal_hits) / n * 4.0
        + min(0.4, excl * 0.15)
        + (max(0.0, cap_ratio - 0.4) * 1.5),
    )

    # Salience: how badly should consolidation remember this? Blend
    # |valence| and arousal, then add a small length bonus (a paragraph
    # carries more potential signal than "ok"), and a tiny question-mark
    # bonus (questions are intentions; intentions matter for recall).
    questions = min(0.2, len(_QUESTION_RE.findall(body)) * 0.08)
    length_bonus = min(0.3, (len(body) / 600.0) * 0.3)
    salience = min(
        1.0,
        0.55 * abs(valence) + 0.35 * arousal + length_bonus + questions,
    )

    triggers = tuple(sorted(set(pos + neg + arousal_hits)))[:8]
    return Affect(valence=valence, arousal=arousal, salience=salience, triggers=triggers)


async def score_with_augmentor(text: str, augmentor: Augmentor | None) -> Affect:
    """Score with the heuristic, then let an optional augmentor refine.

    The augmentor returns `None` to signal "no opinion, keep the
    heuristic". This lets us A/B different scorers (small sentiment
    model, full LLM) without rewriting every caller — the contract
    stays "give me an Affect for this text".
    """

    base = score_text(text)
    if augmentor is None:
        return base
    try:
        refined = await augmentor(text)
    except Exception:
        return base
    if refined is None:
        return base
    return refined


__all__ = ["Affect", "Augmentor", "score_text", "score_with_augmentor"]
