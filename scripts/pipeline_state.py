#!/usr/bin/env python3
"""Content-aware pipeline stage state for safe resume behavior."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from common import read_json, write_json


STAGE_SPECS = {
    "fetch_sources": {"inputs": [], "outputs": ["raw/abs.html", "raw/paper.pdf"]},
    "extract_references": {
        "inputs": ["raw/source.tar", "raw/ar5iv.html"],
        "outputs": ["cache/references.json"],
    },
    "extract_images": {
        "inputs": ["raw/source.tar", "raw/paper.pdf"],
        "outputs": ["cache/images_manifest.json"],
    },
    "extract_paper_text": {
        "inputs": ["raw/paper.pdf"],
        "outputs": ["cache/paper_text.txt", "cache/paper_text.json"],
    },
    "build_report_skeleton": {
        "inputs": ["metadata.json", "references/report_schema.json"],
        "outputs": ["{report}"],
    },
    "validate_report_text": {"inputs": ["{report}"], "outputs": []},
    "paper_index": {"inputs": ["metadata.json"], "outputs": []},
}


def sha256_path(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return "missing"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def report_relative(workspace: Path) -> str:
    metadata = read_json(workspace / "metadata.json")
    return Path(metadata["report_path"]).name


def resolve_paths(workspace: Path, values: list[str], project_root: Path) -> list[Path]:
    report = report_relative(workspace)
    resolved = []
    for value in values:
        value = value.replace("{report}", report)
        if value.startswith("references/"):
            resolved.append(project_root / value)
        else:
            resolved.append(workspace / value)
    return resolved


def fingerprint(workspace: Path, stage: str, script: Path, project_root: Path) -> tuple[str, dict]:
    spec = STAGE_SPECS[stage]
    metadata = read_json(workspace / "metadata.json")
    inputs = resolve_paths(workspace, spec["inputs"], project_root)
    payload = {
        "stage": stage,
        "paper_id_with_version": metadata.get("paper_id_with_version", ""),
        "script": str(script.resolve()),
        "script_sha256": sha256_path(script),
        "inputs": {str(path): sha256_path(path) for path in inputs},
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), payload


def state_path(workspace: Path, stage: str) -> Path:
    return workspace / "cache" / "pipeline_state" / f"{stage}.json"


def outputs_exist(workspace: Path, stage: str, project_root: Path) -> bool:
    outputs = resolve_paths(workspace, STAGE_SPECS[stage]["outputs"], project_root)
    return all(path.exists() and (not path.is_file() or path.stat().st_size > 0) for path in outputs)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("is-current", "mark", "fingerprint"))
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--stage", required=True, choices=tuple(STAGE_SPECS))
    parser.add_argument("--script", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--command", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    project_root = Path(args.project_root).resolve()
    script = Path(args.script).resolve()
    current, payload = fingerprint(workspace, args.stage, script, project_root)
    if args.action == "fingerprint":
        print(current)
        return 0

    path = state_path(workspace, args.stage)
    if args.action == "is-current":
        if not path.exists() or not outputs_exist(workspace, args.stage, project_root):
            return 1
        previous = read_json(path)
        return 0 if previous.get("fingerprint") == current else 1

    spec = STAGE_SPECS[args.stage]
    outputs = resolve_paths(workspace, spec["outputs"], project_root)
    write_json(
        path,
        {
            "stage": args.stage,
            "fingerprint": current,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "command": args.command,
            "fingerprint_inputs": payload,
            "outputs": {str(output): sha256_path(output) for output in outputs},
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
