import boolforge as bf
import yaml
import sys
import os
import numpy as np
import networkx as nx
import random
import re
from pathlib import Path

HEADER = [
    "# model in BoolNet format",
    "# the header targets, factors is mandatory to be importable in the R package BoolNet",
    "",
    "targets, factors",
]

BOOLFORGE_VAR_RE = re.compile(r"\bx(\d+)\b")
BOOLFORGE_NOT_RE = re.compile(r"\(\s*1\s*-\s*(x\d+)\s*\)")


def normalize_boolforge_expression(expr, node_offset=1):
    expr = BOOLFORGE_NOT_RE.sub(lambda match: f"!{match.group(1)}", expr)
    expr = BOOLFORGE_VAR_RE.sub(lambda match: f"x{int(match.group(1)) + node_offset}", expr)
    expr = expr.replace("*", " & ").replace("+", " | ")
    return re.sub(r"\s+", " ", expr).strip()


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
        lines.append((shift_boolforge_var(target.strip()), normalize_boolforge_expression(expr.strip())))

    width = max(len(target) for target, _ in lines)
    formatted = [f"{target.ljust(width)}, {expr}" for target, expr in lines]
    return "\n".join(HEADER + formatted) + "\n"

def make_acyclic_wiring_topological(N, n, rng_seed=None):
    """Fast DAG: assign random node order, only allow edges going forward.
    Nodes with fewer available predecessors get as many inputs as possible (min 1)."""
    rng = np.random.default_rng(rng_seed)
    order = list(range(N))
    rng.shuffle(order)
    rank = {node: i for i, node in enumerate(order)}

    I = [[] for _ in range(N)]
    for target in range(N):
        possible = [v for v in range(N) if rank[v] < rank[target]]
        if not possible:
            # No predecessors available — use a self-loop as placeholder
            I[target] = [target]
        else:
            k = min(n, len(possible))
            regulators = rng.choice(possible, size=k, replace=False).tolist()
            I[target] = regulators
    return I

def make_acyclic_wiring_edge_by_edge(N, n, rng_seed=None):
    """Slower but more uniform DAG: add edges one by one, reject if cycle forms."""
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

    # Any node still with no inputs gets a self-loop as placeholder
    for i in range(N):
        if not I[i]:
            I[i] = [i]

    return I

def main():
    script_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else script_dir / "config.yaml"

    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    output_filename = cfg.pop("output", "network.bnet")
    output_path = Path(output_filename)
    if not output_path.is_absolute():
        output_path = (config_path.parent / output_path).resolve()
    acyclic = cfg.pop("acyclic", False)
    acyclic_method = cfg.pop("acyclic_method", "topological")

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
    with open(output_path, "w") as f:
        f.write(bnet_content)

    print(f"Saved to {output_path}")
    print("\n--- Preview ---")
    print(bnet_content)

if __name__ == "__main__":
    main()
