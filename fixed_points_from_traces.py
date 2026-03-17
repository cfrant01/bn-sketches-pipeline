#!/usr/bin/env python3
"""
Generate fixed-point dynamic properties directly from traces.

Detection rule:
- if the last `min_stable_length` states of a trace are identical,
  the repeated terminal state is treated as a fixed-point candidate.

Supports parameter files (`key = value`) like the other generators.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Sequence, Tuple


TRACE_LINE_SPLIT_RE = re.compile(r"[\t ,;]+")


def read_kv_config(path: Path) -> dict[str, str]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    cfg: dict[str, str] = {}
    for idx, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = re.sub(r"#.*$", "", raw).strip()
        if not line:
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{idx} invalid config line (expected key = value): {raw}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or value == "":
            raise ValueError(f"{path}:{idx} invalid config line: {raw}")
        cfg[key] = value
    return cfg


def cfg_get_str(cfg: dict[str, str], key: str, default: str | None = None) -> str | None:
    return cfg.get(key, default)


def cfg_get_int(cfg: dict[str, str], key: str, default: int | None = None) -> int | None:
    if key not in cfg:
        return default
    return int(cfg[key])


def cfg_get_bool(cfg: dict[str, str], key: str, default: bool = False) -> bool:
    if key not in cfg:
        return default
    val = cfg[key].strip().lower()
    if val in {"1", "true", "yes", "y"}:
        return True
    if val in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"Invalid boolean for {key}: {cfg[key]}")


def arg_was_passed(flag: str) -> bool:
    return flag in sys.argv


def resolve_user_path(value: str, base_dir: Path, cwd: Path | None = None) -> Path:
    p = Path(value)
    if p.is_absolute():
        return p
    if cwd is not None:
        candidate = cwd / p
        if candidate.exists():
            return candidate
    return base_dir / p


def load_genes(path: Path) -> List[str]:
    genes = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not genes:
        raise ValueError(f"No genes found in {path}")
    return genes


def parse_trace_line(line: str, genes_count: int, path: Path, line_number: int) -> Tuple[int, ...] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith(">"):
        return None
    parts = [p for p in TRACE_LINE_SPLIT_RE.split(stripped) if p]
    if len(parts) != genes_count:
        raise ValueError(f"{path}:{line_number} has {len(parts)} values, expected {genes_count}.")
    values: List[int] = []
    for token in parts:
        if token not in {"0", "1"}:
            raise ValueError(f"{path}:{line_number} contains non-binary value '{token}'.")
        values.append(int(token))
    return tuple(values)


def load_trace_states(trace_path: Path, genes_count: int) -> List[Tuple[int, ...]]:
    states: List[Tuple[int, ...]] = []
    for line_no, raw in enumerate(trace_path.read_text(encoding="utf-8").splitlines(), start=1):
        state = parse_trace_line(raw, genes_count, trace_path, line_no)
        if state is not None:
            states.append(state)
    if len(states) < 2:
        raise ValueError(f"Trace file {trace_path} needs at least 2 states.")
    return states


def discover_trace_files(traces_dir: Path, trace_glob: str) -> List[Path]:
    files = sorted(p for p in traces_dir.glob(trace_glob) if p.is_file())
    if not files:
        raise ValueError(f"No trace files matched '{trace_glob}' in {traces_dir}")
    return files


def state_to_formula(state: Sequence[int], genes: Sequence[str]) -> str:
    lits = [gene if bit == 1 else f"~{gene}" for gene, bit in zip(genes, state)]
    return "(" + " & ".join(lits) + ")"


def fixed_point_formula(state: Sequence[int], genes: Sequence[str]) -> str:
    s = state_to_formula(state, genes)
    return f"3{{x}}: ( @{{x}}: ( {s} & (AX ({s})) ) )"


def forbid_other_fixed_points_formula(states: Sequence[Tuple[int, ...]], genes: Sequence[str]) -> str:
    encoded = [state_to_formula(state, genes) for state in states]
    parts = " & ".join(f"~({s})" for s in encoded)
    return f"~(3{{x}}: (@{{x}}: {parts} & (AX {{x}})))"


def detect_fixed_points(
    trace_files: Sequence[Path],
    genes_count: int,
    min_stable_length: int,
) -> List[Tuple[int, ...]]:
    detected: List[Tuple[int, ...]] = []
    for trace_file in trace_files:
        states = load_trace_states(trace_file, genes_count)
        if len(states) < min_stable_length:
            continue
        suffix = states[-min_stable_length:]
        if all(state == suffix[0] for state in suffix):
            detected.append(suffix[0])
    return detected


def dedup_states(states: Sequence[Tuple[int, ...]]) -> List[Tuple[int, ...]]:
    seen = set()
    unique: List[Tuple[int, ...]] = []
    for state in states:
        if state in seen:
            continue
        seen.add(state)
        unique.append(state)
    return unique


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate fixed-point properties directly from traces.")
    parser.add_argument("--config", help="Parameter file (key = value). Recommended.")
    parser.add_argument("--traces-dir", help="Directory containing trace files and genes.txt.")
    parser.add_argument("--output", help="Output .aeon snippet file.")
    parser.add_argument("--genes", help="Optional explicit genes.txt path.")
    parser.add_argument("--trace-glob", default="experiment*.txt")
    parser.add_argument("--min-stable-length", type=int, default=2)
    parser.add_argument("--property-prefix", default="fixed_point")
    parser.add_argument("--start-index", type=int, default=1)
    parser.add_argument("--include-forbid-extra", action="store_true")
    parser.add_argument("--no-dedup", action="store_true")
    parser.add_argument("--no-properties-header", action="store_true")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    cwd = Path.cwd()
    cfg = read_kv_config(resolve_user_path(args.config, base_dir, cwd)) if args.config else {}

    traces_dir_value = args.traces_dir or cfg_get_str(cfg, "traces_dir")
    output_value = args.output or cfg_get_str(cfg, "output")
    if not traces_dir_value or not output_value:
        parser.error("Provide --config with traces_dir/output keys, or pass --traces-dir and --output.")

    traces_dir = resolve_user_path(traces_dir_value, base_dir, cwd)
    genes_value = args.genes if arg_was_passed("--genes") else cfg_get_str(cfg, "genes", args.genes)
    genes_path = resolve_user_path(genes_value, base_dir, cwd) if genes_value else (traces_dir / "genes.txt")
    trace_glob = args.trace_glob if arg_was_passed("--trace-glob") else cfg_get_str(cfg, "trace_glob", args.trace_glob)
    min_stable_length = (
        args.min_stable_length
        if arg_was_passed("--min-stable-length")
        else cfg_get_int(cfg, "min_stable_length", args.min_stable_length)
    )
    property_prefix = (
        args.property_prefix if arg_was_passed("--property-prefix") else cfg_get_str(cfg, "property_prefix", args.property_prefix)
    )
    start_index = args.start_index if arg_was_passed("--start-index") else cfg_get_int(cfg, "start_index", args.start_index)
    include_forbid_extra = (
        args.include_forbid_extra
        if arg_was_passed("--include-forbid-extra")
        else cfg_get_bool(cfg, "include_forbid_extra", args.include_forbid_extra)
    )
    no_dedup = args.no_dedup if arg_was_passed("--no-dedup") else cfg_get_bool(cfg, "no_dedup", args.no_dedup)
    no_properties_header = (
        args.no_properties_header
        if arg_was_passed("--no-properties-header")
        else cfg_get_bool(cfg, "no_properties_header", args.no_properties_header)
    )
    output_path = resolve_user_path(output_value, base_dir, cwd)

    genes = load_genes(genes_path)
    trace_files = discover_trace_files(traces_dir, str(trace_glob))
    fixed_points = detect_fixed_points(trace_files, len(genes), int(min_stable_length))
    raw_count = len(fixed_points)
    if not no_dedup:
        fixed_points = dedup_states(fixed_points)

    lines: List[str] = []
    if not no_properties_header:
        lines.append("## PROPERTIES")
    lines.extend(
        [
            f"# Generated from traces in: {traces_dir}",
            f"# Genes file: {genes_path}",
            f"# Trace files matched: {len(trace_files)} ({trace_glob})",
            f"# min_stable_length: {min_stable_length}",
            f"# Raw fixed-point candidates: {raw_count}",
            f"# Final fixed-point properties: {len(fixed_points)}",
        ]
    )
    for idx, state in enumerate(fixed_points, start=int(start_index)):
        formula = fixed_point_formula(state, genes)
        lines.append(f"#! dynamic_property: {property_prefix}_{idx}: #`{formula}`#")

    if include_forbid_extra and fixed_points:
        formula = forbid_other_fixed_points_formula(fixed_points, genes)
        lines.append(f"#! dynamic_property: {property_prefix}_forbid_extra: #`{formula}`#")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Trace files: {len(trace_files)}")
    print(f"Raw fixed-point candidates: {raw_count}")
    if not no_dedup:
        print(f"Unique fixed points: {len(fixed_points)}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
