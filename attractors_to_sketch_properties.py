#!/usr/bin/env python3
"""
Generate Sketches dynamic properties from BoolNet attractor summary output.

Consumes files like `outputs/traces/attractors_summary.txt` created by
`generate_traces_from_bnet.R` and emits `## PROPERTIES` snippet lines.

Supported outputs:
- fixed-point properties (specific steady-state existence)
- attractor properties (specific attractor existence using one witness state)

Examples:
    python attractors_to_sketch_properties.py ^
      --summary outputs/traces/attractors_summary.txt ^
      --output outputs/sketch_parts/fixed_points_properties.aeon ^
      --mode fixed-points

    python attractors_to_sketch_properties.py ^
      --summary outputs/traces/attractors_summary.txt ^
      --output outputs/sketch_parts/attractor_properties.aeon ^
      --mode attractors --include-forbid-extra
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence


ATTR_HEADER_RE = re.compile(r"^Attractor\s+(\d+)\b.*?(\d+)\s+state\(s\):", re.IGNORECASE)
GENE_ORDER_RE = re.compile(r"Genes are encoded in the following order:\s*(.+?)\s*$", re.IGNORECASE)


@dataclass
class AttractorInfo:
    index: int
    declared_state_count: int
    states: List[str]


def resolve_user_path(value: str, base_dir: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base_dir / path)


def read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return path.read_text(encoding="utf-8")


def parse_genes_from_summary(summary_text: str) -> List[str] | None:
    for line in summary_text.splitlines():
        m = GENE_ORDER_RE.search(line.strip())
        if m:
            genes = [g for g in m.group(1).strip().split() if g]
            return genes if genes else None
    return None


def load_genes(genes_path: Path) -> List[str]:
    genes = [ln.strip() for ln in read_text(genes_path).splitlines() if ln.strip()]
    if not genes:
        raise ValueError(f"No genes found in {genes_path}")
    return genes


def parse_attractors(summary_text: str, genes_count: int) -> List[AttractorInfo]:
    attractors: List[AttractorInfo] = []
    current: AttractorInfo | None = None
    state_re = re.compile(rf"\b([01]{{{genes_count}}})\b")

    for raw in summary_text.splitlines():
        line = raw.strip()

        m = ATTR_HEADER_RE.match(line)
        if m:
            if current is not None:
                attractors.append(current)
            current = AttractorInfo(index=int(m.group(1)), declared_state_count=int(m.group(2)), states=[])
            continue

        if current is None:
            continue

        sm = state_re.search(line)
        if sm:
            state = sm.group(1)
            if state not in current.states:
                current.states.append(state)

    if current is not None:
        attractors.append(current)

    return attractors


def bits_to_formula(bits: str, genes: Sequence[str]) -> str:
    if len(bits) != len(genes):
        raise ValueError(f"State length {len(bits)} does not match genes length {len(genes)}")
    literals = [gene if b == "1" else f"~{gene}" for gene, b in zip(genes, bits)]
    return "(" + " & ".join(literals) + ")"


def mk_fixed_point_formula(bits: str, genes: Sequence[str]) -> str:
    state = bits_to_formula(bits, genes)
    return f"3{{x}}: ( @{{x}}: ( {state} & (AX ({state})) ) )"


def mk_attractor_formula(bits: str, genes: Sequence[str]) -> str:
    state = bits_to_formula(bits, genes)
    return f"3{{x}}: ( @{{x}}: ( {state} & (AG EF ({state})) ) )"


def mk_forbid_other_fixed_points_formula(states: Sequence[str], genes: Sequence[str]) -> str:
    encoded = [bits_to_formula(s, genes) for s in states]
    parts = " & ".join(f"~({s})" for s in encoded)
    return f"~(3{{x}}: (@{{x}}: {parts} & (AX {{x}})))"


def mk_forbid_other_attractors_formula(states: Sequence[str], genes: Sequence[str]) -> str:
    encoded = [bits_to_formula(s, genes) for s in states]
    joined = " | ".join(encoded + ["false"])
    return f"~(3{{x}}: (@{{x}}: ~(AG EF ({joined} ))))"


def write_properties(output_path: Path, lines: List[str]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Sketches dynamic properties from BoolNet attractor summary output."
    )
    parser.add_argument("--summary", required=True, help="Path to BoolNet attractors_summary.txt")
    parser.add_argument("--output", required=True, help="Output .aeon snippet for ## PROPERTIES")
    parser.add_argument("--genes", help="Optional genes.txt path. If omitted, parse gene order from summary.")
    parser.add_argument(
        "--mode",
        choices=["fixed-points", "attractors", "both"],
        default="fixed-points",
        help="Which property types to generate.",
    )
    parser.add_argument(
        "--include-forbid-extra",
        action="store_true",
        help="Add one extra property forbidding additional fixed points/attractors (depending on mode).",
    )
    parser.add_argument(
        "--property-prefix",
        default=None,
        help="Optional prefix override. Defaults depend on mode (fixed_point / attractor).",
    )
    parser.add_argument("--start-index", type=int, default=1, help="Start index for numbering.")
    parser.add_argument("--no-properties-header", action="store_true", help="Do not write '## PROPERTIES'.")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    summary_path = resolve_user_path(args.summary, base_dir)
    output_path = resolve_user_path(args.output, base_dir)
    summary_text = read_text(summary_path)

    genes: List[str]
    if args.genes:
        genes = load_genes(resolve_user_path(args.genes, base_dir))
    else:
        parsed = parse_genes_from_summary(summary_text)
        if parsed is None:
            raise ValueError("Could not parse gene order from summary. Provide --genes <genes.txt>.")
        genes = parsed

    attractors = parse_attractors(summary_text, genes_count=len(genes))
    if not attractors:
        raise ValueError(f"No attractors parsed from {summary_path}")

    lines: List[str] = []
    if not args.no_properties_header:
        lines.append("## PROPERTIES")
    lines.extend(
        [
            f"# Generated from BoolNet attractor summary: {summary_path}",
            f"# Genes ({len(genes)}): {' '.join(genes)}",
            f"# Parsed attractors: {len(attractors)}",
            f"# Mode: {args.mode}",
        ]
    )

    next_idx = args.start_index

    if args.mode in {"fixed-points", "both"}:
        fp_attractors = [a for a in attractors if len(a.states) == 1]
        prefix = args.property_prefix or "fixed_point"
        for a in fp_attractors:
            formula = mk_fixed_point_formula(a.states[0], genes)
            lines.append(f"#! dynamic_property: {prefix}_{next_idx}: #`{formula}`#")
            next_idx += 1

        if args.include_forbid_extra and fp_attractors:
            all_fp_states = [a.states[0] for a in fp_attractors]
            formula = mk_forbid_other_fixed_points_formula(all_fp_states, genes)
            lines.append(f"#! dynamic_property: {prefix}_forbid_extra: #`{formula}`#")

    if args.mode in {"attractors", "both"}:
        # One state witness per attractor is enough for specific-attractor existence.
        attr_prefix = args.property_prefix if args.mode == "attractors" else "attractor"
        for a in attractors:
            witness = a.states[0]
            formula = mk_attractor_formula(witness, genes)
            lines.append(f"#! dynamic_property: {attr_prefix}_{next_idx}: #`{formula}`#")
            next_idx += 1

        if args.include_forbid_extra:
            witness_states = [a.states[0] for a in attractors]
            formula = mk_forbid_other_attractors_formula(witness_states, genes)
            forbid_name = (
                f"{(args.property_prefix or 'attractor')}_forbid_extra"
                if args.mode == "attractors"
                else "attractor_forbid_extra"
            )
            lines.append(f"#! dynamic_property: {forbid_name}: #`{formula}`#")

    write_properties(output_path, lines)

    fp_count = sum(1 for a in attractors if len(a.states) == 1)
    cyc_count = len(attractors) - fp_count
    print(f"Attractors parsed: {len(attractors)} (fixed points: {fp_count}, cyclic: {cyc_count})")
    print(f"Genes: {len(genes)}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()

