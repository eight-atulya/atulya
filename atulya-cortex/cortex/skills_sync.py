"""skills_sync.py — copy bundled markdown skills into the home skills dir.

The cortex ships with a small set of starter skills under
`cortex/templates/skills/`. On install (and again on every `setup` /
`skills sync`), we copy them into `home.skills_dir`. Two failure modes we
have to design around:

1. **The bundled skill changes between releases.** We detect this by
   recording the bundled file's `(mtime, size)` in `.bundled_manifest`
   and re-copying when it differs.
2. **The user edited their copy.** We also record the destination's
   `(mtime, size)` immediately after each copy. If the user later modifies
   the file in their home (different `(mtime, size)` than recorded), we
   preserve their edit and skip the overwrite unless `force=True`.

Returned `SyncResult` lists every action taken so the wizard / dashboard /
doctor can render a useful summary.

Idempotent: calling `sync` twice in a row produces the same on-disk result
on the second run, with `copied=[]` and either `skipped=[...]` or
`preserved=[...]`.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from cortex.home import CortexHome

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    copied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    preserved: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.copied)

    def to_dict(self) -> dict:
        return asdict(self)


def bundled_skills_dir() -> Path:
    """The packaged-skills source directory.

    Resolved relative to this module so it works in editable installs and
    in the wheel where `cortex/templates/skills/` is force-included.
    """

    return (Path(__file__).parent / "templates" / "skills").resolve()


def _file_signature(path: Path) -> tuple[float, int]:
    st = path.stat()
    # Round mtime to whole seconds; some filesystems (FAT, NFS) only have
    # second-precision and round-tripping a float would falsely flag drift.
    return (float(int(st.st_mtime)), int(st.st_size))


def _load_manifest(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict] = {}
    for name, entry in data.items():
        if isinstance(name, str) and isinstance(entry, dict):
            out[name] = entry
    return out


def _save_manifest(path: Path, manifest: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".manifest-", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def sync(
    home: CortexHome,
    *,
    force: bool = False,
    source_dir: Path | None = None,
) -> SyncResult:
    """Copy bundled skills into `home.skills_dir`. See module docstring.

    `source_dir` overrides the bundled source (useful for tests and for an
    eventual community-pack mechanism).
    """

    src_root = Path(source_dir).resolve() if source_dir is not None else bundled_skills_dir()
    result = SyncResult()
    if not src_root.exists():
        result.errors.append(f"bundled skills dir missing: {src_root}")
        logger.warning("skills_sync: %s", result.errors[-1])
        return result

    home.skills_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(home.skills_manifest)

    for src in sorted(src_root.glob("*.md")):
        name = src.name
        dst = home.skills_dir / name
        try:
            current_bundled = _file_signature(src)
        except OSError as exc:
            result.errors.append(f"{name}: cannot stat source ({exc})")
            continue

        recorded = manifest.get(name) or {}
        recorded_bundled = tuple(recorded.get("bundled", ())) or None
        recorded_dest = tuple(recorded.get("dest_after_copy", ())) or None

        if not dst.exists():
            _copy_and_record(src, dst, name, current_bundled, manifest)
            result.copied.append(name)
            continue

        try:
            current_dest = _file_signature(dst)
        except OSError as exc:
            result.errors.append(f"{name}: cannot stat destination ({exc})")
            continue

        user_edited = recorded_dest is not None and current_dest != recorded_dest
        bundled_changed = recorded_bundled != current_bundled

        if not bundled_changed and not user_edited:
            result.skipped.append(name)
            continue

        if user_edited and not force:
            result.preserved.append(name)
            continue

        _copy_and_record(src, dst, name, current_bundled, manifest)
        result.copied.append(name)

    try:
        _save_manifest(home.skills_manifest, manifest)
    except OSError as exc:
        result.errors.append(f"manifest write failed: {exc}")

    if result.copied or result.errors:
        logger.info(
            "skills_sync: copied=%d skipped=%d preserved=%d errors=%d",
            len(result.copied),
            len(result.skipped),
            len(result.preserved),
            len(result.errors),
        )
    return result


def _copy_and_record(
    src: Path,
    dst: Path,
    name: str,
    bundled_sig: tuple[float, int],
    manifest: dict[str, dict],
) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    dest_sig = _file_signature(dst)
    manifest[name] = {
        "bundled": list(bundled_sig),
        "dest_after_copy": list(dest_sig),
    }


__all__ = ["SyncResult", "bundled_skills_dir", "sync"]
