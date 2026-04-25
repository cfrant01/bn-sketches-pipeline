# Sketches Pipeline

Pipeline for generating Boolean networks, traces, sketch parts, and a final AEON sketch for Boolean-network inference experiments.

The current pipeline supports four sketch-information categories:
- influence graph information
- partially specified Boolean network structure
- function properties, where the sketch can enforce monotonicity, essentiality, and canalization constraints
- dynamic properties from traces and bioLQM

The repository entry point for the full workflow is:

```text
run_pipeline.py
```

The stage scripts it calls live under:

```text
src/
```

## What The Pipeline Produces

The main output is a combined sketch file:

```text
outputs/Final_Sketch/net_final_sketch.aeon
```

That final sketch is assembled from:
- `outputs/sketch_parts/net_trace_properties.aeon`
- `outputs/sketch_parts/net_attractors_properties.aeon`
- `outputs/sketch_parts/net_model_part.aeon`

The `net_model_part.aeon` section can also contain structure-side annotations derived from exact Boolean rules, including:
- essential vs non-essential regulator information
- canalizing regulator comments
- canalization-aware symbolic templates for partially revealed targets

## Pipeline Flow

`run_pipeline.py` executes these stages:

1. `create_bnet.py`
   Build a `.bnet` model from `configs/boolforge.yaml`.
2. `generate_traces_from_bnet.R`
   Simulate traces with BoolNet from the `.bnet`.
3. `traces_to_sketch_properties.py`
   Convert traces into dynamic sketch properties.
4. `bnet_to_sketchStructure.py`
   Convert the `.bnet` into the `## MODEL` section of the sketch, with optional monotonicity, essentiality, and canalization annotations.
5. `analyze_dynamics_biolqm.py`
   Compute raw fixed-point and trap-space outputs with bioLQM.
6. `biolqm_to_sketch_properties.py`
   Convert bioLQM outputs into sketch dynamic properties.
7. `combine_sketch_parts.py`
   Combine the selected property families plus the model section into the final sketch.

## Repository Contents

- `configs/`
  Active pipeline configuration files.
- `outputs/`
  Generated BNet files, traces, sketch parts, combined sketch, and inference artifacts.
- `src/create_bnet.py`
  Create a `.bnet` model from a BoolForge YAML config.
- `src/generate_traces_from_bnet.R`
  Generate traces from a `.bnet` using BoolNet.
- `src/traces_to_sketch_properties.py`
  Turn traces into sketch dynamic properties.
- `src/bnet_to_sketchStructure.py`
  Turn a `.bnet` into the sketch `## MODEL` section.
- `src/analyze_dynamics_biolqm.py`
  Run bioLQM fixed-point and trap-space analyses.
- `src/biolqm_to_sketch_properties.py`
  Turn raw bioLQM outputs into sketch properties.
- `src/combine_sketch_parts.py`
  Merge the sketch parts into one AEON sketch.
- `run_pipeline.py`
  Orchestrate the full flow from configs.

## Requirements

### Python

Tested with Python 3.13 on Windows PowerShell. Install the Python dependencies with:

