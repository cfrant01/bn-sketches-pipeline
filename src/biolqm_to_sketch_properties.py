#!/usr/bin/env python3
"""
Convert bioLQM fixpoints and trapspaces outputs into Sketches properties.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Sequence


WILDCARDS = {"-", "*", "?"}


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


def arg_was_passed(flag: str) -> bool:
    import sys

    return flag in sys.argv


def load_lines(path: Path) -> List[str]:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return [line.rstrip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_biolqm_table(path: Path) -> tuple[List[str], List[List[str]]]:
    lines = load_lines(path)
    if len(lines) == 1 and lines[0].strip().upper() == "NO RESULTS":
        return [], []
    if len(lines) < 2:
        raise ValueError(f"{path} does not contain a header and at least one row.")

    header = lines[0].split()
    rows: List[List[str]] = []
    for raw in lines[1:]:
        parts = raw.split()
        if len(parts) == 1 and len(parts[0]) == len(header):
            parts = list(parts[0])
        if len(parts) != len(header):
            raise ValueError(f"{path} row has {len(parts)} values, expected {len(header)}: {raw}")
        rows.append(parts)
    return header, rows


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


def fixed_point_formula(values: Sequence[str], genes: Sequence[str]) -> str:
    state = pattern_to_formula(values, genes)
    return f"3{{x}}: ( @{{x}}: ( {state} & (AX ({state})) ) )"


def trap_space_formula(values: Sequence[str], genes: Sequence[str]) -> str:
    pattern = pattern_to_formula(values, genes)
    return f"3{{x}}: ( @{{x}}: ( {pattern} & (AG EF ({pattern})) ) )"


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

    if not args.output:
        parser.error("Provide --output or set output in --config.")
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

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
