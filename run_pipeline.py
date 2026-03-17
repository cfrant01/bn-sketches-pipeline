#!/usr/bin/env python3
"""
Run the local pipeline:
1) create_bnet.py         -> generate a .bnet file
2) generate_traces_from_bnet.R -> generate traces from that .bnet using a config file
3) traces_to_sketch_properties.py -> generate trace-based PROPERTIES snippet
4) bnet_to_sketchStructure.py -> generate MODEL snippet from the .bnet
5) attractors_to_sketch_properties.py -> generate attractor/fixed-point dynamic properties
6) combine_sketch_parts.py -> combine PROPERTIES and MODEL into a final sketch file

Examples:
    python run_pipeline.py --random --n 5 --k 2 ^
      --bnet-output "outputs\\bnet\\net.bnet" ^
      --trace-config "configs\\traces_configuration_example.txt" ^
      --traces-properties-config "configs\\traces_to_sketch_properties_params.txt" ^
      --structure-config "configs\\bnet_to_sketchStructure_params.txt"

    python run_pipeline.py --input "configs\\sample_rules.txt" ^
      --bnet-output "outputs\\bnet\\from_rules.bnet" ^
      --trace-config "configs\\traces_configuration_example.txt" ^
      --traces-properties-config "configs\\traces_to_sketch_properties_params.txt" ^
      --structure-config "configs\\bnet_to_sketchStructure_params.txt"
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Dict


def quote_cmd(parts: list[str]) -> str:
    return " ".join(shlex.quote(p) for p in parts)


def run_cmd(cmd: list[str], cwd: Path) -> None:
    print(f"\n[RUN] {quote_cmd(cmd)}")
    result = subprocess.run(cmd, cwd=str(cwd))
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def resolve_user_path(value: str, base_dir: Path, cwd: Path | None = None) -> Path:
    p = Path(value)
    if p.is_absolute():
        return p
    if cwd is not None:
        candidate = cwd / p
        if candidate.exists():
            return candidate
    return base_dir / p


def read_kv_config(path: Path) -> Dict[str, str]:
    cfg: Dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    for idx, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{idx} invalid config line (expected key = value): {raw}")
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip()
    return cfg


def build_create_bnet_command(args: argparse.Namespace, scripts_dir: Path) -> list[str]:
    create_script = scripts_dir / "create_bnet.py"
    cmd = [args.python_cmd, str(create_script)]

    if args.random:
        cmd.extend(["--random", "--n", str(args.n), "--k", str(args.k)])
        if args.seed is not None:
            cmd.extend(["--seed", str(args.seed)])
        if args.node_prefix is not None:
            cmd.extend(["--node-prefix", args.node_prefix])
    else:
        cmd.extend(["--input", args.input])

    cmd.extend(["--output", args.bnet_output])

    if args.no_header:
        cmd.append("--no-header")

    return cmd


def build_trace_command(args: argparse.Namespace, scripts_dir: Path) -> list[str]:
    trace_script = scripts_dir / "generate_traces_from_bnet.R"
    return [
        args.rscript_cmd,
        str(trace_script),
        "--bnet",
        args.bnet_output,
        "--config",
        args.trace_config,
    ]


def build_trace_properties_command(
    args: argparse.Namespace,
    scripts_dir: Path,
    traces_dir: Path,
    trace_properties_output: Path,
) -> list[str]:
    script = scripts_dir / "traces_to_sketch_properties.py"
    cmd = [args.python_cmd, str(script)]
    if args.traces_properties_config:
        cmd.extend(["--config", args.traces_properties_config])
    cmd.extend(["--traces-dir", str(traces_dir), "--output", str(trace_properties_output)])
    return cmd


def build_structure_command(
    args: argparse.Namespace,
    scripts_dir: Path,
    bnet_output: Path,
    structure_output: Path,
) -> list[str]:
    script = scripts_dir / "bnet_to_sketchStructure.py"
    cmd = [args.python_cmd, str(script)]
    if args.structure_config:
        cmd.extend(["--config", args.structure_config])
    cmd.extend(["--bnet", str(bnet_output), "--output", str(structure_output)])
    return cmd


def build_attractor_properties_command(
    args: argparse.Namespace,
    scripts_dir: Path,
    attractor_summary: Path,
    attractor_properties_output: Path,
    genes_path: Path,
) -> list[str]:
    script = scripts_dir / "attractors_to_sketch_properties.py"
    cmd = [
        args.python_cmd,
        str(script),
        "--summary",
        str(attractor_summary),
        "--genes",
        str(genes_path),
        "--output",
        str(attractor_properties_output),
        "--mode",
        args.attractor_properties_mode,
    ]
    if args.include_forbid_extra:
        cmd.append("--include-forbid-extra")
    return cmd


def build_combine_command(
    args: argparse.Namespace,
    scripts_dir: Path,
    properties_input: Path,
    model_input: Path,
    combined_output: Path,
) -> list[str]:
    script = scripts_dir / "combine_sketch_parts.py"
    return [
        args.python_cmd,
        str(script),
        "--properties",
        str(properties_input),
        "--model",
        str(model_input),
        "--output",
        str(combined_output),
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run create_bnet.py and then generate_traces_from_bnet.R as a single pipeline command."
    )

    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--random", action="store_true", help="Generate a random .bnet (uses --n and --k).")
    source_group.add_argument("--input", help="Rules file or rules directory for create_bnet.py input mode.")

    parser.add_argument("--n", type=int, help="Number of nodes for --random mode.")
    parser.add_argument("--k", type=int, help="Maximum number of regulators per function for --random mode.")
    parser.add_argument("--seed", type=int, help="Optional seed for create_bnet.py random mode.")
    parser.add_argument("--node-prefix", default="x", help="Node prefix for random mode (default: x).")
    parser.add_argument("--no-header", action="store_true", help="Pass --no-header to create_bnet.py.")

    parser.add_argument("--bnet-output", required=True, help="Path to the generated .bnet file (used by both steps).")
    parser.add_argument("--trace-config", required=True, help="Trace config file for generate_traces_from_bnet.R.")
    parser.add_argument(
        "--traces-properties-config",
        default="configs/traces_to_sketch_properties_params.txt",
        help="Config file for traces_to_sketch_properties.py (CLI overrides will set traces dir/output).",
    )
    parser.add_argument(
        "--structure-config",
        default="configs/bnet_to_sketchStructure_params.txt",
        help="Config file for bnet_to_sketchStructure.py (CLI overrides will set bnet/output).",
    )
    parser.add_argument(
        "--trace-properties-output",
        help="Optional output path for trace-derived properties snippet (default: outputs/sketch_parts/<bnet_stem>_trace_properties.aeon).",
    )
    parser.add_argument(
        "--structure-output",
        help="Optional output path for model-structure snippet (default: outputs/sketch_parts/<bnet_stem>_model_part.aeon).",
    )
    parser.add_argument(
        "--attractor-properties-output",
        help="Optional output path for attractor/fixed-point properties snippet (default: outputs/sketch_parts/<bnet_stem>_attractors_properties.aeon).",
    )
    parser.add_argument(
        "--attractor-properties-mode",
        choices=["fixed-points", "attractors", "both"],
        default="both",
        help="Property type to generate from attractor summary.",
    )
    parser.add_argument(
        "--include-forbid-extra",
        action="store_true",
        help="Pass --include-forbid-extra to attractors_to_sketch_properties.py.",
    )
    parser.add_argument(
        "--skip-attractor-properties",
        action="store_true",
        help="Skip attractors_to_sketch_properties.py even if attractor summary exists.",
    )
    parser.add_argument(
        "--combined-sketch-output",
        help="Optional output path for final combined sketch (default: outputs/sketch_parts/<bnet_stem>_final_sketch.aeon).",
    )
    parser.add_argument(
        "--skip-combine",
        action="store_true",
        help="Skip combine_sketch_parts.py step.",
    )

    parser.add_argument("--python-cmd", default=sys.executable, help="Python executable to run create_bnet.py.")
    parser.add_argument("--rscript-cmd", default="Rscript", help="Rscript executable to run generate_traces_from_bnet.R.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing them.")

    args = parser.parse_args()

    if args.random and (args.n is None or args.k is None):
        parser.error("--random requires --n and --k.")
    if (args.n is not None or args.k is not None) and not args.random:
        parser.error("--n/--k are only valid with --random.")

    return args


def main() -> None:
    args = parse_args()
    scripts_dir = Path(__file__).resolve().parent
    cwd = Path.cwd()
    bnet_output = resolve_user_path(args.bnet_output, scripts_dir, cwd)
    if bnet_output.suffix.lower() != ".bnet":
        raise SystemExit("--bnet-output must point to a .bnet file.")

    trace_cfg_path = resolve_user_path(args.trace_config, scripts_dir, cwd)
    trace_cfg = read_kv_config(trace_cfg_path)
    trace_output_dir_raw = Path(trace_cfg.get("output_dir", "outputs/traces"))
    if trace_output_dir_raw.is_absolute():
        trace_output_dir = trace_output_dir_raw
    else:
        # Paths in the trace config are interpreted relative to the pipeline root.
        trace_output_dir = (scripts_dir / trace_output_dir_raw).resolve()
    genes_path = trace_output_dir / "genes.txt"
    attractor_summary = trace_output_dir / "attractors_summary.txt"

    default_trace_props = scripts_dir / "outputs" / "sketch_parts" / f"{bnet_output.stem}_trace_properties.aeon"
    default_structure = scripts_dir / "outputs" / "sketch_parts" / f"{bnet_output.stem}_model_part.aeon"
    default_attr_props = scripts_dir / "outputs" / "sketch_parts" / f"{bnet_output.stem}_attractors_properties.aeon"
    default_combined = scripts_dir / "outputs" / "sketch_parts" / f"{bnet_output.stem}_final_sketch.aeon"

    trace_properties_output = (
        resolve_user_path(args.trace_properties_output, scripts_dir, cwd)
        if args.trace_properties_output
        else default_trace_props
    )
    structure_output = (
        resolve_user_path(args.structure_output, scripts_dir, cwd)
        if args.structure_output
        else default_structure
    )
    attractor_properties_output = (
        resolve_user_path(args.attractor_properties_output, scripts_dir, cwd)
        if args.attractor_properties_output
        else default_attr_props
    )
    combined_sketch_output = (
        resolve_user_path(args.combined_sketch_output, scripts_dir, cwd)
        if args.combined_sketch_output
        else default_combined
    )

    create_cmd = build_create_bnet_command(args, scripts_dir)
    trace_cmd = build_trace_command(args, scripts_dir)
    trace_props_cmd = build_trace_properties_command(args, scripts_dir, trace_output_dir, trace_properties_output)
    structure_cmd = build_structure_command(args, scripts_dir, bnet_output, structure_output)
    attractor_cmd = build_attractor_properties_command(
        args, scripts_dir, attractor_summary, attractor_properties_output, genes_path
    )
    combine_from_properties = (
        attractor_properties_output if (not args.skip_attractor_properties and attractor_summary.exists()) else trace_properties_output
    )
    combine_cmd = build_combine_command(
        args,
        scripts_dir,
        combine_from_properties,
        structure_output,
        combined_sketch_output,
    )

    print("Pipeline steps:")
    print(f"1) create .bnet -> {bnet_output}")
    print(f"2) generate traces using config -> {trace_cfg_path}")
    print(f"3) trace properties -> {trace_properties_output}")
    print(f"4) model structure -> {structure_output}")
    if args.skip_attractor_properties:
        print("5) attractor/fixed-point properties -> skipped")
    else:
        print(f"5) attractor/fixed-point properties -> {attractor_properties_output}")
    if args.skip_combine:
        print("6) combine final sketch -> skipped")
    else:
        print(f"6) combine final sketch -> {combined_sketch_output}")

    if args.dry_run:
        print("\nDry run mode (no execution):")
        print(quote_cmd(create_cmd))
        print(quote_cmd(trace_cmd))
        print(quote_cmd(trace_props_cmd))
        print(quote_cmd(structure_cmd))
        if not args.skip_attractor_properties:
            print(quote_cmd(attractor_cmd))
        if not args.skip_combine:
            print(quote_cmd(combine_cmd))
        return

    run_cmd(create_cmd, cwd)
    run_cmd(trace_cmd, cwd)
    run_cmd(trace_props_cmd, cwd)
    run_cmd(structure_cmd, cwd)
    if not args.skip_attractor_properties:
        if attractor_summary.exists():
            run_cmd(attractor_cmd, cwd)
        else:
            print(f"\n[SKIP] Attractor summary not found: {attractor_summary}")
    if not args.skip_combine:
        if not structure_output.exists():
            print(f"\n[SKIP] Structure output not found: {structure_output}")
        elif combine_from_properties.exists():
            run_cmd(combine_cmd, cwd)
        elif trace_properties_output.exists():
            fallback_combine_cmd = build_combine_command(
                args,
                scripts_dir,
                trace_properties_output,
                structure_output,
                combined_sketch_output,
            )
            run_cmd(fallback_combine_cmd, cwd)
        else:
            print(
                f"\n[SKIP] No properties file available for combine step "
                f"({combine_from_properties} and {trace_properties_output} are missing)."
            )
    print("\nPipeline completed successfully.")


if __name__ == "__main__":
    main()