```powershell
git clone <your-repo-url>
cd PIPELINE-REPO
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

The `requirements.txt` file covers the Python packages used by the pipeline scripts:
- `boolforge`
- `PyYAML`
- `numpy`
- `networkx`
- `sympy`

### R

The trace-generation step requires R plus the `BoolNet` package.

Install it in R with:

```r
install.packages("BoolNet")
```

The default launcher currently looks for:

```text
C:\Program Files\R\R-4.3.2\bin\Rscript.exe
```

If R is installed elsewhere, either:
- edit the R path in `run_pipeline.py`, or
- pass `--rscript-cmd` explicitly when running the pipeline.

### External tools

- Java, because `tools/bioLQM/bioLQM.cmd` launches the bundled `bioLQM` JAR
- `bioLQM` for fixed-point and trap-space analysis
- Rust/Cargo only if you want to run the Boolean Network Sketches inference binaries locally

This repository already includes a Windows `bioLQM` wrapper under:

```text
tools/bioLQM/bioLQM.cmd
```

So for the default configuration, you do not need a separate global `bioLQM` installation. You do still need `java` available on your `PATH`.

### Fresh Clone Checklist

For a new machine, make sure all of the following are available before running the pipeline:
- Python 3.13
- the packages in `requirements.txt`
- R
- the R package `BoolNet`
- Java on `PATH`

You can quickly verify the external tools with:

```powershell
python --version
Rscript --version
java -version
```

## Quick Start

Run the whole pipeline with the default pipeline config (`configs\pipeline.txt`):

```powershell
python run_pipeline.py
```

Or pass the config path explicitly:

```powershell
python run_pipeline.py --config configs\pipeline.txt
```

Note: `--config` expects a real file path. `configs\pipeline` will fail because the shipped config file is [configs/pipeline.txt](c:\Users\35797\OneDrive\Desktop\THESIS\Sketches pipeline\sketches-pipeline-repo\configs\pipeline.txt).

Dry run:

```powershell
python run_pipeline.py --config configs\pipeline.txt --dry-run
```

If your R installation is not at the default path:

```powershell
python run_pipeline.py --config configs\pipeline.txt --rscript-cmd "C:\Path\To\Rscript.exe"
```

After a successful run, the main output is:

```text
outputs/Final_Sketch/net_final_sketch.aeon
```

## Current Sketch Information That Can Be Included

### 1. Influence graph
- revealed regulator-target edges
- fully unknown edges `-??`
- inferred signed edges for exact rules:
  - `->`
  - `-|`
  - `-?`

### 2. Partially specified Boolean network
- exact Boolean update rules for some targets
- symbolic unknown rules for other revealed targets
- partial revealing/hiding of model support
- optional essentiality-aware symbolic supports that keep only essential regulators visible
- optional canalization-aware symbolic templates when a visible regulator is detected as canalizing

### 3. Update-function properties
- monotonicity/sign inference for exactly revealed Boolean rules, encoded directly on AEON edges
- essentiality comments in the `## MODEL` section for exact revealed rules
- canalization comments in the `## MODEL` section for exact revealed rules

### 4. Dynamic properties
- trace-derived reachability properties
- partial-state reachability properties
- trace-derived recurrence / attractor candidates
- trace-derived short cycle candidates
- bioLQM fixed-point properties
- bioLQM trap-space properties

## Config Reference

All active configuration is under `configs/`.

### `configs/pipeline.txt`

Used by: `run_pipeline.py`

Controls which stage configs are used and which property families are included in the final combined sketch.

| Key | Meaning |
|---|---|
| `boolforge_config` | Path to the BoolForge YAML file used by `create_bnet.py`. |
| `trace_config` | Path to the trace-generation config used by `generate_traces_from_bnet.R`. |
| `traces_properties_config` | Path to the trace-to-properties config used by `traces_to_sketch_properties.py`. |
| `structure_config` | Path to the model-structure config used by `bnet_to_sketchStructure.py`. |
| `biolqm_dynamics_config` | Path to the bioLQM raw-analysis config used by `analyze_dynamics_biolqm.py`. |
| `biolqm_properties_config` | Path to the bioLQM property-conversion config used by `biolqm_to_sketch_properties.py`. |
| `combined_sketch_output` | Path of the final combined AEON sketch. |
| `include_trace_reachability_properties` | Include `reachability_*` properties in the final sketch. |
| `include_trace_attractor_candidate_properties` | Include `trace_attractor_candidate_*` properties in the final sketch. |
| `include_trace_cycle_candidate_properties` | Include `trace_cycle_candidate_*` properties in the final sketch. |
| `include_biolqm_fixed_point_properties` | Include `fixed_point_*` properties in the final sketch. |
| `include_biolqm_trap_space_properties` | Include `trap_space_*` properties in the final sketch. |
| `include_essentiality_structure_constraints` | Turn on essentiality detection and annotate/use essential regulators during the structure step. |
| `include_canalization_structure_annotations` | Enable canalization detection/comments during the structure step for exact revealed rules. |

Also supported by `run_pipeline.py`, but not used in the default sample:

| Key | Meaning |
|---|---|
| `existing_bnet` | Skip BNet generation and use an existing `.bnet` file instead. |
| `skip_attractor_properties` | Skip bioLQM analysis and property generation entirely. |
| `skip_combine` | Stop before combining the final sketch. |

### `configs/boolforge.yaml`

Used by: `create_bnet.py`

Controls random BNet generation through BoolForge.

