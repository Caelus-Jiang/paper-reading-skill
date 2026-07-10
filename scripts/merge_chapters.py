#!/usr/bin/env python3
"""Merge canonical chapter fragments and record a reproducible manifest."""

from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from common import atomic_write_text, get_workspace, write_json
from report_schema import DEFAULT_SCHEMA_PATH, load_report_schema


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def merge_workspace(
    workspace: Path,
    report_path: Path,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
    *,
    delete_fragments: bool = True,
    overwrite_report: bool = False,
) -> Path:
    if report_path.exists() and not overwrite_report:
        raise FileExistsError(f"Report exists; pass --overwrite-report to replace it: {report_path}")

    schema = load_report_schema(schema_path)
    chapters_dir = workspace / "cache" / "chapters"
    fragments = []
    parts = []
    for position, chapter in enumerate(schema["chapters"]):
        path = chapters_dir / chapter["file"]
        if not path.exists():
            raise FileNotFoundError(f"Missing chapter fragment: {path}")
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError(f"Empty chapter fragment: {path}")
        parts.append(text)
        fragments.append(
            {
                "position": position,
                "file": chapter["file"],
                "sha256": sha256_text(text),
                "bytes": len(text.encode("utf-8")),
            }
        )

    report_text = "\n\n".join(parts).rstrip() + "\n"
    atomic_write_text(report_path, report_text)
    write_json(
        workspace / "cache" / "chapter_manifest.json",
        {
            "schema_version": schema["schema_version"],
            "schema_path": str(schema_path.resolve()),
            "merged_at": datetime.now(timezone.utc).isoformat(),
            "report": report_path.name,
            "report_sha256": sha256_text(report_text),
            "fragments": fragments,
            "fragments_deleted": delete_fragments,
        },
    )

    if delete_fragments:
        for path in chapters_dir.glob("*.md"):
            path.unlink()
        try:
            chapters_dir.rmdir()
        except OSError:
            pass
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge cache/chapters into the canonical report.")
    parser.add_argument("--paper-input", required=True)
    parser.add_argument("--root", default="output")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA_PATH))
    parser.add_argument("--keep-fragments", action="store_true")
    parser.add_argument("--overwrite-report", action="store_true")
    args = parser.parse_args()

    workspace, ids = get_workspace(Path(args.root).resolve(), args.paper_input)
    report_path = workspace / f"{ids['arxiv_id']}_阅读报告.md"
    merged = merge_workspace(
        workspace,
        report_path,
        Path(args.schema),
        delete_fragments=not args.keep_fragments,
        overwrite_report=args.overwrite_report,
    )
    print("Merged report:", merged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
