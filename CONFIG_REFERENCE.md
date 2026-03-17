# Config Reference

This document describes all config files used in this repository.

Format for all config files:

```txt
key = value
```

- Empty lines are ignored.
- `#` starts an inline comment.

---

## `configs/traces_configuration_example.txt`
Used by: `generate_traces_from_bnet.R` (and indirectly by `run_pipeline.py`)

| Key | Type | Allowed / Example | Meaning |
|---|---|---|---|
| `num_traces` (alias: `num_series`) | int | `4`, `5`, `20` | Number of trajectories to generate. |
| `num_steps` (alias: `num_measurements`) | int | `8`, `10` | States per trajectory. |
| `update_type` | enum | `synchronous`, `asynchronous` | Update semantics for trace generation. |
| `noise_level` | float | `0.0` | BoolNet noise level. |
| `output_dir` | path | `outputs/traces` | Folder where traces and optional files are written. |
| `output_prefix` | str | `experiment` | Prefix for trace files. |
| `output_suffix` | str | `_modeled.txt`, `.txt` | Suffix for trace files. |
| `write_trajectory_header` | bool | `true`/`false` | If true, writes `>trajectory` line per file. |
| `write_genes_file` | bool | `true`/`false` | If true, writes `genes.txt`. |
| `find_attractors` | bool | `true`/`false` | If true, computes attractors and writes summary. |
| `find_fixed_points` | bool | `true`/`false` | If true, writes fixed-point export. |
| `attractor_update_type` | enum | `synchronous`, `asynchronous` | Dynamics type for attractor computation. |
| `seed` | int | `42` | RNG seed for reproducibility. |

---

## `configs/traces_to_sketch_properties_params.txt`
Used by: `traces_to_sketch_properties.py`

| Key | Type | Allowed / Example | Meaning |
|---|---|---|---|
| `traces_dir` | path | `outputs/traces` | Folder with trace files and usually `genes.txt`. |
| `output` | path | `outputs/sketch_parts/net_trace_properties.aeon` | Output properties snippet path. |
| `genes` | path | optional | Explicit `genes.txt` path; default `<traces_dir>/genes.txt`. |
| `trace_glob` | glob | `experiment*_modeled.txt` | Trace file pattern. |
| `pair_mode` | enum | `consecutive`, `all_pairs`, `chain` | Property generation strategy. |
| `keep_percent` | float | `100`, `50` | Keep this percent of generated properties. |
| `seed` | int | `42` | Seed for reproducible sampling when `keep_percent < 100`. |
| `no_dedup` | bool | `true`/`false` | Keep duplicates instead of deduplicating state pairs/chains. |
| `property_prefix` | str | `reachability`, `trace_chain` | Prefix for property names. |
| `start_index` | int | `1` | Property numbering start. |
| `no_properties_header` | bool | `true`/`false` | Omit `## PROPERTIES` header if true. |

`pair_mode` semantics:
- `consecutive`: one property for each adjacent pair `s_i -> s_{i+1}`
- `all_pairs`: one property for each `i < j` pair
- `chain`: one nested chain property per trajectory

---

## `configs/bnet_to_sketchStructure_params.txt`
Used by: `bnet_to_sketchStructure.py`

| Key | Type | Allowed / Example | Meaning |
|---|---|---|---|
| `bnet` | path | `outputs/bnet/net.bnet` | Input `.bnet` file. |
| `output` | path | `outputs/sketch_parts/net_model_part.aeon` | Output `## MODEL` snippet. |
| `reveal_functions_percent` | float | `100`, `50` | Percent of target functions to reveal. |
| `reveal_regulators_percent` | float | `100`, `50` | Percent of regulators revealed inside revealed functions. |
| `seed` | int | `42` | Seed for reproducible reveal choices. |
| `edge_op` | str | `-??` | AEON edge operator for generated regulator edges. |
| `hidden_policy` | enum | `omit`, `question`, `self` | How to represent hidden/empty-reveal functions. |

