# Sketches Pipeline

Pipeline for generating Boolean networks, traces, sketch parts, and a final sketch file (`.aeon`) that can be used for reconstruction/inference experiments.

This repository contains **only pipeline assets**:
- Python + R scripts
- config files
- examples

It intentionally excludes non-pipeline materials (e.g., diagram source folders from the original workspace).

## What The Pipeline Does

`run_pipeline.py` executes:

1. `create_bnet.py`  
   Create a `.bnet` model (random or from rules file).
2. `generate_traces_from_bnet.R`  
   Generate traces with BoolNet from the `.bnet`.
3. `traces_to_sketch_properties.py`  
   Convert traces to dynamic reachability properties.
4. `bnet_to_sketchStructure.py`  
   Convert `.bnet` support info to sketch `## MODEL`.
5. `attractors_to_sketch_properties.py`  
   Convert BoolNet attractor summary to additional properties.
6. `combine_sketch_parts.py`  
   Combine `## PROPERTIES` + `## MODEL` into one final sketch file.

Final output:
- `outputs/sketch_parts/<bnet_stem>_final_sketch.aeon`

## Requirements

- Windows PowerShell (commands below are PowerShell examples)
- Python 3.10+ (tested with Python 3.13)
- R 4.3+ with package `BoolNet`

## Setup

### 1) Python dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2) R dependencies

```powershell
Rscript .\install_r_packages.R
```

If `Rscript` is not in `PATH`, use full path:

```powershell
"C:\Program Files\R\R-4.3.2\bin\Rscript.exe" .\install_r_packages.R
```

### Optional one-shot setup script

```powershell
.\scripts\setup.ps1 -PythonCmd python -RscriptCmd "C:\Program Files\R\R-4.3.2\bin\Rscript.exe"
```

## Quick Start

From repository root:

```powershell
python .\run_pipeline.py --random --n 5 --k 3 --seed 42 --bnet-output ".\outputs\bnet\net.bnet" --trace-config ".\configs\traces_configuration_example.txt" --rscript-cmd "C:\Program Files\R\R-4.3.2\bin\Rscript.exe"
```

Final sketch location:

```text
outputs/sketch_parts/net_final_sketch.aeon
```

## Rules-File Mode Example

```powershell
python .\run_pipeline.py --input ".\configs\sample_rules.txt" --bnet-output ".\outputs\bnet\from_rules.bnet" --trace-config ".\configs\traces_configuration_example.txt" --rscript-cmd "C:\Program Files\R\R-4.3.2\bin\Rscript.exe"
```

## Example Configs

Additional ready-to-run examples are in:

- `configs/examples/traces_configuration_sync_5x10.txt`
- `configs/examples/traces_configuration_async_5x10.txt`
- `configs/examples/traces_to_sketch_properties_basic.txt`
- `configs/examples/bnet_to_sketchStructure_50_50.txt`

## Full Parameter Documentation

See:

- `CONFIG_REFERENCE.md`

This documents every config key, expected type, default behavior, and effect.

## Repository Structure

```text
.
├─ configs/
│  ├─ examples/
│  ├─ traces_configuration_example.txt
│  ├─ traces_to_sketch_properties_params.txt
│  ├─ bnet_to_sketchStructure_params.txt
│  ├─ fixed_points_from_traces_params.txt
│  ├─ attractors_from_traces_params.txt
│  └─ run_sketch_inference_params.txt
├─ outputs/
├─ create_bnet.py
├─ generate_traces_from_bnet.R
├─ run_pipeline.py
├─ traces_to_sketch_properties.py
├─ bnet_to_sketchStructure.py
├─ attractors_to_sketch_properties.py
├─ fixed_points_from_traces.py
├─ attractors_from_traces.py
├─ combine_sketch_parts.py
├─ run_sketch_inference.py
├─ generate_experiment_sketches.py
├─ run_experiment_batch_inference.py
├─ CONFIG_REFERENCE.md
├─ requirements.txt
└─ install_r_packages.R
```

## Notes

- `run_pipeline.py` is the recommended entry point for standard generation.
- `run_sketch_inference.py` and `run_experiment_batch_inference.py` are for inference execution/reporting workflows.
- Generated outputs are intentionally not versioned (`outputs/` is ignored except `.gitkeep`).
