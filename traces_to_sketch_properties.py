#!/usr/bin/env python3
"""
Convert BoolNet trace files into Sketches dynamic reachability properties.

This script generates only the "PROPERTIES" part of a sketch, i.e. lines like:
#! dynamic_property: reachability_1: #`3{x}: ( @{x}: ( (<state_a>) & EF(<state_b>) ) )`#

It is intended to consume traces produced by `generate_traces_from_bnet.R`.

Examples:
    python traces_to_sketch_properties.py --config configs/traces_to_sketch_properties_params.txt
    python traces_to_sketch_properties.py --config configs/traces_to_sketch_properties_params.txt --pair-mode chain
    python traces_to_sketch_properties.py --config configs/traces_to_sketch_properties_params.txt --keep-percent 50 --seed 42
"""

from __future__ import annotations

import argparse
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple


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


def cfg_get_float(cfg: dict[str, str], key: str, default: float | None = None) -> float | None:
    if key not in cfg:
        return default
    return float(cfg[key])


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


def resolve_user_path(value: str, base_dir: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return base_dir / path


@dataclass(frozen=True)
class Transition:
    trace_name: str
    from_index: int
    to_index: int
    from_state: Tuple[int, ...]
    to_state: Tuple[int, ...]


@dataclass(frozen=True)
class TraceChain:
    trace_name: str
    states: Tuple[Tuple[int, ...], ...]


def load_genes(genes_path: Path) -> List[str]:
    if not genes_path.exists():
        raise FileNotFoundError(f"Genes file not found: {genes_path}")

    genes = [line.strip() for line in genes_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not genes:
        raise ValueError(f"No genes found in {genes_path}")
    return genes


def parse_trace_line(line: str, genes_count: int, path: Path, line_number: int) -> Tuple[int, ...] | None:
    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith(">"):
        return None

    parts = [p for p in TRACE_LINE_SPLIT_RE.split(stripped) if p]
    if len(parts) != genes_count:
        raise ValueError(
            f"{path}:{line_number} has {len(parts)} values, expected {genes_count} (genes.txt order)."
        )

    state: List[int] = []
    for token in parts:
        if token not in {"0", "1"}:
            raise ValueError(f"{path}:{line_number} contains non-binary value '{token}'.")
        state.append(int(token))
    return tuple(state)


def load_trace_states(trace_path: Path, genes_count: int) -> List[Tuple[int, ...]]:
    states: List[Tuple[int, ...]] = []
    for line_number, raw in enumerate(trace_path.read_text(encoding="utf-8").splitlines(), start=1):
        parsed = parse_trace_line(raw, genes_count, trace_path, line_number)
        if parsed is not None:
            states.append(parsed)
    if len(states) < 2:
        raise ValueError(f"Trace file {trace_path} needs at least 2 states to create reachability properties.")
    return states


def discover_trace_files(traces_dir: Path, trace_glob: str) -> List[Path]:
    if not traces_dir.exists():
        raise FileNotFoundError(f"Traces directory not found: {traces_dir}")
    if not traces_dir.is_dir():
        raise NotADirectoryError(f"Expected a directory for --traces-dir: {traces_dir}")

    files = sorted(p for p in traces_dir.glob(trace_glob) if p.is_file())
    if not files:
        raise ValueError(f"No trace files matched '{trace_glob}' in {traces_dir}")
    return files


def build_transitions(
    trace_files: Sequence[Path],
    genes_count: int,
    pair_mode: str,
) -> List[Transition]:
    transitions: List[Transition] = []

    for trace_file in trace_files:
        states = load_trace_states(trace_file, genes_count)
        if pair_mode == "consecutive":
            pairs = [(i, i + 1) for i in range(len(states) - 1)]
        elif pair_mode == "all_pairs":
            pairs = [(i, j) for i in range(len(states) - 1) for j in range(i + 1, len(states))]
        else:
            raise ValueError(f"Unsupported pair mode: {pair_mode}")

        for i, j in pairs:
            transitions.append(
                Transition(
                    trace_name=trace_file.name,
                    from_index=i,
                    to_index=j,
                    from_state=states[i],
                    to_state=states[j],
                )
            )

    return transitions


def build_trace_chains(trace_files: Sequence[Path], genes_count: int) -> List[TraceChain]:
    chains: List[TraceChain] = []
    for trace_file in trace_files:
        states = load_trace_states(trace_file, genes_count)
        chains.append(TraceChain(trace_name=trace_file.name, states=tuple(states)))
    return chains


def state_to_hctl_formula(state: Sequence[int], genes: Sequence[str]) -> str:
    if len(state) != len(genes):
        raise ValueError("State length does not match genes length.")
    literals = [gene if bit == 1 else f"~{gene}" for gene, bit in zip(genes, state)]
    return "(" + " & ".join(literals) + ")"


def transition_to_property_line(
    transition: Transition,
    genes: Sequence[str],
    property_name: str,
) -> str:
    from_state = state_to_hctl_formula(transition.from_state, genes)
    to_state = state_to_hctl_formula(transition.to_state, genes)
    formula = f"3{{x}}: ( @{{x}}: ( {from_state} & EF({to_state}) ) )"
    return f"#! dynamic_property: {property_name}: #`{formula}`#"


def chain_to_formula(states: Sequence[Tuple[int, ...]], genes: Sequence[str]) -> str:
    if len(states) < 2:
        raise ValueError("Trace chain needs at least 2 states.")
    encoded = [state_to_hctl_formula(state, genes) for state in states]
    inner = encoded[-1]
    for state in reversed(encoded[:-1]):
        inner = f"{state} & EF({inner})"
    return f"3{{x}}: ( @{{x}}: ( {inner} ) )"


def chain_to_property_line(chain: TraceChain, genes: Sequence[str], property_name: str) -> str:
    formula = chain_to_formula(chain.states, genes)
    return f"#! dynamic_property: {property_name}: #`{formula}`#"


def deduplicate_transitions(transitions: Iterable[Transition]) -> List[Transition]:
    seen: set[Tuple[Tuple[int, ...], Tuple[int, ...]]] = set()
    unique: List[Transition] = []
    for t in transitions:
        key = (t.from_state, t.to_state)
        if key in seen:
            continue
        seen.add(key)
        unique.append(t)
    return unique


def deduplicate_chains(chains: Iterable[TraceChain]) -> List[TraceChain]:
    seen: set[Tuple[Tuple[int, ...], ...]] = set()
    unique: List[TraceChain] = []
    for chain in chains:
        key = chain.states
        if key in seen:
            continue
        seen.add(key)
        unique.append(chain)
    return unique


def sample_transitions(
    transitions: List[Transition],
    keep_percent: float,
    seed: int | None,
) -> List[Transition]:
    if not (0 <= keep_percent <= 100):
        raise ValueError("--keep-percent must be between 0 and 100.")
    if keep_percent == 100:
        return transitions
    if keep_percent == 0:
        return []

    n_total = len(transitions)
    n_keep = int(round(n_total * keep_percent / 100.0))
    n_keep = max(0, min(n_total, n_keep))
    if n_keep == n_total:
        return transitions
    if n_keep == 0:
        return []

    rng = random.Random(seed)
    selected_indices = sorted(rng.sample(range(n_total), n_keep))
    return [transitions[i] for i in selected_indices]


def write_properties_file(
    output_path: Path,
    properties: List[str],
    metadata_lines: List[str],
    include_header: bool,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    if include_header:
        lines.append("## PROPERTIES")
    lines.extend(metadata_lines)
    lines.extend(properties)
    output_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create Sketches dynamic reachability properties from trace files."
    )
    parser.add_argument("--config", help="Parameter file (key = value). Recommended.")
    parser.add_argument("--traces-dir", help="Directory containing trace files and usually genes.txt.")
    parser.add_argument("--output", help="Output file for the generated properties snippet.")
    parser.add_argument("--genes", help="Path to genes.txt (defaults to <traces-dir>/genes.txt).")
    parser.add_argument(
        "--trace-glob",
        default="experiment*.txt",
        help="Glob pattern for trace files inside --traces-dir (default: experiment*.txt).",
    )
    parser.add_argument(
        "--pair-mode",
        choices=["consecutive", "all_pairs", "chain"],
        default="consecutive",
        help="consecutive = one property per adjacent states; all_pairs = one property per i<j pair in each trace; chain = one ordered reachability-chain property per trace.",
    )
    parser.add_argument(
        "--keep-percent",
        type=float,
        default=100.0,
        help="Percentage of generated (unique) properties to keep, e.g. 50 for half.",
    )
    parser.add_argument("--seed", type=int, help="Random seed for reproducible sampling when keep-percent < 100.")
    parser.add_argument(
        "--no-dedup",
        action="store_true",
        help="Keep duplicate reachability properties (duplicates are otherwise removed).",
    )
    parser.add_argument(
        "--property-prefix",
        default="reachability",
        help="Prefix for property names (default: reachability -> reachability_1, ...).",
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=1,
        help="Starting index for property numbering (default: 1).",
    )
    parser.add_argument(
        "--no-properties-header",
        action="store_true",
        help="Do not write the '## PROPERTIES' header line.",
    )
    return parser


def main() -> None:
    parser = build_argument_parser()
    args = parser.parse_args()
    base_dir = Path(__file__).resolve().parent
    cfg = read_kv_config(Path(args.config)) if args.config else {}

    traces_dir_value = args.traces_dir or cfg_get_str(cfg, "traces_dir")
    output_value = args.output or cfg_get_str(cfg, "output")
    if not traces_dir_value or not output_value:
        parser.error("Provide --config with traces_dir/output keys, or pass --traces-dir and --output.")

    traces_dir = resolve_user_path(traces_dir_value, base_dir)
    genes_value = (
        args.genes if arg_was_passed("--genes") else cfg_get_str(cfg, "genes", args.genes)
    )
    genes_path = resolve_user_path(genes_value, base_dir) if genes_value else (traces_dir / "genes.txt")
    output_path = resolve_user_path(output_value, base_dir)
    trace_glob = args.trace_glob if arg_was_passed("--trace-glob") else cfg_get_str(cfg, "trace_glob", args.trace_glob)
    pair_mode = args.pair_mode if arg_was_passed("--pair-mode") else cfg_get_str(cfg, "pair_mode", args.pair_mode)
    keep_percent = (
        args.keep_percent if arg_was_passed("--keep-percent") else cfg_get_float(cfg, "keep_percent", args.keep_percent)
    )
    seed = args.seed if args.seed is not None else cfg_get_int(cfg, "seed", None)
    no_dedup = args.no_dedup if arg_was_passed("--no-dedup") else cfg_get_bool(cfg, "no_dedup", args.no_dedup)
    property_prefix = (
        args.property_prefix if arg_was_passed("--property-prefix") else cfg_get_str(cfg, "property_prefix", args.property_prefix)
    )
    start_index = args.start_index if arg_was_passed("--start-index") else cfg_get_int(cfg, "start_index", args.start_index)
    no_properties_header = (
        args.no_properties_header
        if arg_was_passed("--no-properties-header")
        else cfg_get_bool(cfg, "no_properties_header", args.no_properties_header)
    )

    genes = load_genes(genes_path)
    trace_files = discover_trace_files(traces_dir, str(trace_glob))
    raw_count = 0
    unique_count = 0
    selected_transitions: List[Transition] = []
    selected_chains: List[TraceChain] = []

    if pair_mode == "chain":
        chains = build_trace_chains(trace_files, genes_count=len(genes))
        raw_count = len(chains)
        if not no_dedup:
            chains = deduplicate_chains(chains)
        unique_count = len(chains)
        selected_chains = sample_transitions(chains, keep_percent=float(keep_percent), seed=seed)  # type: ignore[arg-type]
    else:
        transitions = build_transitions(trace_files, genes_count=len(genes), pair_mode=str(pair_mode))
        raw_count = len(transitions)
        if not no_dedup:
            transitions = deduplicate_transitions(transitions)
        unique_count = len(transitions)
        selected_transitions = sample_transitions(transitions, keep_percent=float(keep_percent), seed=seed)

    if int(start_index) < 0:
        raise ValueError("--start-index must be >= 0")

    properties: List[str] = []
    if pair_mode == "chain":
        for idx, chain in enumerate(selected_chains, start=int(start_index)):
            prop_name = f"{property_prefix}_{idx}"
            properties.append(chain_to_property_line(chain, genes, prop_name))
    else:
        for idx, transition in enumerate(selected_transitions, start=int(start_index)):
            prop_name = f"{property_prefix}_{idx}"
            properties.append(transition_to_property_line(transition, genes, prop_name))

    metadata = [
        f"# Generated from traces in: {traces_dir}",
        f"# Genes file: {genes_path}",
        f"# Trace files matched: {len(trace_files)} ({trace_glob})",
        f"# Pair mode: {pair_mode}",
        f"# Raw transitions: {raw_count}",
        f"# After dedup: {unique_count}" if not no_dedup else f"# Duplicates kept: {unique_count}",
        f"# keep_percent: {keep_percent}",
        f"# Final properties written: {len(properties)}",
    ]
    if seed is not None:
        metadata.append(f"# seed: {seed}")

    write_properties_file(
        output_path=output_path,
        properties=properties,
        metadata_lines=metadata,
        include_header=not no_properties_header,
    )

    print(f"Genes loaded: {len(genes)}")
    print(f"Trace files: {len(trace_files)}")
    print(f"Raw transitions: {raw_count}")
    if not no_dedup:
        print(f"Unique transitions: {unique_count}")
    print(f"Properties written: {len(properties)}")
    print(f"Output: {output_path}")
    if pair_mode == "all_pairs":
        print("Note: all_pairs is still finite for finite traces (it uses all i<j state pairs in each trace).")
    if pair_mode == "chain":
        print("Note: chain mode generates one ordered reachability-chain property per trace.")


if __name__ == "__main__":
    main()
