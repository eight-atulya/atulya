"""personality.py — the brain's voice on disk.

`Personality` reads a markdown file under `atulya-cortex/life/` and exposes
its content as the voice the Cortex speaks with. The file is plain
markdown; the only structure we care about is an optional YAML frontmatter
with `voice`, `traits`, and `bio` fields. Everything else is the body and
is rendered verbatim in the system prompt.

If the file is missing, a sensible default is returned (so a freshly-cloned
cortex still has a voice).

Naming voice: `Personality.load` for the constructor, `.voice` for the
short tag, `.bio` for the multi-paragraph history.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_VOICE = "calm, terse, kind"
DEFAULT_BIO = (
    "I am Atulya, a personal AI brain. I run locally when I can and remember "
    "what matters. I prefer short answers, ask before acting, and tell you "
    "when I am unsure."
)


@dataclass
class Personality:
    """A loaded personality."""

    voice: str = DEFAULT_VOICE
    bio: str = DEFAULT_BIO
    traits: list[str] = field(default_factory=list)
    body: str = ""
    source_path: str | None = None

    def system_prompt_block(self) -> str:
        """Render this personality as a single block for a system prompt."""

        lines: list[str] = []
        lines.append(f"Voice: {self.voice}")
        if self.traits:
            lines.append(f"Traits: {', '.join(self.traits)}")
        lines.append("Bio:")
        lines.append(self.bio)
        if self.body.strip():
            lines.append("Notes:")
            lines.append(self.body.strip())
        return "\n".join(lines)

    @classmethod
    def default(cls) -> "Personality":
        return cls()

    @classmethod
    def load(cls, path: str | Path) -> "Personality":
        """Read a personality markdown file from disk.

        Missing or unreadable file returns the default personality. This is
        deliberate: a fresh clone of cortex should still have a voice.
        """

        p = Path(path)
        if not p.exists() or not p.is_file():
            return cls.default()
        try:
            raw = p.read_text(encoding="utf-8")
        except OSError:
            return cls.default()

        frontmatter, body = _split_frontmatter(raw)
        voice = frontmatter.get("voice", DEFAULT_VOICE).strip() or DEFAULT_VOICE
        bio = frontmatter.get("bio", "").strip() or _first_paragraph(body) or DEFAULT_BIO
        traits_raw = frontmatter.get("traits", "")
        traits = [t.strip() for t in traits_raw.split(",") if t.strip()]
        return cls(
            voice=voice,
            bio=bio,
            traits=traits,
            body=body.strip(),
            source_path=str(p),
        )


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)
_KEY_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.*)$")


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    m = _FRONTMATTER_RE.match(text)
    if m is None:
        return {}, text
    head, body = m.group(1), m.group(2)
    fm: dict[str, str] = {}
    for line in head.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        km = _KEY_RE.match(line)
        if km is None:
            continue
        key, value = km.group(1).strip().lower(), km.group(2).strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        fm[key] = value
    return fm, body


def _first_paragraph(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    return text.split("\n\n", 1)[0].strip()


__all__ = ["DEFAULT_BIO", "DEFAULT_VOICE", "Personality"]
