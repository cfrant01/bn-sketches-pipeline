#!/usr/bin/env python3
"""
Convert BoolNet trace files into Sketches dynamic reachability properties.

This script generates only the "PROPERTIES" part of a sketch, i.e. lines like:
#! dynamic_property: reachability_1: #`3{x}: ( @{x}: ( (<state_a>) & EF(<state_b>) ) )`#

It is intended to consume traces produced by `generate_traces_from_bnet.R`.

Examples:
    python traces_to_sketch_properties.py --config configs/trace_properties.txt
    python traces_to_sketch_properties.py --config configs/trace_properties.txt --pair-mode chain
    python traces_to_sketch_properties.py --config configs/trace_properties.txt --keep-percent 50 --seed 42
"""

from __future__ import annotations

import argparse
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple, TypeVar


TRACE_LINE_SPLIT_RE = re.compile(r"[\t ,;]+")
T = TypeVar("T")


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


@dataclass(frozen=True)
class ProjectedTransition:
    from_state: Tuple[int, ...]
    to_state: Tuple[int, ...]
    projected_genes: Tuple[str, ...]


@dataclass(frozen=True)
class TraceSingleton:
    trace_name: str
    state: Tuple[int, ...]


@dataclass(frozen=True)
class TraceCycleCandidate:
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


def compress_stuttering_states(states: Sequence[Tuple[int, ...]]) -> List[Tuple[int, ...]]:
    if not states:
        return []
    compressed = [states[0]]
    for state in states[1:]:
        if state != compressed[-1]:
            compressed.append(state)
    return compressed


def select_milestones(states: Sequence[Tuple[int, ...]], max_states: int) -> List[Tuple[int, ...]]:
    if max_states < 2:
        raise ValueError("max_states must be at least 2.")
    if len(states) <= max_states:
        return list(states)

    indices = {0, len(states) - 1}
    step = (len(states) - 1) / float(max_states - 1)
    for slot in range(1, max_states - 1):
        indices.add(round(slot * step))

    if len(indices) < max_states:
        for idx in range(1, len(states) - 1):
            indices.add(idx)
            if len(indices) == max_states:
                break

    return [states[idx] for idx in sorted(indices)]


def load_trace_states(
    trace_path: Path,
    genes_count: int,
    compress_stutter: bool,
) -> List[Tuple[int, ...]]:
    states: List[Tuple[int, ...]] = []
    for line_number, raw in enumerate(trace_path.read_text(encoding="utf-8").splitlines(), start=1):
        parsed = parse_trace_line(raw, genes_count, trace_path, line_number)
        if parsed is not None:
            states.append(parsed)
    if compress_stutter:
        states = compress_stuttering_states(states)
    if len(states) < 1:
        raise ValueError(f"Trace file {trace_path} does not contain any valid states.")
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
    compress_stutter: bool,
) -> List[Transition]:
    transitions: List[Transition] = []

    for trace_file in trace_files:
        states = load_trace_states(trace_file, genes_count, compress_stutter=compress_stutter)
        if len(states) < 2:
            continue
        if pair_mode == "consecutive":
            pairs = [(i, i + 1) for i in range(len(states) - 1)]
        elif pair_mode == "all_pairs":
            pairs = [(i, j) for i in range(len(states) - 1) for j in range(i + 1, len(states))]
        elif pair_mode == "endpoints":
            pairs = [(0, len(states) - 1)]
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


def build_trace_chains(
    trace_files: Sequence[Path],
    genes_count: int,
    pair_mode: str,
    compress_stutter: bool,
    max_chain_states: int | None,
) -> List[TraceChain]:
    chains: List[TraceChain] = []
    for trace_file in trace_files:
        states = load_trace_states(trace_file, genes_count, compress_stutter=compress_stutter)
        if len(states) < 2:
            continue
        if pair_mode == "milestones":
            limit = max_chain_states if max_chain_states is not None else 6
            states = select_milestones(states, limit)
        elif max_chain_states is not None and len(states) > max_chain_states:
            states = select_milestones(states, max_chain_states)
        chains.append(TraceChain(trace_name=trace_file.name, states=tuple(states)))
    return chains


