#!/usr/bin/env python3
"""
Generate a batch of Boolean-network sketch experiments.

Requested default experiment set:
- synchronous traces for (n=3, k=2), (n=5, k=3), (n=7, k=4)
- asynchronous traces for the same network sizes
- 5 traces per case, 10 steps per trace
- 3 sketch levels per case, from simple to final

Outputs are written under:
    outputs/experiments/batch_<timestamp>/
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, List


SCRIPT_DIR = Path(__file__).resolve().parent
PYTHON = sys.executable
DEFAULT_RSCRIPT = Path(r"C:\Program Files\R\R-4.3.2\bin\Rscript.exe")

CASES = [
    ("synchronous", 3, 2),
    ("synchronous", 5, 3),
    ("synchronous", 7, 4),
    ("asynchronous", 3, 2),
    ("asynchronous", 5, 3),
    ("asynchronous", 7, 4),
]


def run_cmd(cmd: List[str], cwd: Path) -> None:
    print("[RUN]", " ".join(f'"{part}"' if " " in part else part for part in cmd))
    result = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    if result.stdout:
        print(result.stdout)


def write_kv(path: Path, pairs: Iterable[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key} = {value}" for key, value in pairs]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def combine_sections(output_path: Path, properties_files: List[Path], model_file: Path) -> None:
    def extract(path: Path, header: str) -> List[str]:
        lines = path.read_text(encoding="utf-8").splitlines()
        start = None
        for i, line in enumerate(lines):
            if line.strip() == header:
                start = i + 1
                break
        if start is None:
            return [line for line in lines if line.strip()]

        out: List[str] = []
        for line in lines[start:]:
            if line.strip().startswith("## ") and line.strip() != header:
                break
            out.append(line)
        while out and not out[-1].strip():
            out.pop()
        return out

    prop_lines: List[str] = []
    for prop_file in properties_files:
        section = extract(prop_file, "## PROPERTIES")
        if prop_lines and section and section[0].strip():
            prop_lines.append("")
        prop_lines.extend(section)

    model_lines = extract(model_file, "## MODEL")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output = ["## PROPERTIES", *prop_lines, "", "## MODEL", *model_lines]
    output_path.write_text("\n".join(output) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the requested sync/async sketch experiment batch.")
    parser.add_argument("--output-root", help="Optional explicit output root. Defaults to outputs/experiments/batch_<timestamp>.")
    parser.add_argument("--seed-base", type=int, default=100, help="Base seed used to derive deterministic case seeds.")
    parser.add_argument("--num-traces", type=int, default=5)
    parser.add_argument("--num-steps", type=int, default=10)
    parser.add_argument("--rscript-cmd", default=str(DEFAULT_RSCRIPT), help="Path to Rscript.exe.")
    parser.add_argument("--dry-run", action="store_true", help="Create configs only; skip external tool execution.")
    args = parser.parse_args()

    output_root = (
        Path(args.output_root)
        if args.output_root
        else SCRIPT_DIR / "outputs" / "experiments" / f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    output_root.mkdir(parents=True, exist_ok=True)

    rscript_cmd = Path(args.rscript_cmd)
    if not args.dry_run and not rscript_cmd.exists():
        raise FileNotFoundError(f"Rscript executable not found: {rscript_cmd}")

    for case_index, (update_type, n, k) in enumerate(CASES, start=1):
        case_name = f"{update_type}_n{n}_k{k}"
        case_dir = output_root / case_name
        config_dir = case_dir / "configs"
        generated_dir = case_dir / "generated"
        bnet_dir = generated_dir / "bnet"
        traces_dir = generated_dir / "traces"
        parts_dir = generated_dir / "sketch_parts"
        sketches_dir = case_dir / "sketches"

        for directory in [config_dir, bnet_dir, traces_dir, parts_dir, sketches_dir]:
            directory.mkdir(parents=True, exist_ok=True)

        case_seed = int(args.seed_base) + case_index
        bnet_path = bnet_dir / f"{case_name}.bnet"

        trace_cfg = config_dir / "trace_generation.txt"
        write_kv(
            trace_cfg,
            [
                ("num_traces", str(args.num_traces)),
                ("num_steps", str(args.num_steps)),
                ("update_type", update_type),
                ("noise_level", "0.0"),
                ("output_dir", str(traces_dir)),
                ("output_prefix", "experiment"),
                ("output_suffix", "_modeled.txt"),
                ("write_trajectory_header", "false"),
                ("write_genes_file", "true"),
                ("find_attractors", "true"),
                ("find_fixed_points", "true"),
                ("attractor_update_type", update_type),
                ("seed", str(case_seed)),
            ],
        )

        level1_model_cfg = config_dir / "model_level1.txt"
        level2_model_cfg = config_dir / "model_level2.txt"
        level3_model_cfg = config_dir / "model_level3.txt"

        write_kv(
            level1_model_cfg,
            [
                ("bnet", str(bnet_path)),
                ("output", str(parts_dir / "model_level1.aeon")),
                ("reveal_functions_percent", "50"),
                ("reveal_regulators_percent", "50"),
                ("seed", str(case_seed)),
                ("edge_op", "-??"),
                ("hidden_policy", "omit"),
            ],
        )
        write_kv(
            level2_model_cfg,
            [
                ("bnet", str(bnet_path)),
                ("output", str(parts_dir / "model_level2.aeon")),
                ("reveal_functions_percent", "100"),
                ("reveal_regulators_percent", "50"),
                ("seed", str(case_seed)),
                ("edge_op", "-??"),
                ("hidden_policy", "omit"),
            ],
        )
        write_kv(
            level3_model_cfg,
            [
                ("bnet", str(bnet_path)),
                ("output", str(parts_dir / "model_level3.aeon")),
                ("reveal_functions_percent", "100"),
                ("reveal_regulators_percent", "100"),
                ("seed", str(case_seed)),
                ("edge_op", "-??"),
                ("hidden_policy", "omit"),
            ],
        )

        level1_trace_cfg = config_dir / "trace_props_level1.txt"
        level2_trace_cfg = config_dir / "trace_props_level2.txt"
        level2_chain_cfg = config_dir / "trace_chain_level2.txt"
        level3_trace_cfg = config_dir / "trace_props_level3.txt"
        level3_chain_cfg = config_dir / "trace_chain_level3.txt"
        level3_fp_cfg = config_dir / "fixed_points_level3.txt"
        level3_attr_cfg = config_dir / "attractors_level3.txt"

        write_kv(
            level1_trace_cfg,
            [
                ("traces_dir", str(traces_dir)),
                ("output", str(parts_dir / "trace_properties_level1.aeon")),
                ("trace_glob", "experiment*_modeled.txt"),
                ("pair_mode", "consecutive"),
                ("keep_percent", "50"),
                ("seed", str(case_seed)),
                ("property_prefix", "reachability"),
                ("start_index", "1"),
            ],
        )
        write_kv(
            level2_trace_cfg,
            [
                ("traces_dir", str(traces_dir)),
                ("output", str(parts_dir / "trace_properties_level2.aeon")),
                ("trace_glob", "experiment*_modeled.txt"),
                ("pair_mode", "consecutive"),
                ("keep_percent", "100"),
                ("seed", str(case_seed)),
                ("property_prefix", "reachability"),
                ("start_index", "1"),
            ],
        )
        write_kv(
            level2_chain_cfg,
            [
                ("traces_dir", str(traces_dir)),
                ("output", str(parts_dir / "trace_chains_level2.aeon")),
                ("trace_glob", "experiment*_modeled.txt"),
                ("pair_mode", "chain"),
                ("keep_percent", "100"),
                ("seed", str(case_seed)),
                ("property_prefix", "trace_chain"),
                ("start_index", "1"),
            ],
        )
        write_kv(
            level3_trace_cfg,
            [
                ("traces_dir", str(traces_dir)),
                ("output", str(parts_dir / "trace_properties_level3.aeon")),
                ("trace_glob", "experiment*_modeled.txt"),
                ("pair_mode", "consecutive"),
                ("keep_percent", "100"),
                ("seed", str(case_seed)),
                ("property_prefix", "reachability"),
                ("start_index", "1"),
            ],
        )
        write_kv(
            level3_chain_cfg,
            [
                ("traces_dir", str(traces_dir)),
                ("output", str(parts_dir / "trace_chains_level3.aeon")),
                ("trace_glob", "experiment*_modeled.txt"),
                ("pair_mode", "chain"),
                ("keep_percent", "100"),
                ("seed", str(case_seed)),
                ("property_prefix", "trace_chain"),
                ("start_index", "1"),
            ],
        )
        write_kv(
            level3_fp_cfg,
            [
                ("traces_dir", str(traces_dir)),
                ("output", str(parts_dir / "fixed_points_level3.aeon")),
                ("trace_glob", "experiment*_modeled.txt"),
                ("min_stable_length", "2"),
                ("property_prefix", "fixed_point"),
                ("start_index", "1"),
                ("include_forbid_extra", "true"),
            ],
        )
        write_kv(
            level3_attr_cfg,
            [
                ("traces_dir", str(traces_dir)),
                ("output", str(parts_dir / "attractors_level3.aeon")),
                ("trace_glob", "experiment*_modeled.txt"),
                ("max_cycle_length", "5"),
                ("min_cycle_repeats", "2"),
                ("property_prefix", "attractor"),
                ("start_index", "1"),
                ("include_forbid_extra", "true"),
            ],
        )

        create_bnet_cmd = [
            PYTHON,
            str(SCRIPT_DIR / "create_bnet.py"),
            "--random",
            "--n",
            str(n),
            "--k",
            str(k),
            "--seed",
            str(case_seed),
            "--output",
            str(bnet_path),
        ]
        trace_cmd = [
            str(rscript_cmd),
            str(SCRIPT_DIR / "generate_traces_from_bnet.R"),
            "--bnet",
            str(bnet_path),
            "--config",
            str(trace_cfg),
        ]
        model_cmds = [
            [PYTHON, str(SCRIPT_DIR / "bnet_to_sketchStructure.py"), "--config", str(level1_model_cfg)],
            [PYTHON, str(SCRIPT_DIR / "bnet_to_sketchStructure.py"), "--config", str(level2_model_cfg)],
            [PYTHON, str(SCRIPT_DIR / "bnet_to_sketchStructure.py"), "--config", str(level3_model_cfg)],
        ]
        props_cmds = [
            [PYTHON, str(SCRIPT_DIR / "traces_to_sketch_properties.py"), "--config", str(level1_trace_cfg)],
            [PYTHON, str(SCRIPT_DIR / "traces_to_sketch_properties.py"), "--config", str(level2_trace_cfg)],
            [PYTHON, str(SCRIPT_DIR / "traces_to_sketch_properties.py"), "--config", str(level2_chain_cfg)],
            [PYTHON, str(SCRIPT_DIR / "traces_to_sketch_properties.py"), "--config", str(level3_trace_cfg)],
            [PYTHON, str(SCRIPT_DIR / "traces_to_sketch_properties.py"), "--config", str(level3_chain_cfg)],
            [PYTHON, str(SCRIPT_DIR / "fixed_points_from_traces.py"), "--config", str(level3_fp_cfg)],
            [PYTHON, str(SCRIPT_DIR / "attractors_from_traces.py"), "--config", str(level3_attr_cfg)],
        ]

        print(f"=== {case_name} ===")
        if not args.dry_run:
            run_cmd(create_bnet_cmd, SCRIPT_DIR)
            run_cmd(trace_cmd, SCRIPT_DIR)
            for cmd in model_cmds:
                run_cmd(cmd, SCRIPT_DIR)
            for cmd in props_cmds:
                run_cmd(cmd, SCRIPT_DIR)

        combine_sections(
            sketches_dir / f"{case_name}__level1_basic.aeon",
            [parts_dir / "trace_properties_level1.aeon"],
            parts_dir / "model_level1.aeon",
        )
        combine_sections(
            sketches_dir / f"{case_name}__level2_traces_plus_chains.aeon",
            [parts_dir / "trace_properties_level2.aeon", parts_dir / "trace_chains_level2.aeon"],
            parts_dir / "model_level2.aeon",
        )
        combine_sections(
            sketches_dir / f"{case_name}__level3_full.aeon",
            [
                parts_dir / "trace_properties_level3.aeon",
                parts_dir / "trace_chains_level3.aeon",
                parts_dir / "fixed_points_level3.aeon",
                parts_dir / "attractors_level3.aeon",
            ],
            parts_dir / "model_level3.aeon",
        )

    print(f"Batch output root: {output_root}")


if __name__ == "__main__":
    main()
