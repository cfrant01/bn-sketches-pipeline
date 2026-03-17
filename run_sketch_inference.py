#!/usr/bin/env python3
"""
Prepare and run Boolean Network Sketches inference from generated sketch parts.

The Sketches repository binary expects:
1) an AEON model file
2) a text file with HCTL formulae (one formula per line)

This wrapper converts generated snippet files into those two inputs and then
optionally runs the Rust binary.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List


DYNAMIC_PROPERTY_RE = re.compile(r"#`(.*?)`#")


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


def cfg_get_bool(cfg: dict[str, str], key: str, default: bool = False) -> bool:
    if key not in cfg:
        return default
    val = cfg[key].strip().lower()
    if val in {"1", "true", "yes", "y"}:
        return True
    if val in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"Invalid boolean for {key}: {cfg[key]}")


def arg_was_passed(flag: str) -> bool:
    return flag in sys.argv


def resolve_user_path(value: str, base_dir: Path, cwd: Path | None = None) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    if cwd is not None:
        candidate = cwd / path
        if candidate.exists():
            return candidate
    return base_dir / path


def split_csv_paths(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def extract_model_section(lines: List[str]) -> List[str]:
    start = None
    for i, line in enumerate(lines):
        if line.strip() == "## MODEL":
            start = i + 1
            break
    if start is None:
        return [ln for ln in lines if ln.strip()]

    out: List[str] = []
    for line in lines[start:]:
        if line.strip().startswith("## ") and line.strip() != "## MODEL":
            break
        if line.strip():
            out.append(line)
    return out


def extract_formulae_from_properties(lines: Iterable[str]) -> List[str]:
    formulae: List[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        match = DYNAMIC_PROPERTY_RE.search(line)
        if match:
            formulae.append(match.group(1).strip())
            continue
        if line.startswith("#") or line.startswith("## "):
            continue
        # Accept already-plain formula lines too.
        formulae.append(line)
    return formulae


def write_lines(path: Path, lines: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_cmd(cmd: List[str], cwd: Path, capture_path: Path | None = None) -> None:
    print("[RUN]", " ".join(f'"{p}"' if " " in p else p for p in cmd))
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if capture_path is not None:
        capture_path.parent.mkdir(parents=True, exist_ok=True)
        capture_path.write_text(result.stdout + ("\n" + result.stderr if result.stderr else ""), encoding="utf-8")
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    if result.stdout:
        print(result.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare and run Sketches inference from generated sketch parts.")
    parser.add_argument("--config", help="Parameter file (key = value). Recommended.")
    parser.add_argument("--model-snippet", help="MODEL snippet file (e.g. outputs/sketch_parts/net_model_part.aeon).")
    parser.add_argument(
        "--properties",
        nargs="*",
        help="One or more PROPERTIES snippet files. You can also use the config key 'properties' with comma-separated paths.",
    )
    parser.add_argument(
        "--repo-dir",
        default="reconstructionExp/sketches/repository",
        help="Path to the Boolean Network Sketches repository.",
    )
    parser.add_argument(
        "--prepared-model-output",
        help="Path for the prepared AEON model file used for inference.",
    )
    parser.add_argument(
        "--prepared-formulae-output",
        help="Path for the plain formulae file used for inference.",
    )
    parser.add_argument(
        "--inference-output",
        help="Path to save the inference stdout/stderr.",
    )
    parser.add_argument("--cargo-cmd", default="cargo", help="Cargo executable.")
    parser.add_argument(
        "--binary-path",
        help="Optional precompiled sketches_inference executable. If omitted, cargo run is used.",
    )
    parser.add_argument("--print-witness", action="store_true", help="Ask Sketches to print one witness BN.")
    parser.add_argument("--prepare-only", action="store_true", help="Only prepare model/formulae files; do not run inference.")
    parser.add_argument("--dry-run", action="store_true", help="Print the final command without running it.")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    cwd = Path.cwd()
    cfg = read_kv_config(resolve_user_path(args.config, base_dir, cwd)) if args.config else {}

    model_snippet_value = args.model_snippet or cfg_get_str(cfg, "model_snippet")
    if not model_snippet_value:
        parser.error("Provide --model-snippet or config key model_snippet.")

    properties_values: List[str] = []
    if args.properties:
        properties_values = list(args.properties)
    else:
        prop_cfg = cfg_get_str(cfg, "properties")
        if prop_cfg:
            properties_values = split_csv_paths(prop_cfg)
    if not properties_values:
        parser.error("Provide at least one properties snippet via --properties or config key properties.")

    repo_dir = resolve_user_path(args.repo_dir if arg_was_passed("--repo-dir") else cfg_get_str(cfg, "repo_dir", args.repo_dir), base_dir, cwd)

    model_snippet = resolve_user_path(model_snippet_value, base_dir, cwd)
    properties_files = [resolve_user_path(p, base_dir, cwd) for p in properties_values]

    default_prepared_model = base_dir / "outputs" / "inference" / "prepared_model.aeon"
    default_prepared_formulae = base_dir / "outputs" / "inference" / "prepared_formulae.txt"
    default_inference_output = base_dir / "outputs" / "inference" / "inference_output.txt"

    prepared_model_output = resolve_user_path(
        args.prepared_model_output if args.prepared_model_output else cfg_get_str(cfg, "prepared_model_output", str(default_prepared_model)),
        base_dir,
        cwd,
    )
    prepared_formulae_output = resolve_user_path(
        args.prepared_formulae_output if args.prepared_formulae_output else cfg_get_str(cfg, "prepared_formulae_output", str(default_prepared_formulae)),
        base_dir,
        cwd,
    )
    inference_output = resolve_user_path(
        args.inference_output if args.inference_output else cfg_get_str(cfg, "inference_output", str(default_inference_output)),
        base_dir,
        cwd,
    )

    print_witness = args.print_witness if arg_was_passed("--print-witness") else cfg_get_bool(cfg, "print_witness", args.print_witness)
    prepare_only = args.prepare_only if arg_was_passed("--prepare-only") else cfg_get_bool(cfg, "prepare_only", args.prepare_only)

    model_lines = extract_model_section(model_snippet.read_text(encoding="utf-8").splitlines())
    formulae: List[str] = []
    for prop_file in properties_files:
        formulae.extend(extract_formulae_from_properties(prop_file.read_text(encoding="utf-8").splitlines()))

    if not model_lines:
        raise ValueError(f"No model lines extracted from {model_snippet}")
    if not formulae:
        raise ValueError("No formulae extracted from the provided properties files.")

    write_lines(prepared_model_output, model_lines)
    write_lines(prepared_formulae_output, formulae)

    print(f"Prepared model: {prepared_model_output}")
    print(f"Prepared formulae: {prepared_formulae_output}")
    print(f"Formulae count: {len(formulae)}")

    if prepare_only:
        print("Prepare-only mode: skipping inference execution.")
        return

    binary_path_value = args.binary_path if args.binary_path else cfg_get_str(cfg, "binary_path")
    binary_path = resolve_user_path(binary_path_value, base_dir, cwd) if binary_path_value else None

    if binary_path is not None:
        cmd = [str(binary_path), str(prepared_model_output), str(prepared_formulae_output)]
    else:
        cargo_path = shutil.which(args.cargo_cmd)
        if cargo_path is None:
            raise SystemExit(
                "cargo was not found and no --binary-path was provided. "
                "Install Rust/cargo or point --binary-path to a compiled sketches_inference executable."
            )
        cmd = [cargo_path, "run", "--release", "--bin", "sketches_inference", "--", str(prepared_model_output), str(prepared_formulae_output)]
    if print_witness:
        cmd.append("--print-witness")

    if args.dry_run:
        print("[DRY RUN]", " ".join(f'"{p}"' if " " in p else p for p in cmd))
        return

    run_cmd(cmd, repo_dir, capture_path=inference_output)
    print(f"Inference output saved to: {inference_output}")


if __name__ == "__main__":
    main()