def build_trace_singletons(
    trace_files: Sequence[Path],
    genes_count: int,
    compress_stutter: bool,
) -> List[TraceSingleton]:
    singletons: List[TraceSingleton] = []
    for trace_file in trace_files:
        states = load_trace_states(trace_file, genes_count, compress_stutter=compress_stutter)
        if len(states) == 1:
            singletons.append(TraceSingleton(trace_name=trace_file.name, state=states[0]))
    return singletons


def detect_tail_cycle(states: Sequence[Tuple[int, ...]], cycle_lengths: Sequence[int]) -> Tuple[Tuple[int, ...], ...] | None:
    for cycle_len in sorted(cycle_lengths):
        if cycle_len < 2 or len(states) < 2 * cycle_len:
            continue
        suffix = tuple(states[-cycle_len:])
        previous = tuple(states[-2 * cycle_len:-cycle_len])
        if suffix == previous and len(set(suffix)) > 1:
            return suffix
    return None


def build_trace_cycle_candidates(
    trace_files: Sequence[Path],
    genes_count: int,
    compress_stutter: bool,
    cycle_lengths: Sequence[int],
) -> List[TraceCycleCandidate]:
    cycles: List[TraceCycleCandidate] = []
    for trace_file in trace_files:
        states = load_trace_states(trace_file, genes_count, compress_stutter=compress_stutter)
        cycle_states = detect_tail_cycle(states, cycle_lengths)
        if cycle_states is not None:
            cycles.append(TraceCycleCandidate(trace_name=trace_file.name, states=cycle_states))
    return cycles


def state_to_hctl_formula(state: Sequence[int], genes: Sequence[str]) -> str:
    if len(state) != len(genes):
        raise ValueError("State length does not match genes length.")
    literals = [gene if bit == 1 else f"~{gene}" for gene, bit in zip(genes, state)]
    return "(" + " & ".join(literals) + ")"


def select_partial_gene_indices(
    trace_files: Sequence[Path],
    genes_count: int,
    compress_stutter: bool,
    partial_state_size: int,
    partial_state_mode: str,
    seed: int | None,
) -> List[int]:
    if partial_state_size <= 0:
        raise ValueError("--partial-state-size must be >= 1.")
    if partial_state_size >= genes_count:
        return list(range(genes_count))

    if partial_state_mode == "first":
        return list(range(partial_state_size))

    if partial_state_mode == "random":
        rng = random.Random(seed)
        return sorted(rng.sample(range(genes_count), partial_state_size))

    if partial_state_mode == "variance":
        counts = [0] * genes_count
        total_states = 0
        for trace_file in trace_files:
            states = load_trace_states(trace_file, genes_count, compress_stutter=compress_stutter)
            for state in states:
                total_states += 1
                for idx, bit in enumerate(state):
                    counts[idx] += bit
        if total_states == 0:
            raise ValueError("No states available to score partial-state genes.")

        scored = []
        for idx, ones in enumerate(counts):
            p = ones / float(total_states)
            variance = p * (1.0 - p)
            scored.append((-variance, idx))
        scored.sort()
        return sorted(idx for _, idx in scored[:partial_state_size])

    raise ValueError(f"Unsupported partial state mode: {partial_state_mode}")


def project_state(state: Sequence[int], genes: Sequence[str], selected_indices: Sequence[int]) -> Tuple[Tuple[int, ...], List[str]]:
    projected_state = tuple(state[idx] for idx in selected_indices)
    projected_genes = [genes[idx] for idx in selected_indices]
    return projected_state, projected_genes


