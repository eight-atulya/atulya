"""skills.py — markdown skills on disk.

A "skill" is a markdown file under `atulya-cortex/life/40_knowledge/skills/`
(or any directory passed in). The first H1 (or filename) is the skill name,
and the first paragraph is its description. Skills are rendered into the
system prompt as a one-line catalogue; the cortex picks one by name when it
emits a `tool_call` or `delegate` action.

`Skills.discover()` is fast (re-reads on every call) so editing a skill
file takes effect on the next reflect — no daemon restart.

Naming voice: `Skills.discover` returns a list of `SkillRef` (defined in
the bus). The class is `Skills` plural because it holds a *catalogue*; an
individual skill is just a `SkillRef`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from cortex.bus import SkillRef

_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


class Skills:
    """A simple file-backed catalogue of skills."""

    def __init__(
        self,
        roots: Iterable[str | Path],
        *,
        suffixes: Iterable[str] = (".md", ".markdown"),
    ) -> None:
        self._roots = [Path(p) for p in roots]
        self._suffixes = tuple(s.lower() for s in suffixes)

    @property
    def roots(self) -> list[Path]:
        return list(self._roots)

    def discover(self) -> list[SkillRef]:
        """Walk every root, surface every markdown file as a SkillRef."""

        seen: set[str] = set()
        out: list[SkillRef] = []
        for root in self._roots:
            if not root.exists():
                continue
            if root.is_file():
                ref = self._read_skill(root)
                if ref and ref.path not in seen:
                    seen.add(ref.path)
                    out.append(ref)
                continue
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in self._suffixes:
                    continue
                ref = self._read_skill(path)
                if ref and ref.path not in seen:
                    seen.add(ref.path)
                    out.append(ref)
        return out

    def _read_skill(self, path: Path) -> SkillRef | None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        m = _H1_RE.search(text)
        name = m.group(1).strip() if m else path.stem
        description = self._first_paragraph(text, after_match=m)
        return SkillRef(name=name, path=str(path), description=description)

    @staticmethod
    def _first_paragraph(text: str, *, after_match: re.Match[str] | None) -> str | None:
        if after_match is not None:
            tail = text[after_match.end() :]
        else:
            tail = text
        tail = tail.strip()
        if not tail:
            return None
        para = tail.split("\n\n", 1)[0].strip()
        para = re.sub(r"\s+", " ", para)
        if not para:
            return None
        return para[:240]


def render_skills_block(skills: list[SkillRef]) -> str:
    """One-line-per-skill catalogue suitable for the system prompt."""

    if not skills:
        return "No skills loaded."
    lines = []
    for s in skills:
        desc = (s.description or "").strip()
        if desc:
            lines.append(f"- {s.name}: {desc}")
        else:
            lines.append(f"- {s.name}")
    return "\n".join(lines)


__all__ = ["Skills", "render_skills_block"]
