#!/usr/bin/env python3
"""
Convert a .bnet file into the "## MODEL" part of an AEON sketch.

The script extracts which variables (regulators) appear in each Boolean function and
builds an AEON sketch model section with unknown influence signs (`-??`) and symbolic
function placeholders (`f_<target>(...)`).

You can control reveal granularity with two independent percentages:
1) `--reveal-functions-percent`: reveal support information only for a subset of targets
2) `--reveal-regulators-percent`: for revealed targets, reveal only a subset of regulators

Examples:
    python bnet_to_sketchStructure.py --config configs/bnet_to_sketchStructure_params.txt
    python bnet_to_sketchStructure.py --config configs/bnet_to_sketchStructure_params.txt --seed 42
"""

from __future__ import annotations

import argparse
import random
import re
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple


TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


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


def cfg_get_float(cfg: dict[str, str], key: str, default: float | None = None) -> float | None:
    if key not in cfg:
        return default
    return float(cfg[key])


def cfg_get_int(cfg: dict[str, str], key: str, default: int | None = None) -> int | None:
    if key not in cfg:
        return default
    return int(cfg[key])


def arg_was_passed(flag: str) -> bool:
    return flag in sys.argv


def resolve_user_path(value: str, base_dir: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return base_dir / path


def parse_bnet(path: Path) -> List[Tuple[str, str]]:
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
            raise ValueError(f"{path}:{line_no} has empty target or expression.")
        rules.append((target, expr))

    if not rules:
        raise ValueError(f"No rules found in {path}")
    return rules


def extract_regulators(rules: Sequence[Tuple[str, str]]) -> Dict[str, List[str]]:
    targets = [target for target, _ in rules]
    target_set = set(targets)

    supports: Dict[str, List[str]] = {}
    for target, expr in rules:
        seen = set()
        ordered: List[str] = []
        for token in TOKEN_RE.findall(expr):
            if token in target_set and token not in seen:
                seen.add(token)
                ordered.append(token)
        supports[target] = ordered
    return supports


def choose_subset(items: Sequence[str], reveal_percent: float, rng: random.Random) -> List[str]:
    if not items:
        return []
    if reveal_percent <= 0:
        return []
    if reveal_percent >= 100:
        return list(items)

    n = int(round(len(items) * reveal_percent / 100.0))
    n = max(0, min(len(items), n))
    if n == 0:
        return []
    if n == len(items):
        return list(items)

    idxs = sorted(rng.sample(range(len(items)), n))
    return [items[i] for i in idxs]


def build_model_section(
    supports: Dict[str, List[str]],
    reveal_functions_percent: float,
    reveal_regulators_percent: float,
    seed: int | None,
    edge_op: str,
    hidden_policy: str,
) -> List[str]:
    if not (0 <= reveal_functions_percent <= 100):
        raise ValueError("--reveal-functions-percent must be between 0 and 100.")
    if not (0 <= reveal_regulators_percent <= 100):
        raise ValueError("--reveal-regulators-percent must be between 0 and 100.")

    rng = random.Random(seed)
    targets = list(supports.keys())  # preserve .bnet order
    all_variables = list(targets)

    revealed_targets = set(choose_subset(targets, reveal_functions_percent, rng))

    lines = ["## MODEL"]

    for target in targets:
        full_regs = supports[target]
        is_hidden = target not in revealed_targets
        regs_to_reveal = [] if is_hidden else choose_subset(full_regs, reveal_regulators_percent, rng)

        edge_regs = regs_to_reveal
        if not regs_to_reveal and hidden_policy == "omit":
            # Keep the variable present in the AEON model while leaving its update
            # function unspecified. Listing all variables as possible regulators makes
            # the hidden target maximally unconstrained instead of silently removing it.
            edge_regs = all_variables

        for reg in edge_regs:
            lines.append(f"{reg} {edge_op} {target}")

        if regs_to_reveal:
            args = ", ".join(regs_to_reveal)
            lines.append(f"${target}:f_{target}({args})")
        else:
            # Nothing revealed for this function support.
            if hidden_policy == "omit":
                continue
            elif hidden_policy == "question":
                lines.append(f"${target}: ?")
            elif hidden_policy == "self":
                lines.append(f"{target} {edge_op} {target}")
                lines.append(f"${target}:{target}")
            else:
                raise ValueError(f"Unsupported hidden policy: {hidden_policy}")

    return lines


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create the '## MODEL' part of an AEON sketch from a .bnet file."
    )
    parser.add_argument("--config", help="Parameter file (key = value). Recommended.")
    parser.add_argument("--bnet", help="Input .bnet file.")
    parser.add_argument("--output", help="Output file for the generated model section.")
    parser.add_argument(
        "--reveal-functions-percent",
        type=float,
        default=100.0,
        help="Percent of target functions for which support info is revealed.",
    )
    parser.add_argument(
        "--reveal-regulators-percent",
        type=float,
        default=100.0,
        help="Percent of regulators revealed inside each revealed function.",
    )
    parser.add_argument("--seed", type=int, help="Optional random seed for reproducibility.")
    parser.add_argument(
        "--edge-op",
        default="-??",
        help="AEON influence edge operator to use (default: -??).",
    )
    parser.add_argument(
        "--hidden-policy",
        choices=["omit", "question", "self"],
        default="omit",
        help="How to represent targets with no revealed regulators: omit the update line (omit), '$x: ?' (question), or self-loop identity (self).",
    )
    args = parser.parse_args()
    base_dir = Path(__file__).resolve().parent
    cfg = read_kv_config(Path(args.config)) if args.config else {}

    bnet_path = args.bnet or cfg_get_str(cfg, "bnet")
    output_path_value = args.output or cfg_get_str(cfg, "output")
    reveal_functions_percent = (
        args.reveal_functions_percent
        if arg_was_passed("--reveal-functions-percent")
        else cfg_get_float(cfg, "reveal_functions_percent", args.reveal_functions_percent)
    )
    reveal_regulators_percent = (
        args.reveal_regulators_percent
        if arg_was_passed("--reveal-regulators-percent")
        else cfg_get_float(cfg, "reveal_regulators_percent", args.reveal_regulators_percent)
    )
    seed = args.seed if args.seed is not None else cfg_get_int(cfg, "seed", None)
    edge_op = args.edge_op if arg_was_passed("--edge-op") else cfg_get_str(cfg, "edge_op", args.edge_op)
    hidden_policy = (
        args.hidden_policy
        if arg_was_passed("--hidden-policy")
        else cfg_get_str(cfg, "hidden_policy", args.hidden_policy)
    )

    if not bnet_path or not output_path_value:
        parser.error("Provide --config with bnet/output keys, or pass --bnet and --output.")

    rules = parse_bnet(resolve_user_path(bnet_path, base_dir))
    supports = extract_regulators(rules)
    lines = build_model_section(
        supports=supports,
        reveal_functions_percent=float(reveal_functions_percent),
        reveal_regulators_percent=float(reveal_regulators_percent),
        seed=seed,
        edge_op=str(edge_op),
        hidden_policy=str(hidden_policy),
    )

    out_path = resolve_user_path(output_path_value, base_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    total_targets = len(supports)
    total_regs = sum(len(v) for v in supports.values())
    print(f"Targets: {total_targets}")
    print(f"Total regulator occurrences in supports: {total_regs}")
    print(f"Reveal functions percent: {reveal_functions_percent}")
    print(f"Reveal regulators percent: {reveal_regulators_percent}")
    if seed is not None:
        print(f"Seed: {seed}")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
