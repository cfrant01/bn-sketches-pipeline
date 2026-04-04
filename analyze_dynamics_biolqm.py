#!/usr/bin/env python3
"""
Run bioLQM analyses for fixed points and trap spaces on a .bnet model.

This script stores the raw bioLQM outputs so they can be converted into
Sketches properties by a follow-up step.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_BIOLQM_CMD = str(SCRIPT_DIR / "tools" / "bioLQM" / "bioLQM.cmd") if (SCRIPT_DIR / "tools" / "bioLQM" / "bioLQM.cmd").exists() else "bioLQM"


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


def cfg_get_bool(cfg: Dict[str, str], key: str, default: bool = False) -> bool:
    if key not in cfg:
        return default
    value = cfg[key].strip().lower()
    if value in {"1", "true", "yes", "y"}:
        return True
    if value in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"Invalid boolean for {key}: {cfg[key]}")


def build_biolqm_command(args: argparse.Namespace, analysis_name: str, bnet_path: Path) -> List[str]:
    if args.biolqm_jar:
        return [args.java_cmd, "-jar", args.biolqm_jar, str(bnet_path), "-r", analysis_name]
    return [str(args.biolqm_cmd), str(bnet_path), "-r", analysis_name]


def run_analysis(cmd: List[str], cwd: Path) -> str:
    print("[RUN]", " ".join(f'"{part}"' if " " in part else part for part in cmd))
    result = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
        raise SystemExit(result.returncode)
    return result.stdout


def solve_trapspaces_asp(raw_output: str, python_cmd: str, cwd: Path) -> str:
    lines = [line.rstrip() for line in raw_output.splitlines() if line.strip()]
    if not lines:
        raise ValueError("bioLQM trapspaces output is empty.")
    header = lines[-1].split()
    if not header:
        raise ValueError("Could not parse trap-space header from bioLQM output.")

    asp_lines = lines[:-1]
    with tempfile.NamedTemporaryFile("w", suffix=".lp", delete=False, dir=str(cwd), encoding="utf-8") as handle:
        handle.write("\n".join(asp_lines) + "\n")
        asp_path = Path(handle.name)

    try:
        result = subprocess.run(
            [python_cmd, "-m", "clingo", str(asp_path), "0"],
            cwd=str(cwd),
            text=True,
            capture_output=True,
            check=True,
        )
    finally:
        asp_path.unlink(missing_ok=True)

    hit_re = re.compile(r'hit\("([^"]+)",([01])\)')
    rows: List[str] = []
    current_hits: Dict[str, str] | None = None
    for raw in result.stdout.splitlines():
        stripped = raw.strip()
        if stripped.startswith("Answer:"):
            current_hits = {}
            continue
        if current_hits is None:
            continue
        if stripped in {"SATISFIABLE", "UNSATISFIABLE"} or stripped.startswith("Models"):
            if current_hits:
                row = "".join(current_hits.get(gene, "-") for gene in header)
                rows.append(row)
            current_hits = None
            continue
        for gene, value in hit_re.findall(stripped):
            current_hits[gene] = value

    if current_hits:
        row = "".join(current_hits.get(gene, "-") for gene in header)
        rows.append(row)

    if not rows:
        return "NO RESULTS\n"

    return "\n".join([" ".join(header), *rows, ""]) 


def write_output(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"Wrote: {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run bioLQM fixed-point and trap-space analyses for a .bnet model.")
    parser.add_argument("--config", help="Optional key=value config file.")
    parser.add_argument("--bnet", help="Input .bnet file.")
    parser.add_argument("--fixpoints-output", help="Output file for raw bioLQM fixpoints.")
    parser.add_argument("--trapspaces-output", help="Output file for raw bioLQM trap spaces.")
    parser.add_argument("--biolqm-cmd", default=DEFAULT_BIOLQM_CMD, help="bioLQM executable when not using --biolqm-jar.")
    parser.add_argument("--java-cmd", default="java", help="Java executable used with --biolqm-jar.")
    parser.add_argument("--biolqm-jar", help="Optional path to bioLQM.jar.")
    parser.add_argument("--python-cmd", default=sys.executable, help="Python executable used for the clingo fallback.")
    parser.add_argument("--skip-fixpoints", action="store_true", help="Skip the fixpoints analysis.")
    parser.add_argument("--skip-trapspaces", action="store_true", help="Skip the trapspace analysis.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing them.")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    cwd = Path.cwd()
    cfg = read_kv_config(resolve_user_path(args.config, base_dir, cwd)) if args.config else {}

    args.bnet = args.bnet or cfg.get("bnet")
    args.fixpoints_output = args.fixpoints_output or cfg.get("fixpoints_output")
    args.trapspaces_output = args.trapspaces_output or cfg.get("trapspaces_output")
    args.biolqm_cmd = args.biolqm_cmd if args.biolqm_cmd != DEFAULT_BIOLQM_CMD else cfg.get("biolqm_cmd", args.biolqm_cmd)
    args.java_cmd = args.java_cmd if args.java_cmd != "java" else cfg.get("java_cmd", args.java_cmd)
    args.biolqm_jar = args.biolqm_jar or cfg.get("biolqm_jar")
    if args.config:
        args.skip_fixpoints = args.skip_fixpoints or cfg_get_bool(cfg, "skip_fixpoints", False)
        args.skip_trapspaces = args.skip_trapspaces or cfg_get_bool(cfg, "skip_trapspaces", False)

    if not args.bnet:
        parser.error("Provide --bnet or set bnet in --config.")
    if args.skip_fixpoints and args.skip_trapspaces:
        parser.error("Nothing to do: both fixpoints and trapspaces are skipped.")
    if not args.skip_fixpoints and not args.fixpoints_output:
        parser.error("Provide --fixpoints-output or set fixpoints_output in --config.")
    if not args.skip_trapspaces and not args.trapspaces_output:
        parser.error("Provide --trapspaces-output or set trapspaces_output in --config.")

    return args


def main() -> None:
    args = parse_args()
    base_dir = Path(__file__).resolve().parent
    cwd = Path.cwd()
    bnet_path = resolve_user_path(args.bnet, base_dir, cwd)
    if args.biolqm_jar:
        args.biolqm_jar = str(resolve_user_path(args.biolqm_jar, base_dir, cwd))
    else:
        maybe_biolqm_cmd = Path(str(args.biolqm_cmd))
        if maybe_biolqm_cmd.is_absolute() or any(sep in str(args.biolqm_cmd) for sep in ("\\", "/")):
            args.biolqm_cmd = str(resolve_user_path(str(args.biolqm_cmd), base_dir, cwd))
    fixpoints_output = resolve_user_path(args.fixpoints_output, base_dir, cwd) if args.fixpoints_output else None
    trapspaces_output = resolve_user_path(args.trapspaces_output, base_dir, cwd) if args.trapspaces_output else None

    fixpoints_cmd = build_biolqm_command(args, "fixpoints", bnet_path) if not args.skip_fixpoints else None
    trapspaces_cmd = build_biolqm_command(args, "trapspaces", bnet_path) if not args.skip_trapspaces else None

    if args.dry_run:
        if fixpoints_cmd:
            print(" ".join(f'"{part}"' if " " in part else part for part in fixpoints_cmd))
        if trapspaces_cmd:
            print(" ".join(f'"{part}"' if " " in part else part for part in trapspaces_cmd))
        return

    if fixpoints_cmd and fixpoints_output:
        write_output(fixpoints_output, run_analysis(fixpoints_cmd, cwd))
    if trapspaces_cmd and trapspaces_output:
        trapspaces_raw = run_analysis(trapspaces_cmd, cwd)
        if "% Clingo not found" in trapspaces_raw:
            trapspaces_raw = solve_trapspaces_asp(trapspaces_raw, args.python_cmd, cwd)
        write_output(trapspaces_output, trapspaces_raw)


if __name__ == "__main__":
    main()
