#!/usr/bin/env python3
"""Finalize a paper-reading report with ordered checks and Obsidian sync."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run final paper-reading report acceptance checks.")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--paper-input", help="arXiv URL/id or workspace name used to locate the report.")
    source_group.add_argument("--report-path", help="Direct path to the Markdown report.")
    parser.add_argument("--root", default="output", help="Root output directory used with --paper-input.")
    parser.add_argument("--notes-dir", help="Obsidian folder for paper note Markdown files.")
    parser.add_argument("--images-dir", help="Obsidian folder for copied paper images.")
    parser.add_argument(
        "--no-obsidian",
        action="store_true",
        help="Do not sync to Obsidian when the user explicitly requested no sync.",
    )
    return parser.parse_args()


def append_source_args(command: list[str], args: argparse.Namespace) -> None:
    if args.paper_input:
        command.extend(["--paper-input", args.paper_input, "--root", args.root])
        return
    command.extend(["--report-path", args.report_path])


def run_step(label: str, command: list[str]) -> None:
    print(f"[finalize] {label}", flush=True)
    subprocess.run(command, check=True)


def main() -> int:
    args = parse_args()

    validate_command = [sys.executable, str(SCRIPT_DIR / "validate_report_text.py")]
    append_source_args(validate_command, args)
    run_step("validate UTF-8 text", validate_command)

    quality_command = [sys.executable, str(SCRIPT_DIR / "check_report_quality.py")]
    append_source_args(quality_command, args)
    run_step("run strict report quality checks", quality_command)

    if args.no_obsidian:
        print("[finalize] Obsidian sync intentionally disabled by explicit user request.")
        return 0

    sync_command = [sys.executable, str(SCRIPT_DIR / "sync_obsidian.py")]
    append_source_args(sync_command, args)
    if args.notes_dir:
        sync_command.extend(["--notes-dir", args.notes_dir])
    if args.images_dir:
        sync_command.extend(["--images-dir", args.images_dir])
    run_step("sync report and images to Obsidian", sync_command)

    print("[finalize] report acceptance complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
