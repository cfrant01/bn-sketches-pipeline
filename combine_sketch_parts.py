#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import List


def resolve_user_path(value: str, base_dir: Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (base_dir / p)


def read_lines(path: Path) -> List[str]:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return path.read_text(encoding="utf-8").splitlines()


def extract_section(lines: List[str], section_header: str) -> List[str]:
    idx = None
    for i, line in enumerate(lines):
        if line.strip() == section_header:
            idx = i
            break
    if idx is None:
        return list(lines)

    out: List[str] = []
    for line in lines[idx + 1 :]:
        if line.strip().startswith("## ") and line.strip() != section_header:
            break
        out.append(line)
    return out


def trim_trailing_blank_lines(lines: List[str]) -> List[str]:
    out = list(lines)
    while out and out[-1].strip() == "":
        out.pop()
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Combine PROPERTIES and MODEL snippets into one sketch .aeon file.")
    parser.add_argument("--properties", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--no-blank-line", action="store_true")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    properties_path = resolve_user_path(args.properties, base_dir)
    model_path = resolve_user_path(args.model, base_dir)
    output_path = resolve_user_path(args.output, base_dir)

    prop = trim_trailing_blank_lines(extract_section(read_lines(properties_path), "## PROPERTIES"))
    model = trim_trailing_blank_lines(extract_section(read_lines(model_path), "## MODEL"))

    out: List[str] = ["## PROPERTIES", *prop]
    if not args.no_blank_line:
        out.append("")
    out.extend(["## MODEL", *model])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(out) + "\n", encoding="utf-8")

    print(f"Properties source: {properties_path}")
    print(f"Model source: {model_path}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()