def project_transition(
    transition: Transition,
    genes: Sequence[str],
    selected_indices: Sequence[int],
) -> ProjectedTransition:
    from_bits, projected_genes = project_state(transition.from_state, genes, selected_indices)
    to_bits, _ = project_state(transition.to_state, genes, selected_indices)
    return ProjectedTransition(
        from_state=from_bits,
        to_state=to_bits,
        projected_genes=tuple(projected_genes),
    )


def choose_indices_for_transition(
    transition: Transition,
    genes: Sequence[str],
    partial_state_size: int,
    partial_state_mode: str,
    seed: int | None,
) -> List[int]:
    genes_count = len(genes)
    if partial_state_size >= genes_count:
        return list(range(genes_count))

    if partial_state_mode == "first":
        return list(range(partial_state_size))

    if partial_state_mode == "random":
        base_seed = seed if seed is not None else 0
        rng = random.Random(
            f"{base_seed}:{transition.trace_name}:{transition.from_index}:{transition.to_index}"
        )
        return sorted(rng.sample(range(genes_count), partial_state_size))

    raise ValueError(f"Unsupported per-property partial state mode: {partial_state_mode}")


def transition_to_property_line(
    transition: Transition,
    genes: Sequence[str],
    property_name: str,
    selected_indices: Sequence[int] | None = None,
) -> str:
    if selected_indices is not None:
        from_bits, projected_genes = project_state(transition.from_state, genes, selected_indices)
        to_bits, _ = project_state(transition.to_state, genes, selected_indices)
        from_state = state_to_hctl_formula(from_bits, projected_genes)
        to_state = state_to_hctl_formula(to_bits, projected_genes)
    else:
        from_state = state_to_hctl_formula(transition.from_state, genes)
        to_state = state_to_hctl_formula(transition.to_state, genes)
    formula = f"3{{x}}: ( @{{x}}: ( {from_state} & EF({to_state}) ) )"
    return f"#! dynamic_property: {property_name}: #`{formula}`#"


def singleton_to_property_line(
    singleton: TraceSingleton,
    genes: Sequence[str],
    property_name: str,
    selected_indices: Sequence[int] | None = None,
) -> str:
    if selected_indices is not None:
        state_bits, projected_genes = project_state(singleton.state, genes, selected_indices)
        state_formula = state_to_hctl_formula(state_bits, projected_genes)
    else:
        state_formula = state_to_hctl_formula(singleton.state, genes)
    formula = f"3{{x}}: ( @{{x}}: ( {state_formula} & (AG(EF({state_formula}))) ) )"
    return f"#! dynamic_property: {property_name}: #`{formula}`#"


def cycle_candidate_to_property_line(
    cycle: TraceCycleCandidate,
    genes: Sequence[str],
    property_name: str,
    selected_indices: Sequence[int] | None = None,
) -> str:
    if selected_indices is not None:
        projected_genes = [genes[idx] for idx in selected_indices]
        projected_states = [tuple(state[idx] for idx in selected_indices) for state in cycle.states]
        encoded = [state_to_hctl_formula(state, projected_genes) for state in projected_states]
    else:
        encoded = [state_to_hctl_formula(state, genes) for state in cycle.states]
    inner = encoded[0]
    for state in reversed(encoded[1:]):
        inner = f"{state} & EF({inner})"
    formula = f"3{{x}}: ( @{{x}}: ( {encoded[0]} & EF({inner[len(encoded[0]) + 5:] if inner.startswith(encoded[0] + ' & EF(') else inner}) ) )"
    return f"#! dynamic_property: {property_name}: #`{formula}`#"


def chain_to_formula(states: Sequence[Tuple[int, ...]], genes: Sequence[str]) -> str:
    if len(states) < 2:
        raise ValueError("Trace chain needs at least 2 states.")
    encoded = [state_to_hctl_formula(state, genes) for state in states]
    inner = encoded[-1]
    for state in reversed(encoded[:-1]):
        inner = f"{state} & EF({inner})"
    return f"3{{x}}: ( @{{x}}: ( {inner} ) )"


