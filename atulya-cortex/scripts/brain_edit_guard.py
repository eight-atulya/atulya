#!/usr/bin/env python3
"""
Run a brain-backed post-edit validation pass for changed files.

This script provides a practical baseline integration between repository edits and
Atulya's brain runtime:
1. Detect changed files.
2. Run hard checks for changed Python files via py_compile.
3. Ask the current brain runtime to simulate likely regression risks.

Today, the brain runtime still defaults to a dummy LLM backend, so the simulation
output is best treated as a structured placeholder until a real backend is wired.
The hard checks are the reliable enforcement layer.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import py_compile
import subprocess
import sys
import tempfile
import textwrap
from typing import Iterable, List, Sequence


SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[1]
REPO_ROOT = PROJECT_ROOT.parents[0]
BRAIN_PATH = PROJECT_ROOT / "brain.py"
MAX_DIFF_CHARS = 12000


def run_cmd(cmd: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd),
        cwd=str(cwd),
        check=False,
        text=True,
        capture_output=True,
    )


def get_changed_files(repo_root: Path, staged: bool) -> List[Path]:
    diff_cmd = ["git", "diff", "--name-only"]
    if staged:
        diff_cmd.append("--cached")
    else:
        diff_cmd.append("HEAD")

    diff_result = run_cmd(diff_cmd, repo_root)
    changed = [line.strip() for line in diff_result.stdout.splitlines() if line.strip()]

    if not staged:
        untracked_result = run_cmd(
            ["git", "ls-files", "--others", "--exclude-standard"],
            repo_root,
        )
        changed.extend(
            line.strip() for line in untracked_result.stdout.splitlines() if line.strip()
        )

    deduped: List[Path] = []
    seen = set()
    for rel in changed:
        path = (repo_root / rel).resolve()
        if path in seen or not path.exists():
            continue
        seen.add(path)
        deduped.append(path)

    return deduped


def filter_existing(paths: Iterable[Path]) -> List[Path]:
    return [path.resolve() for path in paths if path.exists()]


def compile_python_files(paths: Iterable[Path]) -> List[str]:
    failures: List[str] = []
    for path in paths:
        if path.suffix != ".py":
            continue
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append(f"{path}: {exc.msg}")
        except Exception as exc:  # pragma: no cover - defensive
            failures.append(f"{path}: {exc}")
    return failures


def read_diff(repo_root: Path, paths: Sequence[Path], staged: bool) -> str:
    rel_paths = [os.path.relpath(path, repo_root) for path in paths]
    if not rel_paths:
        return ""

    diff_cmd = ["git", "diff", "--"]
    if staged:
        diff_cmd = ["git", "diff", "--cached", "--"]
    elif run_cmd(["git", "rev-parse", "--verify", "HEAD"], repo_root).returncode == 0:
        diff_cmd = ["git", "diff", "HEAD", "--"]

    result = run_cmd(diff_cmd + rel_paths, repo_root)
    diff_text = result.stdout.strip()

    if not diff_text:
        snippets = []
        for path in paths:
            if path.suffix == ".py":
                try:
                    snippets.append(
                        f"FILE: {os.path.relpath(path, repo_root)}\n"
                        + path.read_text(encoding="utf-8", errors="replace")[:1200]
                    )
                except Exception:
                    continue
        diff_text = "\n\n".join(snippets)

    if len(diff_text) > MAX_DIFF_CHARS:
        diff_text = diff_text[:MAX_DIFF_CHARS] + "\n...[truncated]..."

    return diff_text


def load_brain_module():
    spec = importlib.util.spec_from_file_location("atulya_brain_runtime", BRAIN_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load brain runtime from {BRAIN_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_brain_simulation(paths: Sequence[Path], diff_text: str) -> str:
    brain = load_brain_module()

    with tempfile.TemporaryDirectory(prefix="atulya-brain-guard-") as tmpdir:
        cfg = brain.build_isolated_config(tmpdir)
        prompt = textwrap.dedent(
            f"""
            Simulate a post-edit review for these repository changes.

            Goal:
            - Identify likely regressions, broken imports, interface mismatches, and missing tests.
            - Suggest the next 3 validation steps.
            - Keep the answer concise and practical.

            Changed files:
            {chr(10).join(f"- {os.path.relpath(path, REPO_ROOT)}" for path in paths) or "- none"}

            Change details:
            {diff_text or "(no diff available)"}
            """
        ).strip()
        return brain.run_once(prompt, cfg)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Atulya brain edit guard.")
    parser.add_argument(
        "--files",
        nargs="*",
        help="Explicit files to validate. Defaults to git-changed files.",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Use staged files instead of current working tree changes.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.files:
        candidate_paths = [
            Path(path) if os.path.isabs(path) else (REPO_ROOT / path)
            for path in args.files
        ]
        paths = filter_existing(candidate_paths)
    else:
        paths = get_changed_files(REPO_ROOT, staged=args.staged)

    if not paths:
        print("brain_edit_guard: no changed files to validate.")
        return 0

    python_failures = compile_python_files(paths)
    diff_text = read_diff(REPO_ROOT, paths, staged=args.staged)

    print("=== Brain Edit Guard ===")
    print("Files under review:")
    for path in paths:
        print(f"- {os.path.relpath(path, REPO_ROOT)}")

    if python_failures:
        print("\nCompile failures:")
        for failure in python_failures:
            print(f"- {failure}")
    else:
        print("\nCompile check: passed")

    print("\nBrain simulation:")
    try:
        simulation = run_brain_simulation(paths, diff_text)
        print(simulation)
        if "[Ψ DUMMY KERNEL]" in simulation:
            print(
                "\nNote: the current brain runtime is using its dummy LLM backend, "
                "so this simulation is only a placeholder until a real backend is wired."
            )
    except Exception as exc:
        print(f"Brain simulation failed: {exc}")
        return 1

    return 1 if python_failures else 0


if __name__ == "__main__":
    sys.exit(main())
