"""plasticity — compile and optimize LLM programs.

Subcommands:

- `atulya-cortex plasticity compile <program.json> <trainset.jsonl>`
    bootstrap few-shot demos and write the compiled program to the output path
    (defaults to `<home>/plasticity/<program_name>.compiled.json`).

- `atulya-cortex plasticity optimize <program.json> <trainset.jsonl>`
    textual-gradient optimization of the program's instructions.

- `atulya-cortex plasticity evaluate <program.json> <testset.jsonl>`
    run the program on the testset and print an EvalReport summary.

- `atulya-cortex plasticity run <program.json>`
    read one input record from stdin (or `--input`) and print the parsed
    program output as JSON.

Program files are JSON in the shape `Program.to_dict()` produces. Datasets
are JSONL where each line is `{"inputs": {...}, "outputs": {...}}`.

The command instantiates a `cortex.language.Language` from the active
profile's config so `plasticity` speaks to whichever provider the user
already configured. No separate auth story.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from cortex import config as cortex_config
from cortex.config import ConfigError
from cortex.language import Language, Provider
from plasticity import (
    BootstrapReport,
    Compiler,
    Example,
    GradientReport,
    Program,
    TextGradient,
    evaluate,
    exact_match,
    load_compiled,
    save_compiled,
)
from plasticity.metric import Metric

NAME = "plasticity"
HELP = "Compile, optimize, or evaluate LLM programs (DSPy + TextGrad)."


def register(subparsers, common_parents) -> None:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=list(common_parents),
        description="The cortex's neuroplasticity toolkit — compile and optimize LLM programs.",
    )
    sub = parser.add_subparsers(dest="plasticity_command", metavar="<action>")

    _register_compile(sub, common_parents)
    _register_optimize(sub, common_parents)
    _register_evaluate(sub, common_parents)
    _register_run(sub, common_parents)

    parser.set_defaults(_run=run)


def run(args: argparse.Namespace, *, home) -> int:
    handler = getattr(args, "_plasticity_run", None)
    if handler is None:
        sys.stderr.write("error: specify a plasticity subcommand (compile|optimize|evaluate|run)\n")
        return 2
    return handler(args, home=home)


# ---------------------------------------------------------------------------
# Subcommand wiring
# ---------------------------------------------------------------------------


def _register_compile(sub, common_parents) -> None:
    p = sub.add_parser(
        "compile",
        parents=list(common_parents),
        help="Bootstrap few-shot demos into a compiled program JSON.",
    )
    p.add_argument("program", type=Path, help="Path to a Program JSON file.")
    p.add_argument("trainset", type=Path, help="Path to JSONL trainset.")
    p.add_argument("--valset", type=Path, default=None, help="Optional JSONL valset (score baseline vs compiled).")
    p.add_argument("--metric-field", default=None, help="Output field used by the default exact_match metric.")
    p.add_argument("--out", type=Path, default=None, help="Where to write the compiled program JSON.")
    p.add_argument("--max-demos", type=int, default=4)
    p.add_argument("--backend", choices=("auto", "local", "dspy"), default="auto")
    p.add_argument("--provider", default=None)
    p.add_argument("--model", default=None)
    p.set_defaults(_plasticity_run=_run_compile)


def _register_optimize(sub, common_parents) -> None:
    p = sub.add_parser(
        "optimize",
        parents=list(common_parents),
        help="Textual-gradient optimization of the program instructions.",
    )
    p.add_argument("program", type=Path)
    p.add_argument("trainset", type=Path)
    p.add_argument("--valset", type=Path, default=None)
    p.add_argument("--metric-field", default=None)
    p.add_argument("--steps", type=int, default=3)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--backend", choices=("auto", "local", "textgrad"), default="auto")
    p.add_argument("--provider", default=None)
    p.add_argument("--model", default=None)
    p.set_defaults(_plasticity_run=_run_optimize)


def _register_evaluate(sub, common_parents) -> None:
    p = sub.add_parser(
        "evaluate",
        parents=list(common_parents),
        help="Run the program on a testset and print the EvalReport.",
    )
    p.add_argument("program", type=Path)
    p.add_argument("testset", type=Path)
    p.add_argument("--metric-field", default=None)
    p.add_argument("--provider", default=None)
    p.add_argument("--model", default=None)
    p.set_defaults(_plasticity_run=_run_evaluate)


def _register_run(sub, common_parents) -> None:
    p = sub.add_parser(
        "run",
        parents=list(common_parents),
        help="Run a compiled program on one input record.",
    )
    p.add_argument("program", type=Path)
    p.add_argument("--input", type=Path, default=None, help="JSON file with an inputs object; defaults to stdin.")
    p.add_argument("--provider", default=None)
    p.add_argument("--model", default=None)
    p.set_defaults(_plasticity_run=_run_once)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _run_compile(args: argparse.Namespace, *, home) -> int:
    program = _load_program(args.program)
    trainset = _load_dataset(args.trainset)
    valset = _load_dataset(args.valset) if args.valset else None
    metric = _build_metric(program, args.metric_field)

    language = _build_language(home)
    try:
        compiler = Compiler(max_demos=args.max_demos)
        compiled, report = asyncio.run(
            compiler.compile(
                program,
                language,
                trainset=trainset,
                metric=metric,
                valset=valset,
                backend=args.backend,
                provider=args.provider,
                model=args.model,
            )
        )
    finally:
        asyncio.run(language.aclose())

    out_path = args.out or _default_out_path(home, args.program, "compiled")
    save_compiled(out_path, compiled, meta={"source": str(args.program)})
    _print_bootstrap_report(report, out_path)
    return 0


def _run_optimize(args: argparse.Namespace, *, home) -> int:
    program = _load_program(args.program)
    trainset = _load_dataset(args.trainset)
    valset = _load_dataset(args.valset) if args.valset else None
    metric = _build_metric(program, args.metric_field)

    language = _build_language(home)
    try:
        grad = TextGradient()
        tuned, report = asyncio.run(
            grad.optimize(
                program,
                language,
                trainset=trainset,
                metric=metric,
                valset=valset,
                steps=args.steps,
                backend=args.backend,
                provider=args.provider,
                model=args.model,
            )
        )
    finally:
        asyncio.run(language.aclose())

    out_path = args.out or _default_out_path(home, args.program, "optimized")
    save_compiled(out_path, tuned, meta={"source": str(args.program), "steps": args.steps})
    _print_gradient_report(report, out_path)
    return 0


def _run_evaluate(args: argparse.Namespace, *, home) -> int:
    program = _load_program(args.program)
    testset = _load_dataset(args.testset)
    metric = _build_metric(program, args.metric_field)

    language = _build_language(home)
    try:
        report = asyncio.run(
            evaluate(
                program,
                language,
                testset,
                metric,
                provider=args.provider,
                model=args.model,
            )
        )
    finally:
        asyncio.run(language.aclose())

    print(f"evaluate {args.program}: {report.summary()}")
    for i, tr in enumerate(report.traces, start=1):
        mark = "pass" if tr.score >= 1.0 else "fail"
        err = f" err={tr.error}" if tr.error else ""
        print(f"  [{i:>3}] {mark} score={tr.score:.3f}{err}")
    return 0


def _run_once(args: argparse.Namespace, *, home) -> int:
    program = _load_program(args.program)
    raw = args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()
    try:
        inputs = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"error: input is not valid JSON: {exc}\n")
        return 2
    if not isinstance(inputs, dict):
        sys.stderr.write("error: input must be a JSON object\n")
        return 2

    language = _build_language(home)
    try:
        out = asyncio.run(
            program.forward(
                language,
                {str(k): str(v) for k, v in inputs.items()},
                provider=args.provider,
                model=args.model,
            )
        )
    finally:
        asyncio.run(language.aclose())

    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_program(path: Path) -> Program:
    if not path.exists():
        raise FileNotFoundError(f"program file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if "version" in data:
        artifact = load_compiled(path)
        return artifact.program
    return Program.from_dict(data)


def _load_dataset(path: Path) -> list[Example]:
    records: list[Example] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        data = json.loads(line)
        records.append(Example.from_dict(data))
    if not records:
        raise ValueError(f"dataset {path} is empty")
    return records


def _build_metric(program: Program, field_name: str | None) -> Metric:
    if not field_name:
        field_name = program.signature.output_names[0]
    return exact_match(field_name)


def _build_language(home) -> Language:
    """Build a Language from the active profile's config, with a safe fallback."""

    try:
        cfg = cortex_config.load(home)
    except (ConfigError, FileNotFoundError, OSError):
        return Language.with_lm_studio()

    provider = _provider_from_config(cfg)
    return Language([provider])