def chain_to_property_line(
    chain: TraceChain,
    genes: Sequence[str],
    property_name: str,
    selected_indices: Sequence[int] | None = None,
) -> str:
    if selected_indices is not None:
        projected_genes = [genes[idx] for idx in selected_indices]
        projected_states = [tuple(state[idx] for idx in selected_indices) for state in chain.states]
        formula = chain_to_formula(projected_states, projected_genes)
    else:
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


def deduplicate_projected_transitions(
    projected_items: Iterable[Tuple[Transition, Sequence[int]]],
    genes: Sequence[str],
) -> List[Tuple[Transition, Tuple[int, ...]]]:
    seen: set[Tuple[Tuple[int, ...], Tuple[int, ...], Tuple[str, ...]]] = set()
    unique: List[Tuple[Transition, Tuple[int, ...]]] = []
    for transition, indices in projected_items:
        projected = project_transition(transition, genes, indices)
        key = (projected.from_state, projected.to_state, projected.projected_genes)
        if key in seen:
            continue
        seen.add(key)
        unique.append((transition, tuple(indices)))
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


def deduplicate_singletons(singletons: Iterable[TraceSingleton]) -> List[TraceSingleton]:
    seen: set[Tuple[int, ...]] = set()
    unique: List[TraceSingleton] = []
    for singleton in singletons:
        if singleton.state in seen:
            continue
        seen.add(singleton.state)
        unique.append(singleton)
    return unique


def deduplicate_cycles(cycles: Iterable[TraceCycleCandidate]) -> List[TraceCycleCandidate]:
    seen: set[Tuple[Tuple[int, ...], ...]] = set()
    unique: List[TraceCycleCandidate] = []
    for cycle in cycles:
        if cycle.states in seen:
            continue
        seen.add(cycle.states)
        unique.append(cycle)
    return unique


def deduplicate_projected_cycles(
    cycles: Iterable[Tuple[TraceCycleCandidate, Sequence[int]]],
    genes: Sequence[str],
) -> List[Tuple[TraceCycleCandidate, Tuple[int, ...]]]:
    seen: set[Tuple[Tuple[Tuple[int, ...], ...], Tuple[str, ...]]] = set()
    unique: List[Tuple[TraceCycleCandidate, Tuple[int, ...]]] = []
    for cycle, indices in cycles:
        projected_genes = tuple(genes[idx] for idx in indices)
        projected_states = tuple(tuple(state[idx] for idx in indices) for state in cycle.states)
        key = (projected_states, projected_genes)
        if key in seen:
            continue
        seen.add(key)
        unique.append((cycle, tuple(indices)))
    return unique


def deduplicate_projected_singletons(
    singletons: Iterable[Tuple[TraceSingleton, Sequence[int]]],
    genes: Sequence[str],
) -> List[Tuple[TraceSingleton, Tuple[int, ...]]]:
    seen: set[Tuple[Tuple[int, ...], Tuple[str, ...]]] = set()
    unique: List[Tuple[TraceSingleton, Tuple[int, ...]]] = []
    for singleton, indices in singletons:
        state_bits, projected_genes = project_state(singleton.state, genes, indices)
        key = (state_bits, tuple(projected_genes))
        if key in seen:
            continue
        seen.add(key)
        unique.append((singleton, tuple(indices)))
    return unique


