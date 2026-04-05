#!/usr/bin/env python3
"""
Run the pipeline from config files.

Main idea:
- every stage is configured by its own config file
- run_pipeline.py reads one pipeline config that points to those stage configs
- commands are then executed with those configs, without hardcoded per-stage parameters
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_RSCRIPT = str(Path(r"C:\Program Files\R\R-4.3.2\bin\Rscript.exe")) if Path(r"C:\Program Files\R\R-4.3.2\bin\Rscript.exe").exists() else "Rscript"
DEFAULT_BIOLQM_CMD = str(SCRIPT_DIR / "tools" / "bioLQM" / "bioLQM.cmd") if (SCRIPT_DIR / "tools" / "bioLQM" / "bioLQM.cmd").exists() else "bioLQM"
DEFAULT_PIPELINE_CONFIG = str(SCRIPT_DIR / "configs" / "pipeline.txt")


def quote_cmd(parts: list[str]) -> str:
    return " ".join(shlex.quote(p) for p in parts)


def run_cmd(cmd: list[str], cwd: Path) -> None:
    print(f"\n[RUN] {quote_cmd(cmd)}")
    result = subprocess.run(cmd, cwd=str(cwd))
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def resolve_user_path(value: str, base_dir: Path, cwd: Path | None = None) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    if cwd is not None:
        candidate = cwd / path
        if candidate.exists():
            return candidate
    return base_dir / path


def read_kv_config(path: Path) -> Dict[str, str]:
    cfg: Dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    for idx, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{idx} invalid config line (expected key = value): {raw}")
        key, value = line.split("=", 1)
        cfg[key.strip()] = value.strip()
    return cfg


def read_yaml_output_path(path: Path) -> Path:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Reading the BoolForge config requires PyYAML.") from exc
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"BoolForge config must be a YAML mapping: {path}")
    output = data.get("output")
    if not output:
        raise ValueError(f"Missing 'output' in BoolForge config: {path}")
    output_path = Path(str(output))
    if not output_path.is_absolute():
        output_path = (path.parent / output_path).resolve()
    return output_path


def cfg_get_bool(cfg: Dict[str, str], key: str, default: bool = False) -> bool:
    if key not in cfg:
        return default
    value = cfg[key].strip().lower()
    if value in {"1", "true", "yes", "y"}:
        return True
    if value in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"Invalid boolean for {key}: {cfg[key]}")


def filter_dynamic_property_file(
    source: Path,
    target: Path,
    keep_prefixes: Iterable[str],
) -> bool:
    lines = source.read_text(encoding="utf-8").splitlines()
    prefixes = tuple(keep_prefixes)
    filtered: list[str] = []
    kept_any = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#! dynamic_property:"):
            try:
                property_name = stripped.split(":", 2)[1].strip()
            except IndexError:
                property_name = ""
            if property_name.startswith(prefixes):
                filtered.append(line)
                kept_any = True
            continue
        filtered.append(line)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(filtered) + "\n", encoding="utf-8")
    return kept_any


def write_overridden_kv_config(
    source: Path,
    overrides: Dict[str, str],
    cwd: Path,
) -> Path:
    cfg = read_kv_config(source)
    cfg.update(overrides)
    handle = tempfile.NamedTemporaryFile(
        "w",
        suffix=".txt",
        delete=False,
        dir=str(cwd),
        encoding="utf-8",
    )
    with handle:
        for key, value in cfg.items():
            handle.write(f"{key} = {value}\n")
    return Path(handle.name)


def build_create_bnet_command(args: argparse.Namespace, boolforge_config: Path) -> list[str]:
    return [args.python_cmd, str(SCRIPT_DIR / "create_bnet.py"), str(boolforge_config)]


def build_trace_command(args: argparse.Namespace, bnet_output: Path, trace_config: Path) -> list[str]:
    return [
        args.rscript_cmd,
        str(SCRIPT_DIR / "generate_traces_from_bnet.R"),
        "--bnet",
        str(bnet_output),
        "--config",
        str(trace_config),
    ]


def build_trace_properties_command(args: argparse.Namespace, traces_properties_config: Path) -> list[str]:
    return [args.python_cmd, str(SCRIPT_DIR / "traces_to_sketch_properties.py"), "--config", str(traces_properties_config)]


def build_structure_command(args: argparse.Namespace, structure_config: Path) -> list[str]:
    return [args.python_cmd, str(SCRIPT_DIR / "bnet_to_sketchStructure.py"), "--config", str(structure_config)]


def build_biolqm_analysis_command(args: argparse.Namespace, biolqm_dynamics_config: Path) -> list[str]:
    return [args.python_cmd, str(SCRIPT_DIR / "analyze_dynamics_biolqm.py"), "--config", str(biolqm_dynamics_config)]


def build_biolqm_properties_command(args: argparse.Namespace, biolqm_properties_config: Path) -> list[str]:
    return [args.python_cmd, str(SCRIPT_DIR / "biolqm_to_sketch_properties.py"), "--config", str(biolqm_properties_config)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the pipeline from config files.")
    parser.add_argument("--config", default=DEFAULT_PIPELINE_CONFIG, help="Pipeline config file.")
    parser.add_argument("--python-cmd", default=sys.executable, help="Python executable for Python steps.")
    parser.add_argument("--rscript-cmd", default=DEFAULT_RSCRIPT, help="Rscript executable for trace generation.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing them.")
    return parser.parse_args()


def require_cfg_value(cfg: Dict[str, str], key: str, cfg_path: Path) -> str:
    value = cfg.get(key)
    if not value:
        raise ValueError(f"Missing required key '{key}' in pipeline config: {cfg_path}")
    return value


def main() -> None:
    args = parse_args()
    cwd = Path.cwd()
    pipeline_cfg_path = resolve_user_path(args.config, SCRIPT_DIR, cwd)
    pipeline_cfg = read_kv_config(pipeline_cfg_path)

    boolforge_config_value = pipeline_cfg.get("boolforge_config", "").strip()
    boolforge_config = (
        resolve_user_path(boolforge_config_value, SCRIPT_DIR, cwd) if boolforge_config_value else None
    )
    trace_config = resolve_user_path(require_cfg_value(pipeline_cfg, "trace_config", pipeline_cfg_path), SCRIPT_DIR, cwd)
    traces_properties_config = resolve_user_path(require_cfg_value(pipeline_cfg, "traces_properties_config", pipeline_cfg_path), SCRIPT_DIR, cwd)
    structure_config = resolve_user_path(require_cfg_value(pipeline_cfg, "structure_config", pipeline_cfg_path), SCRIPT_DIR, cwd)
    biolqm_dynamics_config = resolve_user_path(require_cfg_value(pipeline_cfg, "biolqm_dynamics_config", pipeline_cfg_path), SCRIPT_DIR, cwd)
    biolqm_properties_config = resolve_user_path(require_cfg_value(pipeline_cfg, "biolqm_properties_config", pipeline_cfg_path), SCRIPT_DIR, cwd)
    combined_sketch_output = resolve_user_path(
        require_cfg_value(pipeline_cfg, "combined_sketch_output", pipeline_cfg_path),
        SCRIPT_DIR,
        cwd,
    )
    existing_bnet = pipeline_cfg.get("existing_bnet", "").strip()
    existing_bnet_path = resolve_user_path(existing_bnet, SCRIPT_DIR, cwd) if existing_bnet else None
    skip_attractor_properties = cfg_get_bool(pipeline_cfg, "skip_attractor_properties", False)
    skip_combine = cfg_get_bool(pipeline_cfg, "skip_combine", False)
    include_trace_reachability_properties = cfg_get_bool(
        pipeline_cfg, "include_trace_reachability_properties", True
    )
    include_trace_attractor_candidate_properties = cfg_get_bool(
        pipeline_cfg, "include_trace_attractor_candidate_properties", True
    )
    include_trace_cycle_candidate_properties = cfg_get_bool(
        pipeline_cfg, "include_trace_cycle_candidate_properties", True
    )
    include_biolqm_fixed_point_properties = cfg_get_bool(
        pipeline_cfg, "include_biolqm_fixed_point_properties", True
    )
    include_biolqm_trap_space_properties = cfg_get_bool(
        pipeline_cfg, "include_biolqm_trap_space_properties", True
    )
    include_canalization_structure_annotations = cfg_get_bool(
        pipeline_cfg, "include_canalization_structure_annotations", False
    )

    trace_cfg = read_kv_config(trace_config)
    traces_props_cfg = read_kv_config(traces_properties_config)
    structure_cfg = read_kv_config(structure_config)
    biolqm_dyn_cfg = read_kv_config(biolqm_dynamics_config)
    biolqm_props_cfg = read_kv_config(biolqm_properties_config)

    if existing_bnet_path is not None:
        bnet_output = existing_bnet_path
    elif boolforge_config is not None:
        bnet_output = read_yaml_output_path(boolforge_config)
    else:
        raise ValueError(
            f"Pipeline config must define either 'existing_bnet' or 'boolforge_config': {pipeline_cfg_path}"
        )
    trace_properties_output = resolve_user_path(require_cfg_value(traces_props_cfg, "output", traces_properties_config), SCRIPT_DIR, cwd)
    structure_output = resolve_user_path(require_cfg_value(structure_cfg, "output", structure_config), SCRIPT_DIR, cwd)
    biolqm_fixpoints_output = resolve_user_path(require_cfg_value(biolqm_dyn_cfg, "fixpoints_output", biolqm_dynamics_config), SCRIPT_DIR, cwd)
    biolqm_trapspaces_output = resolve_user_path(require_cfg_value(biolqm_dyn_cfg, "trapspaces_output", biolqm_dynamics_config), SCRIPT_DIR, cwd)
    attractor_properties_output = resolve_user_path(require_cfg_value(biolqm_props_cfg, "output", biolqm_properties_config), SCRIPT_DIR, cwd)

    create_cmd = build_create_bnet_command(args, boolforge_config) if boolforge_config and existing_bnet_path is None else []
    trace_cmd = build_trace_command(args, bnet_output, trace_config)
    trace_props_cmd = build_trace_properties_command(args, traces_properties_config)
    structure_cmd_config = structure_config
    temp_structure_config: Path | None = None
    if include_canalization_structure_annotations:
        temp_structure_config = write_overridden_kv_config(
            structure_config,
            {
                "infer_canalization_for_exact": "true",
                "annotate_canalization_comments": "true",
            },
            cwd,
        )
        structure_cmd_config = temp_structure_config
    structure_cmd = build_structure_command(args, structure_cmd_config)
    biolqm_analysis_cmd = build_biolqm_analysis_command(args, biolqm_dynamics_config)
    biolqm_properties_cmd = build_biolqm_properties_command(args, biolqm_properties_config)

    filtered_trace_properties_output = trace_properties_output.with_name(
        f"{trace_properties_output.stem}_filtered{trace_properties_output.suffix}"
    )
    filtered_attractor_properties_output = attractor_properties_output.with_name(
        f"{attractor_properties_output.stem}_filtered{attractor_properties_output.suffix}"
    )

    combine_properties: list[str] = []

    print("Pipeline steps:")
    if existing_bnet_path is not None:
        print(f"1) use existing .bnet -> {bnet_output}")
    else:
        print(f"1) create .bnet -> {bnet_output}")
    print(f"2) generate traces using config -> {trace_config}")
    print(f"3) trace properties -> {trace_properties_output}")
    print(f"4) model structure -> {structure_output}")
    print(
        "   canalization annotations in structure -> "
        + ("enabled" if include_canalization_structure_annotations else "disabled")
    )
    if skip_attractor_properties:
        print("5) bioLQM dynamics/property generation -> skipped")
    else:
        print(f"5) bioLQM raw outputs -> {biolqm_fixpoints_output}, {biolqm_trapspaces_output}")
        print(f"6) dynamic properties -> {attractor_properties_output}")
    if skip_combine:
        print("7) combine final sketch -> skipped")
    else:
        print(f"7) combine final sketch -> {combined_sketch_output}")

    if args.dry_run:
        print("\nDry run mode (no execution):")
        if create_cmd:
            print(quote_cmd(create_cmd))
        print(quote_cmd(trace_cmd))
        print(quote_cmd(trace_props_cmd))
        print(quote_cmd(structure_cmd))
        if not skip_attractor_properties:
            print(quote_cmd(biolqm_analysis_cmd))
            print(quote_cmd(biolqm_properties_cmd))
        if not skip_combine:
            print("[combine step will use centralized include flags from pipeline config]")
        return

    if create_cmd:
        run_cmd(create_cmd, cwd)
    run_cmd(trace_cmd, cwd)
    run_cmd(trace_props_cmd, cwd)
    run_cmd(structure_cmd, cwd)
    if not skip_attractor_properties:
        run_cmd(biolqm_analysis_cmd, cwd)
        run_cmd(biolqm_properties_cmd, cwd)

    trace_kept = filter_dynamic_property_file(
        trace_properties_output,
        filtered_trace_properties_output,
        keep_prefixes=[
            *(["reachability_"] if include_trace_reachability_properties else []),
            *(["trace_attractor_candidate_"] if include_trace_attractor_candidate_properties else []),
            *(["trace_cycle_candidate_"] if include_trace_cycle_candidate_properties else []),
        ],
    )
    if trace_kept:
        combine_properties.append(str(filtered_trace_properties_output))

    if not skip_attractor_properties:
        attractor_kept = filter_dynamic_property_file(
            attractor_properties_output,
            filtered_attractor_properties_output,
            keep_prefixes=[
                *(
                    ["fixed_point_"]
                    if include_biolqm_fixed_point_properties
                    else []
                ),
                *(
                    ["trap_space_"]
                    if include_biolqm_trap_space_properties
                    else []
                ),
            ],
        )
        if attractor_kept:
            combine_properties.append(str(filtered_attractor_properties_output))

    if not skip_combine:
        if not combine_properties:
            print("\n[INFO] No property families selected for final combine; skipping combine step.")
        else:
            combine_cmd = [
                args.python_cmd,
                str(SCRIPT_DIR / "combine_sketch_parts.py"),
                "--properties",
                *combine_properties,
                "--model",
                str(structure_output),
                "--output",
                str(combined_sketch_output),
            ]
            run_cmd(combine_cmd, cwd)

    print("\nPipeline completed successfully.")

    if temp_structure_config is not None:
        temp_structure_config.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
