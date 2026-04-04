# BoolForge Random Boolean Network Generator

Takes a `config.yaml` file and outputs a `.bnet` file.

```
python BOOLFORGE.py config.yaml
```

---

## Parameters

### General
| Parameter | Type | Default | Description |
|---|---|---|---|
| `output` | string | `network.bnet` | Output filename |

### Network Structure
| Parameter | Type | Default | Description |
|---|---|---|---|
| `N` | int | required | Number of nodes |
| `n` | int / float / list | required | In-degree per node (or distribution parameter) |
| `indegree_distribution` | string | `constant` | `constant`, `uniform`, or `poisson` |
| `NO_SELF_REGULATION` | bool | `true` | If `true`, nodes cannot regulate themselves |
| `STRONGLY_CONNECTED` | bool | `false` | If `true`, forces a strongly connected wiring diagram |
| `AT_LEAST_ONE_REGULATOR_PER_NODE` | bool | `false` | If `true`, every node must regulate at least one other node |
| `n_attempts_to_generate_strongly_connected_network` | int | `1000` | Max retries when forcing strong connectivity |

### Update Rules
| Parameter | Type | Default | Description |
|---|---|---|---|
| `bias` | float / list | `0.5` | Probability of output=1 for each truth table entry |
| `absolute_bias` | float / list | `0.0` | Absolute deviation from 0.5 (used when `USE_ABSOLUTE_BIAS: true`) |
| `USE_ABSOLUTE_BIAS` | bool | `true` | Use `absolute_bias` instead of `bias` |
| `depth` | int / list | `0` | Minimum canalizing depth per node |
| `EXACT_DEPTH` | bool | `false` | If `true`, enforces exact (not minimum) canalizing depth |
| `layer_structure` | list | `null` | Explicit canalizing layer structure, e.g. `[1, 2]` |
| `LINEAR` | bool | `false` | If `true`, uses parity (XOR-based) functions for all nodes |
| `ALLOW_DEGENERATE_FUNCTIONS` | bool | `false` | If `true`, allows non-essential input variables (classical NK model) |
| `hamming_weight` | int / list | `null` | Exact number of 1s in each node's truth table |

### Acyclic (DAG) Options
| Parameter | Type | Default | Description |
|---|---|---|---|
| `acyclic` | bool | `false` | If `true`, generates a DAG (no cycles) |
| `acyclic_method` | string | `topological` | `topological` (fast) or `edge_by_edge` (more uniform) |

### Reproducibility
| Parameter | Type | Default | Description |
|---|---|---|---|
| `rng` | int | `null` | Random seed for reproducible results |

---

## Example `config.yaml`

```yaml
output: network.bnet
N: 5
n: 2
indegree_distribution: constant
NO_SELF_REGULATION: true
STRONGLY_CONNECTED: false
AT_LEAST_ONE_REGULATOR_PER_NODE: false
bias: 0.5
depth: 0
EXACT_DEPTH: false
LINEAR: false
ALLOW_DEGENERATE_FUNCTIONS: false
rng: 42
acyclic: false
acyclic_method: topological
```

---

## Notes

- The `cana` module warning on startup is harmless — it is an optional dependency.
- When `acyclic: true`, the parameters `N` and `n` are consumed by the DAG builder and not passed to BoolForge directly.
- When `acyclic: true`, source nodes (nodes with no valid predecessors) receive a self-loop placeholder required by BoolForge — these appear as `xi, (1 - xi)` or similar in the output.
- `STRONGLY_CONNECTED` and `acyclic` are mutually exclusive — a strongly connected network cannot be acyclic (except for N=1).