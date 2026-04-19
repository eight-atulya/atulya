"""profile.py — switch the cortex between named overlays.

A *profile* is an overlay directory under `profiles/<name>/` that overrides
the profile-scoped paths exposed by `CortexHome` (config, persona, pairing,
state, skills, cron). Caches, logs, and the WhatsApp session are shared.

Use cases:
- A "work" profile with a different persona, allowlist, and bank id.
- A "demo" profile for screenshots that resets pairing on every run.
- A "test" profile pointed at a sandbox atulya-api instance.

Naming voice: `Profile.current(home)` for read; `Profile.switch(home, name)`
for write. The active profile is persisted in `<home>/current_profile`.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Sequence

from cortex.home import (
    DEFAULT_PROFILE_NAME,
    CortexHome,
    _validate_profile_name,
)


@dataclass(frozen=True)
class Profile:
    """A named overlay. The default profile is the home root itself."""

    name: str

    @property
    def is_default(self) -> bool:
        return self.name == DEFAULT_PROFILE_NAME

    # ---- read --------------------------------------------------------------

    @classmethod
    def current(cls, home: CortexHome) -> "Profile":
        """Return the profile this `CortexHome` was resolved with."""

        return cls(name=home.profile_name)

    @classmethod
    def list(cls, home: CortexHome) -> list["Profile"]:
        """List all known profiles, default first then alphabetical."""

        names: list[str] = [DEFAULT_PROFILE_NAME]
        if home.profiles_root.exists():
            for child in sorted(home.profiles_root.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
                    try:
                        _validate_profile_name(child.name)
                    except ValueError:
                        continue
                    names.append(child.name)
        # de-dupe while preserving order
        seen: set[str] = set()
        ordered: list[str] = []
        for n in names:
            if n in seen:
                continue
            seen.add(n)
            ordered.append(n)
        return [cls(name=n) for n in ordered]

    # ---- write -------------------------------------------------------------

    @classmethod
    def create(cls, home: CortexHome, name: str) -> "Profile":
        """Create a new profile overlay. The directory itself is seeded but
        files are written by the wizard / installer, not here.

        Raises `ValueError` for the default profile (it always exists) or if
        the profile already exists.
        """

        _validate_profile_name(name)
        if name == DEFAULT_PROFILE_NAME:
            raise ValueError(f"profile {DEFAULT_PROFILE_NAME!r} always exists")
        target = home.profiles_root / name
        if target.exists():
            raise ValueError(f"profile {name!r} already exists at {target}")
        target.mkdir(parents=True, exist_ok=False)
        for sub in ("pairing", "state", "skills", "cron"):
            (target / sub).mkdir(parents=True, exist_ok=True)
        return cls(name=name)

    @classmethod
    def switch(cls, home: CortexHome, name: str) -> "Profile":
        """Persist `name` as the active profile.

        The caller is responsible for re-resolving `CortexHome` afterwards;
        the existing `home` instance is frozen and will not pick up the new
        active profile until rebuilt.
        """

        _validate_profile_name(name)
        existing = {p.name for p in cls.list(home)}
        if name not in existing:
            raise ValueError(f"unknown profile {name!r} (known: {sorted(existing)})")
        home.current_profile_file.parent.mkdir(parents=True, exist_ok=True)
        home.current_profile_file.write_text(name, encoding="utf-8")
        return cls(name=name)

    @classmethod
    def delete(cls, home: CortexHome, name: str, *, allow_active: bool = False) -> None:
        """Delete a profile overlay. Refuses the default profile.

        If `name` is currently active and `allow_active` is False (default),
        raises rather than orphaning the `current_profile` pointer.
        """

        _validate_profile_name(name)
        if name == DEFAULT_PROFILE_NAME:
            raise ValueError(f"refusing to delete the {DEFAULT_PROFILE_NAME!r} profile")
        if not allow_active and home.profile_name == name:
            raise ValueError(f"profile {name!r} is currently active; switch first or pass allow_active=True")
        target = home.profiles_root / name
        if not target.exists():
            return
        shutil.rmtree(target)
        if home.current_profile_file.exists():
            try:
                if home.current_profile_file.read_text(encoding="utf-8").strip() == name:
                    home.current_profile_file.unlink()
            except OSError:
                pass

    @classmethod
    def names(cls, home: CortexHome) -> Sequence[str]:
        return [p.name for p in cls.list(home)]


__all__ = ["Profile"]
