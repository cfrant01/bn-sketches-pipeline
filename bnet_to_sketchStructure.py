#!/usr/bin/env python3
"""
Convert a .bnet file into the "## MODEL" part of an AEON sketch.

The script extracts which variables (regulators) appear in each Boolean function and
builds an AEON sketch model section with unknown influence signs (`-??`) and symbolic
function placeholders (`f_<target>(...)`).

You can control reveal granularity with three independent percentages:
1) `--reveal-functions-percent`: reveal support information only for a subset of targets
2) `--reveal-regulators-percent`: for revealed targets, reveal only a subset of regulators
3) `--reveal-exact-functions-percent`: reveal the full Boolean update rule for a subset of targets

Exact-function reveal overrides support-only reveal for the selected targets.

Examples:
    python bnet_to_sketchStructure.py --config configs/structure.txt
    python bnet_to_sketchStructure.py --config configs/structure.txt --seed 42
"""

from __future__ import annotations

import argparse
import itertools
import random
import re
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from boolforge.boolean_function import BooleanFunction


TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def compile_boolean_expr(expr: str):
    def replace_token(match: re.Match[str]) -> str:
        token = match.group(0)
        return f'values["{token}"]'

    substituted = TOKEN_RE.sub(replace_token, expr)
    compiled_source = substituted.replace("!", " not ").replace("&", " and ").replace("|", " or ").strip()
    return compile(compiled_source, "<bnet-expr>", "eval")


def evaluate_boolean_expr(compiled_expr, values: dict[str, bool]) -> bool:
    return bool(eval(compiled_expr, {"__builtins__": {}}, {"values": values}))


def classify_regulation_edges(
    expr: str,
    regulators: Sequence[str],
    positive_op: str,
    negative_op: str,
    ambiguous_op: str,
    optional_op: str,
) -> Dict[str, str]:
    if not regulators:
        return {}

    compiled_expr = compile_boolean_expr(expr)
    edge_ops: Dict[str, str] = {}

    for regulator in regulators:
        other_regs = [name for name in regulators if name != regulator]
        saw_positive = False
        saw_negative = False
        is_essential = False

        for bits in itertools.product([False, True], repeat=len(other_regs)):
            base_assignment = dict(zip(other_regs, bits))
            low_assignment = dict(base_assignment)
            high_assignment = dict(base_assignment)
            low_assignment[regulator] = False
            high_assignment[regulator] = True

            low_value = evaluate_boolean_expr(compiled_expr, low_assignment)
            high_value = evaluate_boolean_expr(compiled_expr, high_assignment)

            if low_value != high_value:
                is_essential = True
            if (not low_value) and high_value:
                saw_positive = True
            if low_value and (not high_value):
                saw_negative = True

            if saw_positive and saw_negative:
                break

        if not is_essential:
            edge_ops[regulator] = optional_op
        elif saw_positive and not saw_negative:
            edge_ops[regulator] = positive_op
        elif saw_negative and not saw_positive:
            edge_ops[regulator] = negative_op
        else:
            edge_ops[regulator] = ambiguous_op

    return edge_ops


def build_truth_table(expr: str, regulators: Sequence[str]) -> List[int]:
    if not regulators:
        compiled_expr = compile_boolean_expr(expr)
        return [int(evaluate_boolean_expr(compiled_expr, {}))]

    compiled_expr = compile_boolean_expr(expr)
    truth_table: List[int] = []
    for bits in itertools.product([False, True], repeat=len(regulators)):
        assignment = dict(zip(regulators, bits))
        truth_table.append(int(evaluate_boolean_expr(compiled_expr, assignment)))
    return truth_table


