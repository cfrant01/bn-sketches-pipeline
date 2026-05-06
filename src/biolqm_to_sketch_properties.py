#!/usr/bin/env python3
"""
Convert bioLQM fixpoints and trapspaces outputs into Sketches properties.
"""

from __future__ import annotations

import argparse
import itertools
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple


WILDCARDS = {"-", "*", "?"}
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent if (SCRIPT_DIR.parent / "configs").exists() else SCRIPT_DIR
DEFAULT_BIOLQM_CMD = str(PROJECT_ROOT / "tools" / "bioLQM" / "bioLQM.cmd") if (PROJECT_ROOT / "tools" / "bioLQM" / "bioLQM.cmd").exists() else "bioLQM"


def resolve_user_path(value: str, base_dir: Path, cwd: Path | None = None) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    if cwd is not None:
        candidate = cwd / path
        if candidate.exists():
            return candidate
    return base_dir / path


def resolve_config_value_path(value: str, config_path: Path | None, base_dir: Path, cwd: Path | None = None) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    if cwd is not None:
        return cwd / path
    candidate = base_dir / path
    if candidate.exists() or config_path is None:
        return candidate
    if config_path is not None:
        return config_path.parent / path
    return candidate


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
        key, value = line.split("=", 1)
        cfg[key.strip()] = value.strip()
    return cfg


def cfg_get_bool(cfg: Dict[str, str], key: str, default: bool = False) -> bool:
    if key not in cfg:
        return default
    value = cfg[key].strip().lower()
    if value in {"1", "true", "yes", "y"}:
        return True
    if value in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"Invalid boolean for {key}: {cfg[key]}")


def cfg_get_int(cfg: Dict[str, str], key: str, default: int) -> int:
    if key not in cfg:
        return default
    try:
        return int(cfg[key])
    except ValueError as exc:
        raise ValueError(f"Invalid integer for {key}: {cfg[key]}") from exc


def cfg_get_int_alias(cfg: Dict[str, str], keys: Sequence[str], default: int) -> int:
    for key in keys:
        if key in cfg:
            return cfg_get_int(cfg, key, default)
    return default


def arg_was_passed(flag: str) -> bool:
    import sys

    return flag in sys.argv


