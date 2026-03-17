#!/usr/bin/env python3
"""
Validate, run, summarize, and plot a batch of generated sketch experiments.

Input:
- a batch directory like outputs/experiments/batch_20260227_190436
- each case contains sketch files under <case>/sketches/*.aeon

For every sketch, this script:
1) validates that the model/properties are inference-ready
2) extracts model and formulae into prepared files
3) runs the Sketches Rust binary in WSL
4) stores stdout/stderr and witness network
5) writes a CSV summary
6) generates overview plots
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR_DEFAULT = SCRIPT_DIR.parent / "reconstructionExp" / "sketches" / "repository"

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
DYNAMIC_PROPERTY_RE = re.compile(r"#`(.*?)`#")
SKETCH_NAME_RE = re.compile(
    r"^(?P<mode>synchronous|asynchronous)_n(?P<n>\d+)_k(?P<k>\d+)__(?P<level>.+)\.aeon$"
)

KEYWORDS = {
    "true",
    "false",
    "EF",
    "AF",
    "EG",
    "AG",
    "EX",
    "AX",
    "EU",
    "AU",
}


def windows_to_wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    parts = [part.replace("\\", "/") for part in resolved.parts[1:]]
    suffix = "/".join(p.strip("\\/") for p in parts if p not in {resolved.drive, "\\"})
    return f"/mnt/{drive}/{suffix}"


def read_lines(path: Path) -> List[str]:
    return path.read_text(encoding="utf-8").splitlines()


def extract_section(lines: Sequence[str], section_header: str, stop_header: str | None = None) -> List[str]:
    start = None
    for i, line in enumerate(lines):
        if line.strip() == section_header:
            start = i + 1
            break
    if start is None:
        return []

    out: List[str] = []
    for line in lines[start:]:
        stripped = line.strip()
        if stop_header and stripped == stop_header:
            break
        if stripped.startswith("## ") and stripped != section_header and stop_header is None:
            break
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
    return formulae


def extract_model_lines(lines: Sequence[str]) -> List[str]:
    model_lines = extract_section(lines, "## MODEL")
    return [line for line in model_lines if line.strip()]


def parse_model_variables(model_lines: Sequence[str]) -> List[str]:
    variables: List[str] = []
    seen = set()
    for raw in model_lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("$"):
            target = line[1:].split(":", 1)[0].strip()
            if target and target not in seen:
                seen.add(target)
                variables.append(target)
            continue
        parts = line.split()
        if len(parts) >= 3:
            target = parts[-1].strip()
            if target and target not in seen:
                seen.add(target)
                variables.append(target)
    return variables


def validate_model_lines(model_lines: Sequence[str]) -> List[str]:
    issues: List[str] = []
    if not model_lines:
        issues.append("missing model section")
        return issues

    for line in model_lines:
        stripped = line.strip()
        if ": ?" in stripped or stripped.endswith(":?"):
            issues.append("invalid unknown update syntax '?': use omitted updates instead")
    model_vars = parse_model_variables(model_lines)
    if not model_vars:
        issues.append("no model variables could be parsed")
    return issues


def validate_formulae(formulae: Sequence[str], model_vars: Sequence[str]) -> List[str]:
    issues: List[str] = []
    if not formulae:
        issues.append("no dynamic properties extracted")
        return issues

    model_var_set = set(model_vars)
    allowed_hctl_vars = {"x", "y", "z", "a", "b", "c"}

    for idx, formula in enumerate(formulae, start=1):
        tokens = TOKEN_RE.findall(formula)
        for token in tokens:
            if token in KEYWORDS:
                continue
            if token in model_var_set:
                continue
            if token in allowed_hctl_vars:
                continue
            if token.islower() and len(token) == 1:
                continue
            issues.append(f"formula {idx} references unknown variable '{token}'")
            break
    return issues


def parse_metadata_from_name(path: Path) -> Dict[str, str]:
    match = SKETCH_NAME_RE.match(path.name)
    if not match:
        return {"mode": "unknown", "n": "", "k": "", "level": path.stem}
    return match.groupdict()


def prepare_sketch(sketch_path: Path, prepared_dir: Path) -> Dict[str, object]:
    lines = read_lines(sketch_path)
    properties_section = extract_section(lines, "## PROPERTIES", stop_header="## MODEL")
    model_lines = extract_model_lines(lines)
    formulae = extract_formulae_from_properties(properties_section)
    model_vars = parse_model_variables(model_lines)

    issues = []
    issues.extend(validate_model_lines(model_lines))
    issues.extend(validate_formulae(formulae, model_vars))

    prepared_dir.mkdir(parents=True, exist_ok=True)
    model_path = prepared_dir / "prepared_model.aeon"
    formulae_path = prepared_dir / "prepared_formulae.txt"
    model_path.write_text("\n".join(model_lines) + ("\n" if model_lines else ""), encoding="utf-8")
    formulae_path.write_text("\n".join(formulae) + ("\n" if formulae else ""), encoding="utf-8")

    return {
        "model_path": model_path,
        "formulae_path": formulae_path,
        "model_vars": model_vars,
        "formulae_count": len(formulae),
        "issues": issues,
    }


def ensure_wsl_binary(repo_dir: Path, timeout_sec: int) -> None:
    repo_wsl = windows_to_wsl_path(repo_dir)
    command = f"set -euo pipefail; cd {shlex.quote(repo_wsl)}; cargo build --release --bin sketches-inference"
    subprocess.run(
        ["wsl.exe", "bash", "-lc", command],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
    )


def run_inference_wsl(
    repo_dir: Path,
    model_path: Path,
    formulae_path: Path,
    timeout_sec: int,
) -> Tuple[str, str, str]:
    repo_wsl = windows_to_wsl_path(repo_dir)
    model_wsl = windows_to_wsl_path(model_path)
    formulae_wsl = windows_to_wsl_path(formulae_path)
    command = (
        f"set -euo pipefail; cd {shlex.quote(repo_wsl)}; "
        f"./target/release/sketches-inference {shlex.quote(model_wsl)} {shlex.quote(formulae_wsl)} --print-witness"
    )

    completed = subprocess.run(
        ["wsl.exe", "bash", "-lc", command],
        capture_output=True,
        text=True,
        timeout=timeout_sec,
    )
    return completed.stdout, completed.stderr, str(completed.returncode)


def parse_inference_output(stdout: str, stderr: str, return_code: str) -> Dict[str, object]:
    text = stdout + ("\n" + stderr if stderr else "")
    data: Dict[str, object] = {
        "return_code": int(return_code),
        "status": "error" if int(return_code) != 0 else "ok",
        "components": None,
        "symbolic_parameters": None,
        "candidate_networks": None,
        "elapsed_ms": None,
        "witness": "",
    }

    m = re.search(r"Loaded BN model with (\d+) components\.", text)
    if m:
        data["components"] = int(m.group(1))

    m = re.search(r"Model has (\d+) symbolic parameters\.", text)
    if m:
        data["symbolic_parameters"] = int(m.group(1))

    m = re.search(r"([0-9.eE+-]+) consistent candidate networks found in total\.", text)
    if m:
        try:
            data["candidate_networks"] = float(m.group(1))
        except ValueError:
            pass

    m = re.search(r"Elapsed time from the start of this computation: (\d+)ms", text)
    if m:
        data["elapsed_ms"] = int(m.group(1))

    witness_match = re.search(r"witness network:\s*(.*?)\n-------", text, re.DOTALL)
    if witness_match:
        data["witness"] = witness_match.group(1).strip()

    return data


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def plot_summary(rows: Sequence[Dict[str, object]], plots_dir: Path) -> None:
    import matplotlib.pyplot as plt

    def level_order(name: str) -> int:
        if name.startswith("level1"):
            return 1
        if name.startswith("level2"):
            return 2
        if name.startswith("level3"):
            return 3
        return 99

    ordered = sorted(
        rows,
        key=lambda row: (
            str(row["mode"]),
            int(row["n"]) if str(row["n"]).isdigit() else 0,
            int(row["k"]) if str(row["k"]).isdigit() else 0,
            level_order(str(row["level"])),
        ),
    )
    labels = [f"{row['mode'][0].upper()} n{row['n']} k{row['k']}\n{row['level']}" for row in ordered]
    x = list(range(len(ordered)))

    runtime_values = [float(row["elapsed_ms"]) / 1000.0 if row["elapsed_ms"] not in {"", None} else math.nan for row in ordered]
    param_values = [float(row["symbolic_parameters"]) if row["symbolic_parameters"] not in {"", None} else math.nan for row in ordered]
    candidate_values = [float(row["candidate_networks"]) if row["candidate_networks"] not in {"", None} else math.nan for row in ordered]
    status_values = [str(row["status"]) for row in ordered]

    plots_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(16, 6))
    colors = ["#4c78a8" if status == "ok" else "#f58518" if status == "timeout" else "#e45756" for status in status_values]
    ax.bar(x, runtime_values, color=colors)
    ax.set_title("Inference Runtime by Sketch")
    ax.set_ylabel("Seconds")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    fig.tight_layout()
    fig.savefig(plots_dir / "runtime_seconds_by_sketch.png", dpi=200)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(16, 6))
    ax.bar(x, param_values, color="#72b7b2")
    ax.set_title("Symbolic Parameters by Sketch")
    ax.set_ylabel("Count")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    fig.tight_layout()
    fig.savefig(plots_dir / "symbolic_parameters_by_sketch.png", dpi=200)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(16, 6))
    ax.bar(x, candidate_values, color="#54a24b")
    ax.set_title("Candidate Networks by Sketch")
    ax.set_ylabel("Approximate count")
    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    fig.tight_layout()
    fig.savefig(plots_dir / "candidate_networks_by_sketch.png", dpi=200)
    plt.close(fig)

    levels = ["level1_basic", "level2_traces_plus_chains", "level3_full"]
    statuses = ["ok", "timeout", "validation_error", "error"]
    counts = {level: {status: 0 for status in statuses} for level in levels}
    for row in ordered:
        level = str(row["level"])
        status = str(row["status"])
        if level not in counts:
            counts[level] = {s: 0 for s in statuses}
        if status not in counts[level]:
            counts[level][status] = 0
        counts[level][status] += 1

    fig, ax = plt.subplots(figsize=(10, 5))
    bottoms = [0] * len(counts)
    x_levels = list(range(len(counts)))
    level_names = list(counts.keys())
    palette = {
        "ok": "#4c78a8",
        "timeout": "#f58518",
        "validation_error": "#e45756",
        "error": "#b279a2",
    }
    for status in statuses:
        values = [counts[level].get(status, 0) for level in level_names]
        ax.bar(x_levels, values, bottom=bottoms, label=status, color=palette[status])
        bottoms = [bottom + value for bottom, value in zip(bottoms, values)]
    ax.set_title("Inference Outcome Count by Sketch Level")
    ax.set_ylabel("Sketches")
    ax.set_xticks(x_levels)
    ax.set_xticklabels(level_names, rotation=15, ha="right")
    ax.legend()
    fig.tight_layout()
    fig.savefig(plots_dir / "status_counts_by_level.png", dpi=200)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run and summarize inference for a batch of generated sketch experiments.")
    parser.add_argument("--batch-dir", required=True, help="Path to outputs/experiments/batch_<timestamp>.")
    parser.add_argument("--repo-dir", default=str(REPO_DIR_DEFAULT), help="Path to the sketches Rust repository.")
    parser.add_argument("--timeout-sec", type=int, default=180, help="Per-sketch timeout in seconds.")
    parser.add_argument("--build-timeout-sec", type=int, default=600, help="Timeout for cargo build in WSL.")
    parser.add_argument("--skip-run", action="store_true", help="Only validate and prepare inputs; do not run inference.")
    args = parser.parse_args()

    batch_dir = Path(args.batch_dir).resolve()
    repo_dir = Path(args.repo_dir).resolve()
    results_dir = batch_dir / "results"
    prepared_root = results_dir / "prepared"
    raw_root = results_dir / "raw"
    plots_dir = results_dir / "plots"
    summary_path = results_dir / "summary.csv"

    sketch_files = sorted(batch_dir.glob("*\\sketches\\*.aeon"))
    if not sketch_files:
        raise FileNotFoundError(f"No sketch files found under {batch_dir}")

    if not args.skip_run:
        ensure_wsl_binary(repo_dir, timeout_sec=int(args.build_timeout_sec))

    rows: List[Dict[str, object]] = []
    for sketch_path in sketch_files:
        meta = parse_metadata_from_name(sketch_path)
        case_name = sketch_path.parent.parent.name
        sketch_stem = sketch_path.stem
        prepared_dir = prepared_root / case_name / sketch_stem
        raw_dir = raw_root / case_name / sketch_stem

        prepared = prepare_sketch(sketch_path, prepared_dir)
        issues = list(prepared["issues"])  # type: ignore[arg-type]

        row: Dict[str, object] = {
            "sketch_path": str(sketch_path),
            "case_name": case_name,
            "mode": meta["mode"],
            "n": meta["n"],
            "k": meta["k"],
            "level": meta["level"],
            "model_vars": len(prepared["model_vars"]),  # type: ignore[arg-type]
            "formulae_count": prepared["formulae_count"],
            "prepared_model": str(prepared["model_path"]),
            "prepared_formulae": str(prepared["formulae_path"]),
            "validation_issues": " | ".join(issues),
            "status": "validation_error" if issues else "pending",
            "components": "",
            "symbolic_parameters": "",
            "candidate_networks": "",
            "elapsed_ms": "",
            "witness_path": "",
            "output_path": "",
        }

        raw_dir.mkdir(parents=True, exist_ok=True)
        if issues or args.skip_run:
            if args.skip_run and not issues:
                row["status"] = "skipped"
            rows.append(row)
            continue

        try:
            stdout, stderr, return_code = run_inference_wsl(
                repo_dir=repo_dir,
                model_path=prepared["model_path"],  # type: ignore[arg-type]
                formulae_path=prepared["formulae_path"],  # type: ignore[arg-type]
                timeout_sec=int(args.timeout_sec),
            )
            combined_output = stdout + ("\n" + stderr if stderr else "")
            output_path = raw_dir / "inference_output.txt"
            write_text(output_path, combined_output)
            row["output_path"] = str(output_path)

            parsed = parse_inference_output(stdout, stderr, return_code)
            row["status"] = parsed["status"]
            row["components"] = parsed["components"] if parsed["components"] is not None else ""
            row["symbolic_parameters"] = parsed["symbolic_parameters"] if parsed["symbolic_parameters"] is not None else ""
            row["candidate_networks"] = parsed["candidate_networks"] if parsed["candidate_networks"] is not None else ""
            row["elapsed_ms"] = parsed["elapsed_ms"] if parsed["elapsed_ms"] is not None else ""

            witness = str(parsed["witness"]).strip()
            if witness:
                witness_path = raw_dir / "witness.bnet"
                write_text(witness_path, witness + "\n")
                row["witness_path"] = str(witness_path)

        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            combined_output = stdout + ("\n" + stderr if stderr else "")
            output_path = raw_dir / "inference_output.txt"
            write_text(output_path, combined_output)
            row["output_path"] = str(output_path)
            row["status"] = "timeout"

            partial = parse_inference_output(stdout, stderr, "124")
            row["components"] = partial["components"] if partial["components"] is not None else ""
            row["symbolic_parameters"] = partial["symbolic_parameters"] if partial["symbolic_parameters"] is not None else ""
            row["candidate_networks"] = partial["candidate_networks"] if partial["candidate_networks"] is not None else ""
            row["elapsed_ms"] = partial["elapsed_ms"] if partial["elapsed_ms"] is not None else ""

        rows.append(row)

    results_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "sketch_path",
        "case_name",
        "mode",
        "n",
        "k",
        "level",
        "model_vars",
        "formulae_count",
        "prepared_model",
        "prepared_formulae",
        "validation_issues",
        "status",
        "components",
        "symbolic_parameters",
        "candidate_networks",
        "elapsed_ms",
        "witness_path",
        "output_path",
    ]
    with summary_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    plot_summary(rows, plots_dir)

    ok_count = sum(1 for row in rows if row["status"] == "ok")
    timeout_count = sum(1 for row in rows if row["status"] == "timeout")
    validation_count = sum(1 for row in rows if row["status"] == "validation_error")
    print(f"Sketches processed: {len(rows)}")
    print(f"Successful runs: {ok_count}")
    print(f"Timeouts: {timeout_count}")
    print(f"Validation errors: {validation_count}")
    print(f"Summary: {summary_path}")
    print(f"Plots: {plots_dir}")


if __name__ == "__main__":
    main()