def analyze_canalization(expr: str, regulators: Sequence[str]) -> List[Tuple[str, int, int]]:
    if not regulators:
        return []

    bf = BooleanFunction(build_truth_table(expr, regulators))
    properties = bf.get_layer_structure()
    order = list(properties.get("OrderOfCanalizingVariables", []))
    can_inputs = list(properties.get("CanalizingInputs", []))
    can_outputs = list(properties.get("CanalizedOutputs", []))

    return [
        (regulators[int(idx)], int(can_input), int(can_output))
        for idx, can_input, can_output in zip(order, can_inputs, can_outputs)
    ]


def build_canalization_template(
    target: str,
    visible_regulators: Sequence[str],
    canalization_data: Sequence[Tuple[str, int, int]],
) -> str | None:
    if not visible_regulators or not canalization_data:
        return None

    chosen: Tuple[str, int, int] | None = None
    for regulator, can_input, can_output in canalization_data:
        if regulator in visible_regulators:
            chosen = (regulator, can_input, can_output)
            break
    if chosen is None:
        return None

    regulator, can_input, can_output = chosen
    remaining = [reg for reg in visible_regulators if reg != regulator]
    literal = regulator if can_input == 1 else f"!{regulator}"

    if not remaining:
        if can_output == 1:
            return literal
        return f"!{literal}" if not literal.startswith("!") else literal[1:]

    residual_symbol = f"g_{target}(" + ", ".join(remaining) + ")"
    if can_output == 1:
        return f"{literal} | {residual_symbol}"

    anti_literal = f"!{regulator}" if can_input == 1 else regulator
    return f"{anti_literal} & {residual_symbol}"