def _provider_from_config(cfg: Any) -> Provider:
    model_cfg = getattr(cfg, "model", None)
    if model_cfg is None:
        return Provider.lm_studio()
    base_url = getattr(model_cfg, "base_url", None) or ""
    model_id = getattr(model_cfg, "model", None) or ""
    api_key_env = getattr(model_cfg, "api_key_env", None) or ""
    api_key = os.environ.get(api_key_env, "") if api_key_env else ""
    name = getattr(model_cfg, "provider", "configured") or "configured"
    if base_url:
        return Provider(
            name=name,
            base_url=base_url,
            api_key=api_key,
            default_model=model_id,
        )
    return Provider.lm_studio(model=model_id or "google/gemma-3-4b")


def _default_out_path(home, program_path: Path, suffix: str) -> Path:
    base = program_path.stem
    return home.plasticity_dir / f"{base}.{suffix}.json"


def _print_bootstrap_report(report: BootstrapReport, out_path: Path) -> None:
    print(f"compiled -> {out_path}")
    print(f"  {report.summary()}")
    for note in report.notes:
        print(f"  note: {note}")


def _print_gradient_report(report: GradientReport, out_path: Path) -> None:
    print(f"optimized -> {out_path}")
    print(f"  {report.summary()}")
    for tr in report.steps:
        mark = "accept" if tr.accepted else "reject"
        print(f"  step {tr.step}: {mark} {tr.score_before:.3f} -> {tr.score_after:.3f}")


__all__ = ["NAME", "HELP", "register", "run"]