| Key | Meaning |
|---|---|
| `output` | Output `.bnet` path. |
| `N` | Number of nodes. |
| `n` | Maximum indegree used when building the wiring. |
| `indegree_distribution` | BoolForge indegree distribution, e.g. `constant`. |
| `NO_SELF_REGULATION` | Forbid self-regulation in random generation. |
| `STRONGLY_CONNECTED` | Ask BoolForge for a strongly connected graph if supported by the chosen settings. |
| `AT_LEAST_ONE_REGULATOR_PER_NODE` | Require every node to have at least one regulator. |
| `bias` | BoolForge rule-generation bias. |
| `depth` | BoolForge rule depth. |
| `EXACT_DEPTH` | Enforce exact depth if supported. |
| `LINEAR` | Ask for linear-style functions if supported. |
| `ALLOW_DEGENERATE_FUNCTIONS` | Allow degenerate/constant-like generated logic. |
| `rng` | Random seed. |
| `acyclic` | If true, build an acyclic wiring before rule generation. |
| `acyclic_method` | Acyclic wiring strategy: `topological` or `edge_by_edge`. |

Notes:
- `create_bnet.py` currently expects a BoolForge YAML config, not the older text-based random CLI shown in stale docs.
- When `acyclic = true`, the script builds the wiring first and then hands it to BoolForge.

### `configs/traces.txt`

Used by: `generate_traces_from_bnet.R`

Controls trace simulation from the generated `.bnet`.

| Key | Meaning |
|---|---|
| `num_traces` | Number of traces to generate. Alias supported in code: `num_series`. |
| `num_steps` | Number of states per trace. Alias supported in code: `num_measurements`. |
| `update_type` | `synchronous` or `asynchronous`. |
| `noise_level` | BoolNet noise level. |
| `seed` | Random seed. |
| `output_dir` | Directory for trace outputs. |
| `output_prefix` | Prefix for each trace file. |
| `output_suffix` | Suffix for each trace file. |
| `write_trajectory_header` | If true, writes a `>trajectory` header in each trace file. |
| `write_genes_file` | If true, writes `genes.txt` alongside the traces. |

### `configs/trace_properties.txt`

Used by: `traces_to_sketch_properties.py`

Controls how trace files are converted into dynamic sketch properties.

| Key | Meaning |
|---|---|
| `traces_dir` | Directory containing the trace files. |
| `output` | Output AEON properties snippet path. |
| `genes` | Optional explicit path to `genes.txt`. Defaults to `<traces_dir>/genes.txt`. |
| `trace_glob` | Glob used to match trace files. |
| `pair_mode` | Property generation mode: `consecutive`, `all_pairs`, `endpoints`, `chain`, or `milestones`. |
| `keep_percent` | Percentage of generated properties to keep after sampling. |
| `partial_state_size` | If set, project states down to this many genes before property generation. |
| `partial_state_mode` | Gene-selection strategy for partial states: `variance`, `first`, `random`, or `random_per_property`. |
| `seed` | Random seed for sampling and random gene projection. |
| `no_dedup` | If true, keep duplicates instead of deduplicating. |
| `compress_stutter` | Collapse consecutive duplicate states before analysis. |
| `max_chain_states` | Maximum number of states retained in chain-like modes. |
| `property_prefix` | Prefix for reachability property names. |
| `start_index` | Starting index for numbering properties. |
| `no_properties_header` | If true, omit the `## PROPERTIES` header. |

Also supported by the current script, with built-in defaults:

| Key | Meaning |
|---|---|
| `fixed_point_prefix` | Prefix used for singleton-tail recurrence candidates. Default is `trace_attractor_candidate`. |
| `cycle_prefix` | Prefix used for cycle candidates. Default is `trace_cycle_candidate`. |
| `cycle_lengths` | Comma-separated cycle lengths to detect in trace tails. Default is `2,3`. |

### `configs/structure.txt`

Used by: `bnet_to_sketchStructure.py`

Controls which parts of the generated BNet become visible in the sketch `## MODEL` section.