def sample_items(
    items: List[T],
    keep_percent: float,
    seed: int | None,
) -> List[T]:
    if not (0 <= keep_percent <= 100):
        raise ValueError("--keep-percent must be between 0 and 100.")
    if keep_percent == 100:
        return items
    if keep_percent == 0:
        return []

    n_total = len(items)
    n_keep = int(round(n_total * keep_percent / 100.0))
    n_keep = max(0, min(n_total, n_keep))
    if n_keep == n_total:
        return items
    if n_keep == 0:
        return []

    rng = random.Random(seed)
    selected_indices = sorted(rng.sample(range(n_total), n_keep))
    return [items[i] for i in selected_indices]


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
        choices=["consecutive", "all_pairs", "chain", "milestones", "endpoints"],
        default="consecutive",
        help="consecutive = one property per adjacent states; all_pairs = one property per i<j pair in each trace; endpoints = one start-to-end reachability per trace; chain = one ordered reachability-chain property per trace; milestones = one lighter chain over sampled milestone states per trace.",
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
    parser.add_argument(
        "--compress-stutter",
        dest="compress_stutter",
        action="store_true",
        default=True,
        help="Collapse consecutive duplicate states before generating properties (default: enabled).",
    )
    parser.add_argument(
        "--no-compress-stutter",
        dest="compress_stutter",
        action="store_false",
        help="Keep consecutive duplicate states as-is.",
    )
    parser.add_argument(
        "--max-chain-states",
        type=int,
        help="Optional cap for chain-like modes. If a trace is longer, it is reduced to evenly spaced milestone states.",
    )
    parser.add_argument(
        "--partial-state-size",
        type=int,
        help="If set, project each state formula to this many genes instead of using the full state.",
    )
    parser.add_argument(
        "--partial-state-mode",
        choices=["variance", "first", "random", "random_per_property"],
        default="variance",
        help="How to choose genes for projected partial states: most variable across traces (variance), first genes in genes.txt order, one global random subset (random), or a different random subset per property (random_per_property).",
    )
    parser.add_argument(
        "--fixed-point-prefix",
        default="trace_attractor_candidate",
        help="Prefix for trace-derived singleton recurrence candidate properties.",
    )
    parser.add_argument(
        "--cycle-prefix",
        default="trace_cycle_candidate",
        help="Prefix for trace-derived cycle candidate properties.",
    )
    parser.add_argument(
        "--cycle-lengths",
        default="2,3",
        help="Comma-separated cycle lengths to detect from repeated trace tails (default: 2,3).",
    )
    return parser


