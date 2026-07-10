#!/usr/bin/env python3
"""Run acceptance checks, then optionally perform explicit Obsidian sync."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finalize a paper-reading report.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--paper-input")
    source.add_argument("--report-path")
    parser.add_argument("--root", default="output")
    sync = parser.add_mutually_exclusive_group()
    sync.add_argument("--sync-obsidian", action="store_true", help="Explicitly enable Obsidian sync after validation.")
    sync.add_argument("--no-obsidian", action="store_true", help="Deprecated compatibility flag; sync is disabled by default.")
    parser.add_argument("--notes-dir")
    parser.add_argument("--images-dir")
    parser.add_argument("--obsidian-overwrite", action="store_true")
    parser.add_argument("--obsidian-dry-run", action="store_true")
    parser.add_argument("--rebuild-related-index", action="store_true")
    return parser.parse_args()


def append_source(command: list[str], args: argparse.Namespace) -> None:
    if args.paper_input:
        command.extend(["--paper-input", args.paper_input, "--root", args.root])
    else:
        command.extend(["--report-path", args.report_path])


def run(label: str, command: list[str]) -> None:
    print(f"[finalize] {label}", flush=True)
    subprocess.run(command, check=True)


def main() -> int:
    args = parse_args()
    encoding = [sys.executable, str(SCRIPT_DIR / "validate_report_text.py")]
    append_source(encoding, args)
    run("validate UTF-8 text", encoding)

    quality = [sys.executable, str(SCRIPT_DIR / "check_report_quality.py"), "--require-chapter-manifest"]
    append_source(quality, args)
    run("run schema-driven report acceptance", quality)

    if not args.sync_obsidian:
        print("[finalize] validation complete; Obsidian sync is disabled by default")
        return 0

    sync = [sys.executable, str(SCRIPT_DIR / "sync_obsidian.py")]
    append_source(sync, args)
    if args.notes_dir:
        sync.extend(["--notes-dir", args.notes_dir])
    if args.images_dir:
        sync.extend(["--images-dir", args.images_dir])
    if args.obsidian_overwrite:
        sync.append("--overwrite")
    if args.obsidian_dry_run:
        sync.append("--dry-run")
    if args.rebuild_related_index:
        sync.append("--rebuild-related-index")
    run("sync accepted report to Obsidian", sync)
    print("[finalize] report acceptance and explicit sync complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
