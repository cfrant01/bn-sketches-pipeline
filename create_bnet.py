#!/usr/bin/env python3
"""
Create .bnet files from simple instruction files.

Instruction format (one rule per line):
    targets, factors              # optional header line (ignored)
    A = B & !C
    B, 1
    C: A | B

Supported separators: '=', ',', ':'
Comments and empty lines are ignored. Comments start with '#'.

Examples:
    python create_bnet.py --input configs/sample_rules.txt --output outputs/bnet/model.bnet
    python create_bnet.py --input instructions_dir --output outputs/bnet
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


HEADER = [
    "# model in BoolNet format",
    "# the header targets, factors is mandatory to be importable in the R package BoolNet",
    "",
    "targets, factors",
]

SUPPORTED_SUFFIXES = {".txt", ".rules", ".instr", ".instructions"}


def strip_inline_comment(line: str) -> str:
    if "#" in line:
        return line.split("#", 1)[0].strip()
    return line.strip()


def parse_rule(line: str, line_number: int, source: Path) -> Tuple[str, str]:
    cleaned = strip_inline_comment(line)
    if not cleaned:
        raise ValueError("empty")

    lowered = cleaned.lower().replace(" ", "")
    if lowered == "targets,factors":
        raise ValueError("header")

    for sep in ("=", ",", ":"):
        if sep in cleaned:
            left, right = cleaned.split(sep, 1)
            target = left.strip()
            expr = right.strip()
            if not target or not expr:
                break
            return target, expr

    raise ValueError(
        f"Invalid rule at {source}:{line_number}. Expected 'target = expr', "
        f"'target, expr', or 'target: expr'."
    )


def parse_instruction_file(path: Path) -> List[Tuple[str, str]]:
    rules: List[Tuple[str, str]] = []
    for idx, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            rule = parse_rule(raw_line, idx, path)
        except ValueError as exc:
            tag = str(exc)
            if tag in {"empty", "header"}:
                continue
            raise
        else:
            rules.append(rule)

    if not rules:
        raise ValueError(f"No valid rules found in {path}")
    return rules


def format_bnet_lines(rules: Iterable[Tuple[str, str]], align: bool = True) -> List[str]:
    rule_list = list(rules)
    if not align:
        return [f"{target}, {expr}" for target, expr in rule_list]

    width = max(len(target) for target, _ in rule_list)
    return [f"{target.ljust(width)}, {expr}" for target, expr in rule_list]


def write_bnet(output_path: Path, rules: List[Tuple[str, str]], include_header: bool) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    if include_header:
        lines.extend(HEADER)
    lines.extend(format_bnet_lines(rules))
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def collect_instruction_files(input_path: Path) -> List[Path]:
    if input_path.is_file():
        return [input_path]
    if input_path.is_dir():
        files = [p for p in sorted(input_path.iterdir()) if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES]
        if files:
            return files
        return [p for p in sorted(input_path.iterdir()) if p.is_file()]
    raise FileNotFoundError(f"Input path not found: {input_path}")


def build_output_path(input_file: Path, input_root: Path, output_target: Path) -> Path:
    if input_root.is_file():
        return output_target
    relative = input_file.relative_to(input_root)
    return output_target / relative.with_suffix(".bnet")


def generate_random_expression(regulators: List[str]) -> str:
    if not regulators:
        return random.choice(["0", "1"])

    literals = [f"!{r}" if random.choice([True, False]) else r for r in regulators]
    expr = literals[0]
    for lit in literals[1:]:
        op = random.choice([" & ", " | "])
        expr = f"{expr}{op}{lit}"

    if len(literals) >= 2 and random.choice([True, False]):
        expr = f"({expr})"
    return expr


def generate_random_rules(n: int, k: int, prefix: str = "x") -> List[Tuple[str, str]]:
    if n <= 0:
        raise ValueError("--n must be >= 1")
    if k < 0:
        raise ValueError("--k must be >= 0")

    nodes = [f"{prefix}{i}" for i in range(1, n + 1)]
    rules: List[Tuple[str, str]] = []

    for node in nodes:
        candidates = [x for x in nodes if x != node]
        max_regulators = min(k, len(candidates))
        regulator_count = random.randint(0, max_regulators) if max_regulators > 0 else 0
        regulators = random.sample(candidates, regulator_count) if regulator_count > 0 else []
        expr = generate_random_expression(regulators)
        rules.append((node, expr))

    return rules


def resolve_random_output_path(output_arg: Optional[str], n: int, k: int) -> Path:
    if output_arg:
        return Path(output_arg)
    return Path("outputs") / "bnet" / f"random_n{n}_k{k}.bnet"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate .bnet file(s) from instruction file(s) or create a random .bnet network."
    )
    parser.add_argument("--input", help="Instruction file or directory.")
    parser.add_argument("--output", help="Output .bnet file (single input/random) or output directory (directory input).")
    parser.add_argument("--random", action="store_true", help="Generate a random Boolean network instead of reading rules from file.")
    parser.add_argument("--n", type=int, help="Number of nodes for --random mode.")
    parser.add_argument("--k", type=int, help="Maximum number of other nodes used in each function (random mode).")
    parser.add_argument("--seed", type=int, help="Optional random seed for reproducible random networks.")
    parser.add_argument("--node-prefix", default="x", help="Node name prefix in random mode (default: x -> x1, x2, ...).")
    parser.add_argument(
        "--no-header",
        action="store_true",
        help="Do not write BoolNet header (targets, factors).",
    )
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    if args.random:
        if args.input:
            raise ValueError("Use either --random or --input, not both.")
        if args.n is None or args.k is None:
            raise ValueError("--random mode requires both --n and --k.")

        rules = generate_random_rules(args.n, args.k, prefix=args.node_prefix)
        output_path = resolve_random_output_path(args.output, args.n, args.k)
        write_bnet(output_path, rules, include_header=not args.no_header)
        print(f"Wrote {output_path}")
        return

    if not args.input:
        raise ValueError("Provide --input <file|dir> or use --random with --n and --k.")
    if not args.output:
        raise ValueError("--output is required when using --input mode.")

    input_path = Path(args.input)
    output_path = Path(args.output)

    files = collect_instruction_files(input_path)
    if input_path.is_dir() and output_path.suffix.lower() == ".bnet":
        raise ValueError("When --input is a directory, --output must be a directory, not a .bnet file.")

    for src in files:
        rules = parse_instruction_file(src)
        dst = build_output_path(src, input_path, output_path)
        write_bnet(dst, rules, include_header=not args.no_header)
        print(f"Wrote {dst}")


if __name__ == "__main__":
    main()
