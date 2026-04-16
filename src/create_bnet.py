#!/usr/bin/env python3
import boolforge as bf
import inspect
import yaml
import sys
from pathlib import Path
import numpy as np
import networkx as nx
import random
import re


HEADER = [
    "# model in BoolNet format",
    "# the header targets, factors is mandatory to be importable in the R package BoolNet",
    "",
    "targets, factors",
]

BOOLFORGE_VAR_RE = re.compile(r"\bx(\d+)\b")
BOOLFORGE_NOT_RE = re.compile(r"\(\s*1\s*-\s*(x\d+)\s*\)")
TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def normalize_boolforge_expression(expr, node_offset=1):
    expr = BOOLFORGE_NOT_RE.sub(lambda match: f"!{match.group(1)}", expr)
    expr = BOOLFORGE_VAR_RE.sub(lambda match: f"x{int(match.group(1)) + node_offset}", expr)
    expr = expr.replace("*", " & ").replace("+", " | ")
    return re.sub(r"\s+", " ", expr).strip()


def simplify_expression(expr):
    try:
        from sympy import Symbol  # type: ignore
        from sympy.logic.boolalg import simplify_logic  # type: ignore
        from sympy.parsing.sympy_parser import parse_expr  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Expression simplification requires the 'sympy' package.") from exc

    variables = sorted({token for token in TOKEN_RE.findall(expr) if token.lower() not in {"true", "false"}})
    local_dict = {name: Symbol(name) for name in variables}

    sympy_expr = expr.replace("!", "~")
    parsed = parse_expr(sympy_expr, local_dict=local_dict, evaluate=False)
    simplified = simplify_logic(parsed, form="dnf", force=True)

    text = str(simplified)
    text = text.replace("~", "!")
    text = text.replace(" & ", " & ").replace(" | ", " | ")
    text = text.replace("True", "1").replace("False", "0")
    return text


def shift_boolforge_var(var_name, node_offset=1):
    return f"x{int(var_name[1:]) + node_offset}"


def normalize_bnet_content(raw_content):
    lines = []
    for raw in raw_content.splitlines():
        line = raw.strip()
        if not line:
            continue
        if "," not in line:
            raise ValueError(f"Invalid BoolForge output line: {raw}")
        target, expr = line.split(",", 1)
        normalized_expr = normalize_boolforge_expression(expr.strip())
        simplified_expr = simplify_expression(normalized_expr)
        lines.append((shift_boolforge_var(target.strip()), simplified_expr))

    width = max(len(target) for target, _ in lines)
    formatted = [f"{target.ljust(width)}, {expr}" for target, expr in lines]
    return "\n".join(HEADER + formatted) + "\n"


def make_acyclic_wiring_topological(N, n, rng_seed=None):
    rng = np.random.default_rng(rng_seed)
    order = list(range(N))
    rng.shuffle(order)
    rank = {node: i for i, node in enumerate(order)}

    I = [[] for _ in range(N)]
    for target in range(N):
        possible = [v for v in range(N) if rank[v] < rank[target]]
        if not possible:
            I[target] = [target]
        else:
            k = min(n, len(possible))
            regulators = rng.choice(possible, size=k, replace=False).tolist()
            I[target] = regulators
    return I


def make_acyclic_wiring_edge_by_edge(N, n, rng_seed=None):
    random.seed(rng_seed)
    G = nx.DiGraph()
    G.add_nodes_from(range(N))
    I = [[] for _ in range(N)]
    in_degree = [0] * N

    all_edges = [(u, v) for u in range(N) for v in range(N) if u != v]
    random.shuffle(all_edges)

    for u, v in all_edges:
        if in_degree[v] < n:
            G.add_edge(u, v)
            if nx.is_directed_acyclic_graph(G):
                I[v].append(u)
                in_degree[v] += 1
            else:
                G.remove_edge(u, v)

    for i in range(N):
        if not I[i]:
            I[i] = [i]

    return I


def filter_boolforge_kwargs(cfg):
    """Keep only kwargs supported by the installed BoolForge version."""
    supported = set(inspect.signature(bf.random_network).parameters)
    filtered = {}
    dropped = []

    for key, value in cfg.items():
        if key in supported:
            filtered[key] = value
        else:
            dropped.append(key)

    if dropped:
        print(
            "Ignoring unsupported BoolForge config keys for this installation: "
            + ", ".join(sorted(dropped))
        )

    return filtered


def main():
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else repo_root / "configs" / "boolforge.yaml"

    with config_path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    output_filename = cfg.pop("output", "outputs/bnet/net.bnet")
    output_path = Path(output_filename)
    if not output_path.is_absolute():
        output_path = (config_path.parent / output_path).resolve()
    acyclic = cfg.pop("acyclic", False)
    acyclic_method = cfg.pop("acyclic_method", "topological")
    cfg = filter_boolforge_kwargs(cfg)

    # BoolForge currently crashes in the non-acyclic generator when
    # AT_LEAST_ONE_REGULATOR_PER_NODE=True, so force the safe setting.
    if not acyclic and cfg.get("AT_LEAST_ONE_REGULATOR_PER_NODE", False):
        cfg["AT_LEAST_ONE_REGULATOR_PER_NODE"] = False
        print("Set AT_LEAST_ONE_REGULATOR_PER_NODE=False because acyclic=False uses the BoolForge random wiring path.")

    if acyclic:
        N = cfg.pop("N")
        n = cfg.pop("n")
        rng_seed = cfg.get("rng", None)

        if acyclic_method == "topological":
            I = make_acyclic_wiring_topological(N, n, rng_seed)
            print("Built acyclic network using topological method (fast).")
        elif acyclic_method == "edge_by_edge":
            I = make_acyclic_wiring_edge_by_edge(N, n, rng_seed)
            print("Built acyclic network using edge-by-edge method (uniform).")
        else:
            print(f"Unknown acyclic_method '{acyclic_method}'. Use 'topological' or 'edge_by_edge'.")
            sys.exit(1)

        bn = bf.random_network(I=I, **cfg)
    else:
        bn = bf.random_network(**cfg)

    bnet_content = normalize_bnet_content(str(bn.to_bnet()))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        f.write(bnet_content)

    print(f"Saved to {output_path}")
    print("\n--- Preview ---")
    print(bnet_content)


if __name__ == "__main__":
    main()