def main() -> None:
    parser = build_argument_parser()
    args = parser.parse_args()
    script_dir = Path(__file__).resolve().parent
    base_dir = script_dir.parent if (script_dir.parent / "configs").exists() else script_dir
    cwd = Path.cwd()
    config_path = resolve_user_path(args.config, base_dir) if args.config else None
    cfg = read_kv_config(config_path) if config_path else {}

    traces_dir_value = args.traces_dir or cfg_get_str(cfg, "traces_dir")
    output_value = args.output or cfg_get_str(cfg, "output")
    if not traces_dir_value or not output_value:
        parser.error("Provide --config with traces_dir/output keys, or pass --traces-dir and --output.")

    traces_dir = resolve_config_value_path(traces_dir_value, config_path, base_dir, cwd)
    genes_value = (
        args.genes if arg_was_passed("--genes") else cfg_get_str(cfg, "genes", args.genes)
    )
    genes_path = resolve_config_value_path(genes_value, config_path, base_dir, cwd) if genes_value else (traces_dir / "genes.txt")
    output_path = resolve_config_value_path(output_value, config_path, base_dir, cwd)
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
    compress_stutter = (
        args.compress_stutter
        if arg_was_passed("--compress-stutter") or arg_was_passed("--no-compress-stutter")
        else cfg_get_bool(cfg, "compress_stutter", args.compress_stutter)
    )
    max_chain_states = (
        args.max_chain_states
        if arg_was_passed("--max-chain-states")
        else cfg_get_int(cfg, "max_chain_states", None)
    )
    partial_state_size = (
        args.partial_state_size
        if arg_was_passed("--partial-state-size")
        else cfg_get_int(cfg, "partial_state_size", None)
    )
    partial_state_mode = (
        args.partial_state_mode
        if arg_was_passed("--partial-state-mode")
        else cfg_get_str(cfg, "partial_state_mode", args.partial_state_mode)
    )
    fixed_point_prefix = (
        args.fixed_point_prefix
        if arg_was_passed("--fixed-point-prefix")
        else cfg_get_str(cfg, "fixed_point_prefix", args.fixed_point_prefix)
    )
    cycle_prefix = (
        args.cycle_prefix
        if arg_was_passed("--cycle-prefix")
        else cfg_get_str(cfg, "cycle_prefix", args.cycle_prefix)
    )
    cycle_lengths_raw = (
        args.cycle_lengths
        if arg_was_passed("--cycle-lengths")
        else cfg_get_str(cfg, "cycle_lengths", args.cycle_lengths)
    )
    cycle_lengths = [int(part.strip()) for part in str(cycle_lengths_raw).split(",") if part.strip()]

    genes = load_genes(genes_path)
    trace_files = discover_trace_files(traces_dir, str(trace_glob))
    raw_count = 0
    unique_count = 0
    selected_transitions: List[Transition] = []
    selected_chains: List[TraceChain] = []
    selected_singletons: List[TraceSingleton] = []
    selected_cycles: List[TraceCycleCandidate] = []
    selected_indices: List[int] | None = None
    projected_selected_transitions: List[Tuple[Transition, Tuple[int, ...]]] = []
    projected_selected_singletons: List[Tuple[TraceSingleton, Tuple[int, ...]]] = []
    projected_selected_cycles: List[Tuple[TraceCycleCandidate, Tuple[int, ...]]] = []
    singleton_raw_count = 0
    singleton_unique_count = 0
    cycle_raw_count = 0
    cycle_unique_count = 0

    use_global_projection = (
        partial_state_size is not None and str(partial_state_mode) != "random_per_property"
    )
    use_per_property_projection = str(partial_state_mode) == "random_per_property"

    if use_global_projection:
        selected_indices = select_partial_gene_indices(
            trace_files=trace_files,
            genes_count=len(genes),
            compress_stutter=compress_stutter,
            partial_state_size=int(partial_state_size),
            partial_state_mode=str(partial_state_mode),
            seed=seed,
        )

    if pair_mode in {"chain", "milestones"}:
        chains = build_trace_chains(
            trace_files,
            genes_count=len(genes),
            pair_mode=str(pair_mode),
            compress_stutter=compress_stutter,
            max_chain_states=max_chain_states,
        )
        raw_count = len(chains)
        if not no_dedup:
            chains = deduplicate_chains(chains)
        unique_count = len(chains)
        selected_chains = sample_items(chains, keep_percent=float(keep_percent), seed=seed)
    else:
        singletons = build_trace_singletons(
            trace_files,
            genes_count=len(genes),
            compress_stutter=compress_stutter,
        )
        singleton_raw_count = len(singletons)
        if not no_dedup:
            singletons = deduplicate_singletons(singletons)
        cycles = build_trace_cycle_candidates(
            trace_files,
            genes_count=len(genes),
            compress_stutter=compress_stutter,
            cycle_lengths=cycle_lengths,
        )
        cycle_raw_count = len(cycles)
        if not no_dedup:
            cycles = deduplicate_cycles(cycles)
        transitions = build_transitions(
            trace_files,
            genes_count=len(genes),
            pair_mode=str(pair_mode),
            compress_stutter=compress_stutter,
        )
        raw_count = len(transitions)
        if not no_dedup:
            transitions = deduplicate_transitions(transitions)
        if use_per_property_projection:
            projected_candidates = [
                (
                    transition,
                    tuple(
                        choose_indices_for_transition(
                            transition,
                            genes,
                            int(partial_state_size),
                            "random",
                            seed,
                        )
                    ),
                )
                for transition in transitions
            ]
            if not no_dedup:
                projected_candidates = deduplicate_projected_transitions(projected_candidates, genes)
            unique_count = len(projected_candidates)
            projected_selected_transitions = sample_items(projected_candidates, keep_percent=float(keep_percent), seed=seed)
            projected_singleton_candidates = [
                (
                    singleton,
                    tuple(
                        choose_indices_for_transition(
                            Transition(
                                trace_name=singleton.trace_name,
                                from_index=0,
                                to_index=0,
                                from_state=singleton.state,
                                to_state=singleton.state,
                            ),
                            genes,
                            int(partial_state_size),
                            "random",
                            seed,
                        )
                    ),
                )
                for singleton in singletons
            ]
            if not no_dedup:
                projected_singleton_candidates = deduplicate_projected_singletons(projected_singleton_candidates, genes)
            singleton_unique_count = len(projected_singleton_candidates)
            projected_selected_singletons = sample_items(projected_singleton_candidates, keep_percent=float(keep_percent), seed=seed)
            projected_cycle_candidates = [
                (
                    cycle,
                    tuple(
                        choose_indices_for_transition(
                            Transition(
                                trace_name=cycle.trace_name,
                                from_index=0,
                                to_index=len(cycle.states) - 1,
                                from_state=cycle.states[0],
                                to_state=cycle.states[-1],
                            ),
                            genes,
                            int(partial_state_size),
                            "random",
                            seed,
                        )
                    ),
                )
                for cycle in cycles
            ]
            if not no_dedup:
                projected_cycle_candidates = deduplicate_projected_cycles(projected_cycle_candidates, genes)
            cycle_unique_count = len(projected_cycle_candidates)
            projected_selected_cycles = sample_items(projected_cycle_candidates, keep_percent=float(keep_percent), seed=seed)
        else:
            if selected_indices is not None and not no_dedup:
                projected_candidates = [(transition, tuple(selected_indices)) for transition in transitions]
                projected_candidates = deduplicate_projected_transitions(projected_candidates, genes)
                transitions = [transition for transition, _ in projected_candidates]
                projected_singleton_candidates = [(singleton, tuple(selected_indices)) for singleton in singletons]
                projected_singleton_candidates = deduplicate_projected_singletons(projected_singleton_candidates, genes)
                singletons = [singleton for singleton, _ in projected_singleton_candidates]
                projected_cycle_candidates = [(cycle, tuple(selected_indices)) for cycle in cycles]
                projected_cycle_candidates = deduplicate_projected_cycles(projected_cycle_candidates, genes)
                cycles = [cycle for cycle, _ in projected_cycle_candidates]
            unique_count = len(transitions)
            selected_transitions = sample_items(transitions, keep_percent=float(keep_percent), seed=seed)
            singleton_unique_count = len(singletons)
            selected_singletons = sample_items(singletons, keep_percent=float(keep_percent), seed=seed)
            cycle_unique_count = len(cycles)
            selected_cycles = sample_items(cycles, keep_percent=float(keep_percent), seed=seed)

    if int(start_index) < 0:
        raise ValueError("--start-index must be >= 0")

    properties: List[str] = []
    if pair_mode in {"chain", "milestones"}:
        for idx, chain in enumerate(selected_chains, start=int(start_index)):
            prop_name = f"{property_prefix}_{idx}"
            properties.append(chain_to_property_line(chain, genes, prop_name, selected_indices=selected_indices))
        next_index = int(start_index) + len(selected_chains)
    else:
        if use_per_property_projection:
            for idx, (transition, indices) in enumerate(projected_selected_transitions, start=int(start_index)):
                prop_name = f"{property_prefix}_{idx}"
                properties.append(transition_to_property_line(transition, genes, prop_name, selected_indices=indices))
            next_index = int(start_index) + len(projected_selected_transitions)
            for idx, (singleton, indices) in enumerate(projected_selected_singletons, start=next_index):
                prop_name = f"{fixed_point_prefix}_{idx}"
                properties.append(singleton_to_property_line(singleton, genes, prop_name, selected_indices=indices))
            next_index += len(projected_selected_singletons)
            for idx, (cycle, indices) in enumerate(projected_selected_cycles, start=next_index):
                prop_name = f"{cycle_prefix}_{idx}"
                properties.append(cycle_candidate_to_property_line(cycle, genes, prop_name, selected_indices=indices))
        else:
            for idx, transition in enumerate(selected_transitions, start=int(start_index)):
                prop_name = f"{property_prefix}_{idx}"
                properties.append(transition_to_property_line(transition, genes, prop_name, selected_indices=selected_indices))
            next_index = int(start_index) + len(selected_transitions)
            for idx, singleton in enumerate(selected_singletons, start=next_index):
                prop_name = f"{fixed_point_prefix}_{idx}"
                properties.append(singleton_to_property_line(singleton, genes, prop_name, selected_indices=selected_indices))
            next_index += len(selected_singletons)
            for idx, cycle in enumerate(selected_cycles, start=next_index):
                prop_name = f"{cycle_prefix}_{idx}"
                properties.append(cycle_candidate_to_property_line(cycle, genes, prop_name, selected_indices=selected_indices))

    metadata = [
        f"# Generated from traces in: {traces_dir}",
        f"# Genes file: {genes_path}",
        f"# Trace files matched: {len(trace_files)} ({trace_glob})",
        f"# Pair mode: {pair_mode}",
        f"# compress_stutter: {compress_stutter}",
        f"# Raw transitions: {raw_count}",
        f"# After dedup: {unique_count}" if not no_dedup else f"# Duplicates kept: {unique_count}",
        f"# Raw singleton traces: {singleton_raw_count}",
        f"# Singleton traces after dedup: {singleton_unique_count}" if not no_dedup else f"# Singleton traces kept: {singleton_unique_count}",
        f"# Raw cycle candidates: {cycle_raw_count}",
        f"# Cycle candidates after dedup: {cycle_unique_count}" if not no_dedup else f"# Cycle candidates kept: {cycle_unique_count}",
        f"# keep_percent: {keep_percent}",
        f"# Final properties written: {len(properties)}",
    ]
    if max_chain_states is not None:
        metadata.append(f"# max_chain_states: {max_chain_states}")
    if selected_indices is not None:
        projected_genes = [genes[idx] for idx in selected_indices]
        metadata.append(f"# partial_state_size: {len(selected_indices)}")
        metadata.append(f"# partial_state_mode: {partial_state_mode}")
        metadata.append(f"# partial_state_genes: {' '.join(projected_genes)}")
    elif use_per_property_projection and partial_state_size is not None:
        metadata.append(f"# partial_state_size: {int(partial_state_size)}")
        metadata.append(f"# partial_state_mode: {partial_state_mode}")
        metadata.append("# partial_state_genes: varies_per_property")
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
    print(f"Raw singleton traces: {singleton_raw_count}")
    if not no_dedup:
        print(f"Unique singleton traces: {singleton_unique_count}")
    print(f"Raw cycle candidates: {cycle_raw_count}")
    if not no_dedup:
        print(f"Unique cycle candidates: {cycle_unique_count}")
    print(f"Properties written: {len(properties)}")
    print(f"Output: {output_path}")
    if pair_mode == "all_pairs":
        print("Note: all_pairs is still finite for finite traces (it uses all i<j state pairs in each trace).")
    if pair_mode == "endpoints":
        print("Note: endpoints mode generates one start-to-end reachability property per trace.")
    if pair_mode == "chain":
        print("Note: chain mode generates one ordered reachability-chain property per trace.")
    if pair_mode == "milestones":
        print("Note: milestones mode generates one reduced ordered reachability-chain property per trace.")
    if selected_indices is not None:
        print(
            "Note: partial-state projection is enabled for genes: "
            + ", ".join(genes[idx] for idx in selected_indices)
        )
    elif use_per_property_projection and partial_state_size is not None:
        print("Note: partial-state projection is enabled with a different random gene subset per property.")
    if singleton_unique_count:
        print("Note: singleton traces were converted into trace-derived recurrence/attractor candidate properties.")
    if cycle_unique_count:
        print("Note: repeated trace tails were converted into trace-derived cycle candidate properties.")


if __name__ == "__main__":
    main()