def load_lines(path: Path) -> List[str]:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return [line.rstrip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_biolqm_text(text: str, source: str) -> tuple[List[str], List[List[str]]]:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if len(lines) == 1 and lines[0].strip().upper() == "NO RESULTS":
        return [], []
    if len(lines) < 2:
        return [], []

    header = lines[0].split()
    rows: List[List[str]] = []
    for raw in lines[1:]:
        parts = raw.split()
        if len(parts) == 1 and len(parts[0]) == len(header):
            parts = list(parts[0])
        if len(parts) != len(header):
            raise ValueError(f"{source} row has {len(parts)} values, expected {len(header)}: {raw}")
        rows.append(parts)
    return header, rows


def parse_biolqm_table(path: Path) -> tuple[List[str], List[List[str]]]:
    lines = load_lines(path)
    if len(lines) < 2 and not (len(lines) == 1 and lines[0].strip().upper() == "NO RESULTS"):
        raise ValueError(f"{path} does not contain a header and at least one row.")
    return parse_biolqm_text("\n".join(lines), str(path))


def parse_bnet_rules(path: Path) -> tuple[List[str], List[Tuple[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(f".bnet file not found: {path}")
    rules: List[Tuple[str, str]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().replace(" ", "") == "targets,factors":
            continue
        if "," not in line:
            raise ValueError(f"{path}:{line_no} is not a valid .bnet line: {raw}")
        target, expr = line.split(",", 1)
        target = target.strip()
        expr = expr.strip()
        if not target or not expr:
            raise ValueError(f"{path}:{line_no} is not a valid .bnet line: {raw}")
        rules.append((target, expr))
    return [target for target, _ in rules], rules


def write_clamped_bnet(source_rules: Sequence[Tuple[str, str]], assignments: Dict[str, str], output: Path) -> None:
    lines = [
        "# model in BoolNet format",
        "# generated temporary clamped network",
        "",
        "targets, factors",
    ]
    for target, expr in source_rules:
        lines.append(f"{target}, {assignments.get(target, expr)}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def dedup_rows(rows: Sequence[List[str]]) -> List[List[str]]:
    seen = set()
    out: List[List[str]] = []
    for row in rows:
        key = tuple(row)
        if key in seen:
            continue
        seen.add(key)
        out.append(list(row))
    return out


def pattern_to_formula(values: Sequence[str], genes: Sequence[str]) -> str:
    literals: List[str] = []
    for gene, value in zip(genes, values):
        if value in WILDCARDS:
            continue
        if value == "1":
            literals.append(gene)
        elif value == "0":
            literals.append(f"~{gene}")
        else:
            raise ValueError(f"Unsupported pattern value '{value}' for gene '{gene}'.")
    if not literals:
        return "true"
    return "(" + " & ".join(literals) + ")"


def assignment_to_formula(assignments: Dict[str, str]) -> str:
    literals = [gene if value == "1" else f"~{gene}" for gene, value in assignments.items()]
    if not literals:
        return "true"
    return "(" + " & ".join(literals) + ")"


def stable_guard_formula(assignments: Dict[str, str]) -> str:
    return f"AG {assignment_to_formula(assignments)}"


def fixed_point_formula(values: Sequence[str], genes: Sequence[str]) -> str:
    state = pattern_to_formula(values, genes)
    return f"3{{x}}: ( @{{x}}: ( {state} & (AX ({state})) ) )"


def trap_space_formula(values: Sequence[str], genes: Sequence[str]) -> str:
    pattern = pattern_to_formula(values, genes)
    return f"3{{x}}: ( @{{x}}: ( {pattern} & (AG EF ({pattern})) ) )"


def lifted_fixed_point_formula(values: Sequence[str], genes: Sequence[str], assignments: Dict[str, str]) -> str:
    guard = stable_guard_formula(assignments)
    state = pattern_to_formula(values, genes)
    return f"(3{{c}}: (@{{c}}: {guard})) => (3{{x}}: ( @{{x}}: ( ({guard}) & {state} & (AX ({state})) ) ))"


def lifted_trap_space_formula(values: Sequence[str], genes: Sequence[str], assignments: Dict[str, str]) -> str:
    guard = stable_guard_formula(assignments)
    pattern = pattern_to_formula(values, genes)
    return f"(3{{c}}: (@{{c}}: {guard})) => (3{{x}}: ( @{{x}}: ( ({guard}) & {pattern} & (AG EF ({pattern})) ) ))"


def run_biolqm(biolqm_cmd: str, bnet_path: Path, analysis_name: str, cwd: Path, java_cmd: str = "java", biolqm_jar: Path | None = None) -> str:
    if biolqm_jar is not None:
        cmd = [java_cmd, "-jar", str(biolqm_jar), str(bnet_path), "-r", analysis_name]
    else:
        cmd = [biolqm_cmd, str(bnet_path), "-r", analysis_name]
    print("[RUN]", " ".join(f'"{part}"' if " " in part else part for part in cmd))
    result = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
        raise SystemExit(result.returncode)
    return result.stdout


def solve_trapspaces_asp(raw_output: str, python_cmd: str, cwd: Path) -> str:
    lines = [line.rstrip() for line in raw_output.splitlines() if line.strip()]
    if not lines:
        return "NO RESULTS\n"
    header = lines[-1].split()
    if not header:
        return "NO RESULTS\n"

    asp_lines = lines[:-1]
    with tempfile.NamedTemporaryFile("w", suffix=".lp", delete=False, dir=str(cwd), encoding="utf-8") as handle:
        handle.write("\n".join(asp_lines) + "\n")
        asp_path = Path(handle.name)

    try:
        result = subprocess.run(
            [python_cmd, "-m", "clingo", str(asp_path), "0"],
            cwd=str(cwd),
            text=True,
            capture_output=True,
            check=True,
        )
    finally:
        asp_path.unlink(missing_ok=True)

    hit_re = re.compile(r'hit\("([^"]+)",([01])\)')
    rows: List[str] = []
    current_hits: Dict[str, str] | None = None
    for raw in result.stdout.splitlines():
        stripped = raw.strip()
        if stripped.startswith("Answer:"):
            current_hits = {}
            continue
        if current_hits is None:
            continue
        if stripped in {"SATISFIABLE", "UNSATISFIABLE"} or stripped.startswith("Models"):
            if current_hits:
                row = "".join(current_hits.get(gene, "-") for gene in header)
                rows.append(row)
            current_hits = None
            continue
        for gene, value in hit_re.findall(stripped):
            current_hits[gene] = value

    if current_hits:
        row = "".join(current_hits.get(gene, "-") for gene in header)
        rows.append(row)

    if not rows:
        return "NO RESULTS\n"
    return "\n".join([" ".join(header), *rows, ""])


def iter_constant_assignments(genes: Sequence[str], max_clamped: int, limit: int) -> Iterable[Dict[str, str]]:
    emitted = 0
    for width in range(1, max_clamped + 1):
        for selected in itertools.combinations(genes, width):
            for values in itertools.product(["0", "1"], repeat=width):
                if limit > 0 and emitted >= limit:
                    return
                emitted += 1
                yield dict(zip(selected, values))


def assignment_name(assignments: Dict[str, str]) -> str:
    return "_".join(f"{gene}_is_{value}" for gene, value in assignments.items())


def forbid_other_fixed_points_formula(patterns: Sequence[Sequence[str]], genes: Sequence[str]) -> str:
    encoded = [pattern_to_formula(pattern, genes) for pattern in patterns]
    parts = " & ".join(f"~({pattern})" for pattern in encoded)
    return f"~(3{{x}}: (@{{x}}: {parts} & (AX {{x}})))"


def forbid_other_patterns_formula(patterns: Sequence[Sequence[str]], genes: Sequence[str]) -> str:
    encoded = [pattern_to_formula(pattern, genes) for pattern in patterns]
    joined = " | ".join(encoded + ["false"])
    return f"~(3{{x}}: (@{{x}}: ~(AG EF ({joined} ))))"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert bioLQM fixed points and trap spaces into Sketches properties.")
    parser.add_argument("--config", help="Optional key=value config file.")
    parser.add_argument("--fixpoints", help="Raw bioLQM fixpoints output file.")
    parser.add_argument("--trapspaces", help="Raw bioLQM trapspace output file.")
    parser.add_argument("--output", help="Output .aeon properties file.")
    parser.add_argument("--mode", choices=["fixed-points", "trap-spaces", "both"], default="both")
    parser.add_argument("--property-prefix-fixed", default="fixed_point")
    parser.add_argument("--property-prefix-trap", default="trap_space")
    parser.add_argument("--start-index", type=int, default=1)
    parser.add_argument("--include-forbid-extra", action="store_true")
    parser.add_argument("--no-dedup", action="store_true")
    parser.add_argument("--no-properties-header", action="store_true")
    parser.add_argument("--bnet", help="Original .bnet file, required when constant_depth > 1.")
    parser.add_argument(
        "--constant-depth",
        type=int,
        default=1,
        help="Include lifted properties from clamped subnetworks up to this depth. 1 means only the original network.",
    )
    parser.add_argument(
        "--constant-subnetwork-limit",
        type=int,
        default=0,
        help="Maximum number of clamped subnetworks to analyze. 0 means no limit.",
    )
    parser.add_argument("--constant-property-prefix", default="constant", help="Prefix marker for lifted constant-depth properties.")
    parser.add_argument("--biolqm-cmd", default=DEFAULT_BIOLQM_CMD, help="bioLQM executable for constant-depth analyses.")
    parser.add_argument("--java-cmd", default="java", help="Java executable used with --biolqm-jar.")
    parser.add_argument("--biolqm-jar", help="Optional path to bioLQM.jar.")
    parser.add_argument("--python-cmd", default=sys.executable, help="Python executable used for the clingo fallback.")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    base_dir = script_dir.parent if (script_dir.parent / "configs").exists() else script_dir
    cwd = Path.cwd()
    config_path = resolve_user_path(args.config, base_dir, cwd) if args.config else None
    cfg = read_kv_config(config_path) if config_path else {}
    args.config_path = config_path

    args.fixpoints = args.fixpoints or cfg.get("fixpoints")
    args.trapspaces = args.trapspaces or cfg.get("trapspaces")
    args.output = args.output or cfg.get("output")
    args.bnet = args.bnet or cfg.get("bnet")
    if args.mode == "both" and "mode" in cfg and not arg_was_passed("--mode"):
        args.mode = cfg["mode"]
    if not arg_was_passed("--property-prefix-fixed"):
        args.property_prefix_fixed = cfg.get("property_prefix_fixed", args.property_prefix_fixed)
    if not arg_was_passed("--property-prefix-trap"):
        args.property_prefix_trap = cfg.get("property_prefix_trap", args.property_prefix_trap)
    if not arg_was_passed("--start-index"):
        args.start_index = int(cfg.get("start_index", args.start_index))
    if args.config:
        args.include_forbid_extra = args.include_forbid_extra or cfg_get_bool(cfg, "include_forbid_extra", False)
        args.no_dedup = args.no_dedup or cfg_get_bool(cfg, "no_dedup", False)
        args.no_properties_header = args.no_properties_header or cfg_get_bool(cfg, "no_properties_header", False)
    if not arg_was_passed("--constant-depth"):
        args.constant_depth = cfg_get_int_alias(cfg, ["constant_depth", "constantdepth"], args.constant_depth)
    if not arg_was_passed("--constant-subnetwork-limit"):
        args.constant_subnetwork_limit = cfg_get_int_alias(
            cfg,
            ["constant_subnetwork_limit", "constant_limit", "constantlimit"],
            args.constant_subnetwork_limit,
        )
    if not arg_was_passed("--constant-property-prefix"):
        args.constant_property_prefix = cfg.get("constant_property_prefix", args.constant_property_prefix)
    if not arg_was_passed("--biolqm-cmd"):
        args.biolqm_cmd = cfg.get("biolqm_cmd", args.biolqm_cmd)
    if not arg_was_passed("--java-cmd"):
        args.java_cmd = cfg.get("java_cmd", args.java_cmd)
    args.biolqm_jar = args.biolqm_jar or cfg.get("biolqm_jar")

    if not args.output:
        parser.error("Provide --output or set output in --config.")
    if args.constant_depth < 1:
        parser.error("constant_depth must be at least 1.")
    if args.constant_subnetwork_limit < 0:
        parser.error("constant_subnetwork_limit must be at least 0.")
    if args.constant_depth > 1 and not args.bnet:
        parser.error("Set bnet in the config or pass --bnet when constant_depth > 1.")
    if args.mode in {"fixed-points", "both"} and not args.fixpoints:
        parser.error("Provide --fixpoints or set fixpoints in --config.")
    if args.mode in {"trap-spaces", "both"} and not args.trapspaces:
        parser.error("Provide --trapspaces or set trapspaces in --config.")

    return args


def main() -> None:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    base_dir = script_dir.parent if (script_dir.parent / "configs").exists() else script_dir
    cwd = Path.cwd()
    config_path = getattr(args, "config_path", None)
    output_path = resolve_config_value_path(args.output, config_path, base_dir, cwd)

    fixpoint_header: List[str] | None = None
    fixpoint_rows: List[List[str]] = []
    trap_header: List[str] | None = None
    trap_rows: List[List[str]] = []

    if args.mode in {"fixed-points", "both"}:
        fixpoint_header, fixpoint_rows = parse_biolqm_table(
            resolve_config_value_path(args.fixpoints, config_path, base_dir, cwd)
        )
        if not args.no_dedup:
            fixpoint_rows = dedup_rows(fixpoint_rows)
    if args.mode in {"trap-spaces", "both"}:
        trap_header, trap_rows = parse_biolqm_table(
            resolve_config_value_path(args.trapspaces, config_path, base_dir, cwd)
        )
        if not args.no_dedup:
            trap_rows = dedup_rows(trap_rows)

    if fixpoint_header and trap_header and fixpoint_header != trap_header:
        raise ValueError("bioLQM fixpoints and trapspaces headers differ; cannot combine outputs safely.")

    genes = fixpoint_header or trap_header
    if genes is None:
        raise ValueError("No bioLQM results were loaded.")

    lines: List[str] = []
    if not args.no_properties_header:
        lines.append("## PROPERTIES")
    lines.extend(
        [
            "# Generated from bioLQM outputs",
            f"# Genes ({len(genes)}): {' '.join(genes)}",
            f"# Fixed points: {len(fixpoint_rows)}",
            f"# Trap spaces: {len(trap_rows)}",
            f"# Mode: {args.mode}",
        ]
    )

    next_idx = int(args.start_index)
    if args.mode in {"fixed-points", "both"}:
        for row in fixpoint_rows:
            formula = fixed_point_formula(row, genes)
            lines.append(f"#! dynamic_property: {args.property_prefix_fixed}_{next_idx}: #`{formula}`#")
            next_idx += 1
        if args.include_forbid_extra and fixpoint_rows:
            formula = forbid_other_fixed_points_formula(fixpoint_rows, genes)
            lines.append(f"#! dynamic_property: {args.property_prefix_fixed}_forbid_extra: #`{formula}`#")

    if args.mode in {"trap-spaces", "both"}:
        for row in trap_rows:
            formula = trap_space_formula(row, genes)
            lines.append(f"#! dynamic_property: {args.property_prefix_trap}_{next_idx}: #`{formula}`#")
            next_idx += 1
        if args.include_forbid_extra and trap_rows:
            formula = forbid_other_patterns_formula(trap_rows, genes)
            lines.append(f"#! dynamic_property: {args.property_prefix_trap}_forbid_extra: #`{formula}`#")

    if args.constant_depth > 1:
        bnet_path = resolve_config_value_path(args.bnet, config_path, base_dir, cwd)
        bnet_genes, bnet_rules = parse_bnet_rules(bnet_path)
        if genes is not None and bnet_genes != genes:
            raise ValueError("bioLQM output genes and .bnet target order differ; cannot add constant-depth properties safely.")

        biolqm_jar = (
            resolve_config_value_path(args.biolqm_jar, config_path, base_dir, cwd)
            if args.biolqm_jar
            else None
        )
        biolqm_cmd = str(args.biolqm_cmd)
        maybe_biolqm_cmd = Path(biolqm_cmd)
        if biolqm_jar is None and (maybe_biolqm_cmd.is_absolute() or any(sep in biolqm_cmd for sep in ("\\", "/"))):
            biolqm_cmd = str(resolve_config_value_path(biolqm_cmd, config_path, base_dir, cwd))

        max_clamped = min(args.constant_depth - 1, len(bnet_genes))
        constant_networks = 0
        constant_fixed = 0
        constant_traps = 0
        tmp_path = output_path.parent.parent / "dynamics" / "constant_depth_tmp"
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        try:
            for assignments in iter_constant_assignments(bnet_genes, max_clamped, args.constant_subnetwork_limit):
                constant_networks += 1
                name = assignment_name(assignments)
                clamped_bnet = tmp_path / f"{name}.bnet"
                write_clamped_bnet(bnet_rules, assignments, clamped_bnet)

                if args.mode in {"fixed-points", "both"}:
                    raw_fixpoints = run_biolqm(
                        biolqm_cmd,
                        clamped_bnet,
                        "fixpoints",
                        cwd,
                        java_cmd=args.java_cmd,
                        biolqm_jar=biolqm_jar,
                    )
                    clamped_header, clamped_rows = parse_biolqm_text(raw_fixpoints, f"{name} fixpoints")
                    if clamped_header and clamped_header != bnet_genes:
                        raise ValueError(f"{name} fixpoint genes differ from .bnet target order.")
                    if not args.no_dedup:
                        clamped_rows = dedup_rows(clamped_rows)
                    for idx, row in enumerate(clamped_rows, start=1):
                        formula = lifted_fixed_point_formula(row, bnet_genes, assignments)
                        lines.append(
                            f"#! dynamic_property: {args.constant_property_prefix}_{name}_fixed_point_{idx}: #`{formula}`#"
                        )
                        constant_fixed += 1

                if args.mode in {"trap-spaces", "both"}:
                    raw_traps = run_biolqm(
                        biolqm_cmd,
                        clamped_bnet,
                        "trapspaces",
                        cwd,
                        java_cmd=args.java_cmd,
                        biolqm_jar=biolqm_jar,
                    )
                    if "% Clingo not found" in raw_traps:
                        raw_traps = solve_trapspaces_asp(raw_traps, args.python_cmd, cwd)
                    clamped_header, clamped_rows = parse_biolqm_text(raw_traps, f"{name} trapspaces")
                    if clamped_header and clamped_header != bnet_genes:
                        raise ValueError(f"{name} trapspace genes differ from .bnet target order.")
                    if not args.no_dedup:
                        clamped_rows = dedup_rows(clamped_rows)
                    for idx, row in enumerate(clamped_rows, start=1):
                        formula = lifted_trap_space_formula(row, bnet_genes, assignments)
                        lines.append(
                            f"#! dynamic_property: {args.constant_property_prefix}_{name}_trap_space_{idx}: #`{formula}`#"
                        )
                        constant_traps += 1
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)

        lines.extend(
            [
                f"# Constant-depth subnetworks analyzed: {constant_networks}",
                f"# Constant-depth fixed-point properties: {constant_fixed}",
                f"# Constant-depth trap-space properties: {constant_traps}",
            ]
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