def analyze_essentiality(expr: str, regulators: Sequence[str]) -> Tuple[List[str], List[str]]:
    if not regulators:
        return [], []

    bf = BooleanFunction(build_truth_table(expr, regulators))
    essential_indices = set(int(idx) for idx in bf.get_essential_variables())
    essential = [regulators[i] for i in range(len(regulators)) if i in essential_indices]
    non_essential = [regulators[i] for i in range(len(regulators)) if i not in essential_indices]
    return essential, non_essential


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
    rules: Sequence[Tuple[str, str]],
    supports: Dict[str, List[str]],
    reveal_functions_percent: float,
    reveal_regulators_percent: float,
    reveal_exact_functions_percent: float,
    seed: int | None,
    edge_op: str,
    hidden_policy: str,
    infer_monotonicity_for_exact: bool,
    positive_edge_op: str,
    negative_edge_op: str,
    ambiguous_edge_op: str,
    infer_canalization_for_exact: bool,
    apply_canalization_templates: bool,
    annotate_canalization_comments: bool,
    infer_essentiality: bool,
    apply_essentiality_to_symbolic_supports: bool,
    annotate_essentiality_comments: bool,
) -> Tuple[List[str], List[str], List[str]]:
    if not (0 <= reveal_functions_percent <= 100):
        raise ValueError("--reveal-functions-percent must be between 0 and 100.")
    if not (0 <= reveal_regulators_percent <= 100):
        raise ValueError("--reveal-regulators-percent must be between 0 and 100.")
    if not (0 <= reveal_exact_functions_percent <= 100):
        raise ValueError("--reveal-exact-functions-percent must be between 0 and 100.")

    rng = random.Random(seed)
    targets = [target for target, _ in rules]  # preserve .bnet order
    all_variables = list(targets)
    expr_map = {target: expr for target, expr in rules}

    revealed_targets = set(choose_subset(targets, reveal_functions_percent, rng))
    exact_targets = set(choose_subset(targets, reveal_exact_functions_percent, rng))

    lines = ["## MODEL"]
    canalization_report_lines: List[str] = []
    essentiality_report_lines: List[str] = []

    for target in targets:
        full_regs = supports[target]
        is_exact = target in exact_targets
        is_hidden = (target not in revealed_targets) and not is_exact
        essential_regs, non_essential_regs = (
            analyze_essentiality(expr_map[target], full_regs)
            if infer_essentiality
            else (list(full_regs), [])
        )
        reveal_pool = essential_regs if (apply_essentiality_to_symbolic_supports and not is_exact) else full_regs
        regs_to_reveal = list(full_regs) if is_exact else ([] if is_hidden else choose_subset(reveal_pool, reveal_regulators_percent, rng))

        edge_regs = regs_to_reveal
        if not regs_to_reveal and hidden_policy == "omit":
            # Keep the variable present in the AEON model while leaving its update
            # function unspecified. Listing all variables as possible regulators makes
            # the hidden target maximally unconstrained instead of silently removing it.
            edge_regs = all_variables

        inferred_edge_ops = (
            classify_regulation_edges(
                expr=expr_map[target],
                regulators=full_regs,
                positive_op=positive_edge_op,
                negative_op=negative_edge_op,
                ambiguous_op=ambiguous_edge_op,
                optional_op=edge_op,
            )
            if infer_monotonicity_for_exact
            else {}
        )
        canalization_data = (
            analyze_canalization(expr_map[target], full_regs)
            if infer_canalization_for_exact
            else []
        )

        for reg in edge_regs:
            reg_edge_op = inferred_edge_ops.get(reg, edge_op)
            lines.append(f"{reg} {reg_edge_op} {target}")

        if canalization_data:
            for regulator, can_input, can_output in canalization_data:
                canalization_report_lines.append(
                    f"{target}: {regulator}={can_input} => {target}={can_output}"
                )
            if annotate_canalization_comments:
                details = ", ".join(
                    f"{regulator}={can_input} => {target}={can_output}"
                    for regulator, can_input, can_output in canalization_data
                )
                lines.append(f"# canalization {target}: {details}")

        if infer_essentiality:
            essential_text = ",".join(essential_regs) if essential_regs else "-"
            non_essential_text = ",".join(non_essential_regs) if non_essential_regs else "-"
            essentiality_report_lines.append(
                f"{target}: essential={essential_text}; non_essential={non_essential_text}"
            )
            if annotate_essentiality_comments and (essential_regs or non_essential_regs):
                lines.append(
                    f"# essentiality {target}: essential={essential_text}; non_essential={non_essential_text}"
                )

        if is_exact:
            lines.append(f"${target}:{expr_map[target]}")
        elif regs_to_reveal:
            canalization_template = (
                build_canalization_template(target, regs_to_reveal, canalization_data)
                if apply_canalization_templates
                else None
            )
            if canalization_template is not None:
                lines.append(f"${target}:{canalization_template}")
            else:
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

    return lines, canalization_report_lines, essentiality_report_lines


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
    parser.add_argument(
        "--reveal-exact-functions-percent",
        type=float,
        default=0.0,
        help="Percent of target functions revealed exactly as Boolean rules.",
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
    parser.add_argument(
        "--infer-monotonicity-for-exact",
        action="store_true",
        help="Infer regulation monotonicity/essentiality for exactly revealed Boolean rules and emit AEON edge operators accordingly.",
    )
    parser.add_argument(
        "--positive-edge-op",
        default="->",
        help="Edge operator used for essential positive regulations inferred from exact rules.",
    )
    parser.add_argument(
        "--negative-edge-op",
        default="-|",
        help="Edge operator used for essential negative regulations inferred from exact rules.",
    )
    parser.add_argument(
        "--ambiguous-edge-op",
        default="-?",
        help="Edge operator used for essential but sign-ambiguous regulations inferred from exact rules.",
    )
    parser.add_argument(
        "--infer-canalization-for-exact",
        action="store_true",
        help="Detect canalizing variables for exactly revealed Boolean rules using boolforge.",
    )
    parser.add_argument(
        "--annotate-canalization-comments",
        action="store_true",
        help="Annotate exact revealed rules with canalization comments in the sketch model section.",
    )
    parser.add_argument(
        "--apply-canalization-templates",
        action="store_true",
        help="For symbolic (non-exact) targets, emit a partial canalization template when a visible canalizing regulator is known.",
    )
    parser.add_argument(
        "--canalization-output",
        help="Optional report file for canalization detected in exactly revealed Boolean rules.",
    )
    parser.add_argument(
        "--infer-essentiality",
        action="store_true",
        help="Detect essential and non-essential regulators from .bnet rules using boolforge.",
    )
    parser.add_argument(
        "--apply-essentiality-to-symbolic-supports",
        action="store_true",
        help="For symbolic (non-exact) targets, reveal only essential regulators when essentiality is enabled.",
    )
    parser.add_argument(
        "--annotate-essentiality-comments",
        action="store_true",
        help="Annotate essential/non-essential regulators as comments in the sketch model section.",
    )
    parser.add_argument(
        "--essentiality-output",
        help="Optional report file for essentiality detected from Boolean rules.",
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
    reveal_exact_functions_percent = (
        args.reveal_exact_functions_percent
        if arg_was_passed("--reveal-exact-functions-percent")
        else cfg_get_float(cfg, "reveal_exact_functions_percent", args.reveal_exact_functions_percent)
    )
    seed = args.seed if args.seed is not None else cfg_get_int(cfg, "seed", None)
    edge_op = args.edge_op if arg_was_passed("--edge-op") else cfg_get_str(cfg, "edge_op", args.edge_op)
    hidden_policy = (
        args.hidden_policy
        if arg_was_passed("--hidden-policy")
        else cfg_get_str(cfg, "hidden_policy", args.hidden_policy)
    )
    infer_monotonicity_for_exact = (
        args.infer_monotonicity_for_exact
        if arg_was_passed("--infer-monotonicity-for-exact")
        else str(cfg_get_str(cfg, "infer_monotonicity_for_exact", "false")).strip().lower()
        in {"1", "true", "yes", "on"}
    )
    positive_edge_op = (
        args.positive_edge_op
        if arg_was_passed("--positive-edge-op")
        else cfg_get_str(cfg, "positive_edge_op", args.positive_edge_op)
    )
    negative_edge_op = (
        args.negative_edge_op
        if arg_was_passed("--negative-edge-op")
        else cfg_get_str(cfg, "negative_edge_op", args.negative_edge_op)
    )
    ambiguous_edge_op = (
        args.ambiguous_edge_op
        if arg_was_passed("--ambiguous-edge-op")
        else cfg_get_str(cfg, "ambiguous_edge_op", args.ambiguous_edge_op)
    )
    infer_canalization_for_exact = (
        args.infer_canalization_for_exact
        if arg_was_passed("--infer-canalization-for-exact")
        else str(cfg_get_str(cfg, "infer_canalization_for_exact", "false")).strip().lower()
        in {"1", "true", "yes", "on"}
    )
    annotate_canalization_comments = (
        args.annotate_canalization_comments
        if arg_was_passed("--annotate-canalization-comments")
        else str(cfg_get_str(cfg, "annotate_canalization_comments", "false")).strip().lower()
        in {"1", "true", "yes", "on"}
    )
    apply_canalization_templates = (
        args.apply_canalization_templates
        if arg_was_passed("--apply-canalization-templates")
        else str(cfg_get_str(cfg, "apply_canalization_templates", "false")).strip().lower()
        in {"1", "true", "yes", "on"}
    )
    canalization_output_value = (
        args.canalization_output
        if args.canalization_output is not None
        else cfg_get_str(cfg, "canalization_output", None)
    )
    infer_essentiality = (
        args.infer_essentiality
        if arg_was_passed("--infer-essentiality")
        else str(cfg_get_str(cfg, "infer_essentiality", "false")).strip().lower()
        in {"1", "true", "yes", "on"}
    )
    apply_essentiality_to_symbolic_supports = (
        args.apply_essentiality_to_symbolic_supports
        if arg_was_passed("--apply-essentiality-to-symbolic-supports")
        else str(cfg_get_str(cfg, "apply_essentiality_to_symbolic_supports", "false")).strip().lower()
        in {"1", "true", "yes", "on"}
    )
    annotate_essentiality_comments = (
        args.annotate_essentiality_comments
        if arg_was_passed("--annotate-essentiality-comments")
        else str(cfg_get_str(cfg, "annotate_essentiality_comments", "false")).strip().lower()
        in {"1", "true", "yes", "on"}
    )
    essentiality_output_value = (
        args.essentiality_output
        if args.essentiality_output is not None
        else cfg_get_str(cfg, "essentiality_output", None)
    )

    if not bnet_path or not output_path_value:
        parser.error("Provide --config with bnet/output keys, or pass --bnet and --output.")

    rules = parse_bnet(resolve_user_path(bnet_path, base_dir))
    supports = extract_regulators(rules)
    lines, canalization_report_lines, essentiality_report_lines = build_model_section(
        rules=rules,
        supports=supports,
        reveal_functions_percent=float(reveal_functions_percent),
        reveal_regulators_percent=float(reveal_regulators_percent),
        reveal_exact_functions_percent=float(reveal_exact_functions_percent),
        seed=seed,
        edge_op=str(edge_op),
        hidden_policy=str(hidden_policy),
        infer_monotonicity_for_exact=bool(infer_monotonicity_for_exact),
        positive_edge_op=str(positive_edge_op),
        negative_edge_op=str(negative_edge_op),
        ambiguous_edge_op=str(ambiguous_edge_op),
        infer_canalization_for_exact=bool(infer_canalization_for_exact),
        apply_canalization_templates=bool(apply_canalization_templates),
        annotate_canalization_comments=bool(annotate_canalization_comments),
        infer_essentiality=bool(infer_essentiality),
        apply_essentiality_to_symbolic_supports=bool(apply_essentiality_to_symbolic_supports),
        annotate_essentiality_comments=bool(annotate_essentiality_comments),
    )

    out_path = resolve_user_path(output_path_value, base_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if canalization_output_value:
        canalization_output_path = resolve_user_path(canalization_output_value, base_dir)
        canalization_output_path.parent.mkdir(parents=True, exist_ok=True)
        if canalization_report_lines:
            text = "\n".join(canalization_report_lines) + "\n"
        else:
            text = "NO RESULTS\n"
        canalization_output_path.write_text(text, encoding="utf-8")

    if essentiality_output_value:
        essentiality_output_path = resolve_user_path(essentiality_output_value, base_dir)
        essentiality_output_path.parent.mkdir(parents=True, exist_ok=True)
        if essentiality_report_lines:
            text = "\n".join(essentiality_report_lines) + "\n"
        else:
            text = "NO RESULTS\n"
        essentiality_output_path.write_text(text, encoding="utf-8")

    total_targets = len(supports)
    total_regs = sum(len(v) for v in supports.values())
    print(f"Targets: {total_targets}")
    print(f"Total regulator occurrences in supports: {total_regs}")
    print(f"Reveal functions percent: {reveal_functions_percent}")
    print(f"Reveal regulators percent: {reveal_regulators_percent}")
    print(f"Reveal exact functions percent: {reveal_exact_functions_percent}")
    print(f"Infer monotonicity for exact rules: {infer_monotonicity_for_exact}")
    print(f"Infer canalization for exact rules: {infer_canalization_for_exact}")
    print(f"Apply canalization templates: {apply_canalization_templates}")
    print(f"Infer essentiality: {infer_essentiality}")
    print(f"Apply essentiality to symbolic supports: {apply_essentiality_to_symbolic_supports}")
    if seed is not None:
        print(f"Seed: {seed}")
    print(f"Output: {out_path}")
    if canalization_output_value:
        print(f"Canalization output: {resolve_user_path(canalization_output_value, base_dir)}")
    if essentiality_output_value:
        print(f"Essentiality output: {resolve_user_path(essentiality_output_value, base_dir)}")


if __name__ == "__main__":
    main()
