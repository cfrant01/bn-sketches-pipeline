# Config Reference

This document describes the **current active config files** used by the pipeline.

All config files use:

```txt
key = value
```

For the current high-level overview and usage examples, see `README.md`.

## Active Config Files

### `configs/pipeline.txt`
Used by: `run_pipeline.py`

Controls which stage configs are used and which property families are included in the final combined sketch.

Keys:
- `boolforge_config`
- `trace_config`
- `traces_properties_config`
- `structure_config`
- `biolqm_dynamics_config`
- `biolqm_properties_config`
- `combined_sketch_output`
- `include_trace_reachability_properties`
- `include_trace_attractor_candidate_properties`
- `include_trace_cycle_candidate_properties`
- `include_biolqm_fixed_point_properties`
- `include_biolqm_trap_space_properties`

Also supported by the script:
- `existing_bnet`
- `skip_attractor_properties`
- `skip_combine`

### `configs/boolforge.yaml`
Used by: `create_bnet.py`

Current sample keys:
- `output`
- `N`
- `n`
- `indegree_distribution`
- `NO_SELF_REGULATION`
- `STRONGLY_CONNECTED`
- `AT_LEAST_ONE_REGULATOR_PER_NODE`
- `bias`
- `depth`
- `EXACT_DEPTH`
- `LINEAR`
- `ALLOW_DEGENERATE_FUNCTIONS`
- `rng`
- `acyclic`
- `acyclic_method`

### `configs/traces.txt`
Used by: `generate_traces_from_bnet.R`

Keys:
- `num_traces` (alias supported in code: `num_series`)
- `num_steps` (alias supported in code: `num_measurements`)
- `update_type`
- `noise_level`
- `seed`
- `output_dir`
- `output_prefix`
- `output_suffix`
- `write_trajectory_header`
- `write_genes_file`

### `configs/trace_properties.txt`
Used by: `traces_to_sketch_properties.py`

Keys:
- `traces_dir`
- `output`
- `genes`
- `trace_glob`
- `pair_mode`
- `keep_percent`
- `partial_state_size`
- `partial_state_mode`
- `seed`
- `no_dedup`
- `compress_stutter`
- `max_chain_states`
- `property_prefix`
- `start_index`
- `no_properties_header`

Also supported by the script:
- `fixed_point_prefix`
- `cycle_prefix`
- `cycle_lengths`

### `configs/structure.txt`
Used by: `bnet_to_sketchStructure.py`

Keys:
- `bnet`
- `output`
- `reveal_functions_percent`
- `reveal_regulators_percent`
- `reveal_exact_functions_percent`
- `seed`
- `edge_op`
- `hidden_policy`
- `infer_monotonicity_for_exact`
- `positive_edge_op`
- `negative_edge_op`
- `ambiguous_edge_op`

### `configs/dynamics.txt`
Used by: `analyze_dynamics_biolqm.py`

Keys:
- `bnet`
- `fixpoints_output`
- `trapspaces_output`
- `biolqm_cmd`

Also supported by the script:
- `java_cmd`
- `biolqm_jar`
- `skip_fixpoints`
- `skip_trapspaces`

### `configs/dynamics_properties.txt`
Used by: `biolqm_to_sketch_properties.py`

Keys:
- `fixpoints`
- `trapspaces`
- `output`
- `mode`
- `property_prefix_fixed`
- `property_prefix_trap`
- `start_index`
- `include_forbid_extra`
- `no_dedup`
- `no_properties_header`

## Notes

- The repo still contains some older example files and legacy helper scripts from earlier iterations.
- For the current supported workflow, prefer the active config files listed above.