| Key | Meaning |
|---|---|
| `bnet` | Input `.bnet` file. |
| `output` | Output AEON model snippet path. |
| `reveal_functions_percent` | Percentage of target functions for which support information is revealed. |
| `reveal_regulators_percent` | Percentage of regulators shown for support-revealed targets. |
| `reveal_exact_functions_percent` | Percentage of target functions whose exact Boolean rules are copied into the sketch. |
| `seed` | Random seed for reveal choices. |
| `edge_op` | Default AEON edge operator for unconstrained edges, usually `-??`. |
| `hidden_policy` | How to represent functions with nothing revealed: `omit`, `question`, or `self`. |
| `infer_monotonicity_for_exact` | If true, infer regulator signs for exactly revealed rules and write `->`, `-|`, or `-?` edges. |
| `positive_edge_op` | Edge operator used for inferred positive monotone regulation. |
| `negative_edge_op` | Edge operator used for inferred negative monotone regulation. |
| `ambiguous_edge_op` | Edge operator used for inferred essential but sign-ambiguous regulation. |
| `infer_essentiality` | If true, detect essential and non-essential regulators from exact Boolean rules. |
| `apply_essentiality_to_symbolic_supports` | If true, symbolic supports only reveal essential regulators when essentiality is enabled. |
| `annotate_essentiality_comments` | If true, write essential/non-essential regulator summaries as comments in the `## MODEL` section. |
| `essentiality_output` | Path for the essentiality report file. |
| `infer_canalization_for_exact` | If true, detect canalizing variables for exactly revealed rules using BoolForge. |
| `apply_canalization_templates` | If true, use canalization-aware symbolic templates for non-exact targets when possible. |
| `annotate_canalization_comments` | If true, write detected canalization as comments in the `## MODEL` section. |
| `canalization_output` | Path for the canalization report file. |

### `configs/dynamics.txt`

Used by: `analyze_dynamics_biolqm.py`

Controls the raw bioLQM analysis step.

| Key | Meaning |
|---|---|
| `bnet` | Input `.bnet` file. |
| `fixpoints_output` | Output file for raw fixed-point results. |
| `trapspaces_output` | Output file for raw trap-space results. |
| `biolqm_cmd` | Path to the bioLQM executable or wrapper script. |
| `java_cmd` | Java executable to use when calling a JAR directly. |
| `biolqm_jar` | Optional path to `bioLQM.jar`. |
| `skip_fixpoints` | Skip fixed-point analysis. |
| `skip_trapspaces` | Skip trap-space analysis. |

### `configs/dynamics_properties.txt`

Used by: `biolqm_to_sketch_properties.py`

Controls conversion from raw bioLQM outputs into sketch properties.

| Key | Meaning |
|---|---|
| `fixpoints` | Path to raw fixed-point output. |
| `trapspaces` | Path to raw trap-space output. |
| `output` | Output AEON properties snippet path. |
| `mode` | Which property families to emit: `fixed-points`, `trap-spaces`, or `both`. |
| `property_prefix_fixed` | Prefix for emitted fixed-point properties. |
| `property_prefix_trap` | Prefix for emitted trap-space properties. |
| `start_index` | Starting index for numbering. |
| `include_forbid_extra` | Emit additional forbid-extra constraints. Usually keep this `false` unless you know you want them. |
| `no_dedup` | If true, keep duplicate properties. |
| `no_properties_header` | If true, omit the `## PROPERTIES` header. |

## Inference Helper

`run_sketch_inference.py` is available when you want to convert generated sketch parts into:
- a pure AEON model file, and
- a plain text file with one HCTL formula per line

before running the Boolean Network Sketches inference binary.

It accepts either CLI flags or a key-value config with:
- `model_snippet`
- `properties`
- `repo_dir`
- `prepared_model_output`
- `prepared_formulae_output`
- `inference_output`
- `binary_path`
- `print_witness`
- `prepare_only`

## Known External Assumptions

- Java must be installed and available on `PATH`
- the bundled `tools/bioLQM/` directory must remain present if you use the default config
- R must have the `BoolNet` package installed
- inference execution requires a local clone/build of the Boolean Network Sketches Rust repository

## Notes

- `compress_stutter = true` is usually the right default for trace-derived properties.
- Singleton traces are currently turned into trace-derived recurrence / attractor-candidate properties, not hard fixed-point claims.
- If a generated BNet contains direct contradictions like `x_i = !x_i`, bioLQM may correctly report no fixed points.
- `bnet_to_sketchStructure.py` may print `The module cana cannot be found...` on some environments through the BoolForge stack. The pipeline still works without `cana`; that warning only indicates optional functionality is unavailable.