Recommended for inference compatibility:
- `hidden_policy = omit`

---

## `configs/fixed_points_from_traces_params.txt`
Used by: `fixed_points_from_traces.py`

| Key | Type | Allowed / Example | Meaning |
|---|---|---|---|
| `traces_dir` | path | `outputs/traces` | Folder containing traces. |
| `output` | path | `outputs/sketch_parts/fixed_points_from_traces.aeon` | Output properties file. |
| `genes` | path | optional | Explicit genes file. |
| `trace_glob` | glob | `experiment*_modeled.txt` | Trace pattern. |
| `min_stable_length` | int | `2` | Number of identical final states required to call fixed-point candidate. |
| `property_prefix` | str | `fixed_point` | Prefix for emitted property names. |
| `start_index` | int | `1` | Property numbering start. |
| `include_forbid_extra` | bool | `true`/`false` | Add extra formula forbidding other fixed points. |
| `no_dedup` | bool | `true`/`false` | Keep duplicates if true. |
| `no_properties_header` | bool | `true`/`false` | Omit header if true. |

---

## `configs/attractors_from_traces_params.txt`
Used by: `attractors_from_traces.py`

| Key | Type | Allowed / Example | Meaning |
|---|---|---|---|
| `traces_dir` | path | `outputs/traces` | Folder containing traces. |
| `output` | path | `outputs/sketch_parts/attractors_from_traces.aeon` | Output properties file. |
| `genes` | path | optional | Explicit genes file. |
| `trace_glob` | glob | `experiment*_modeled.txt` | Trace pattern. |
| `max_cycle_length` | int | `5` | Maximum cycle length considered for suffix-cycle detection. |
| `min_cycle_repeats` | int | `2` | Minimum repeats of suffix cycle required. |
| `exclude_fixed_points` | bool | `true`/`false` | If true, exclude cycle length 1. |
| `property_prefix` | str | `attractor` | Prefix for emitted property names. |
| `start_index` | int | `1` | Property numbering start. |
| `include_forbid_extra` | bool | `true`/`false` | Add extra formula forbidding other attractors. |
| `no_dedup` | bool | `true`/`false` | Keep duplicates if true. |
| `no_properties_header` | bool | `true`/`false` | Omit header if true. |

---

## `configs/run_sketch_inference_params.txt`
Used by: `run_sketch_inference.py`

| Key | Type | Allowed / Example | Meaning |
|---|---|---|---|
| `model_snippet` | path | `outputs/sketch_parts/net_model_part.aeon` | Input model snippet. |
| `properties` | csv paths | `a.aeon,b.aeon` | One or more properties snippet files. |
| `repo_dir` | path | `../reconstructionExp/sketches/repository` | Sketches Rust repo path. |
| `prepared_model_output` | path | `outputs/inference/prepared_model.aeon` | Prepared model output. |
| `prepared_formulae_output` | path | `outputs/inference/prepared_formulae.txt` | Prepared formulae output. |
| `inference_output` | path | `outputs/inference/inference_output.txt` | Captured inference stdout/stderr. |
| `binary_path` | path | optional | Use precompiled binary instead of `cargo run`. |
| `print_witness` | bool | `true`/`false` | Ask inference binary to print witness network. |
| `prepare_only` | bool | `true`/`false` | Build prepared files only, skip execution. |

---

## `configs/sample_rules.txt`
Used by: `create_bnet.py` via `--input`

Accepted rule forms:
- `target = expression`
- `target, expression`
- `target: expression`

BoolNet header line `targets, factors` is optional in the rules file input.

---

## `configs/examples/*`
Runnable example presets for common scenarios.

- `traces_configuration_sync_5x10.txt`
- `traces_configuration_async_5x10.txt`
- `traces_to_sketch_properties_basic.txt`
- `bnet_to_sketchStructure_50_50.txt`

These are intended as starting points for quick runs and teaching/demo usage.
