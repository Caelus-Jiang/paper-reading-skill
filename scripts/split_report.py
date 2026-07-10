#!/usr/bin/env python3
"""Recreate canonical chapter fragments from an existing report."""

from __future__ import annotations

import argparse
from pathlib import Path

from common import atomic_write_text, get_workspace
from report_schema import load_report_schema


MIGRATABLE_MISSING_CHAPTERS = {"00_quicklook.md"}
MIGRATION_PLACEHOLDER = "<!-- PAPER_READING_PLACEHOLDER: complete this new required chapter -->"


def missing_chapter_fragment(chapter: dict) -> str:
    blocks = [chapter["heading"]]
    for heading in chapter.get("subheadings") or []:
        blocks.extend(["", heading, "", MIGRATION_PLACEHOLDER])
    return "\n".join(blocks).rstrip() + "\n"


def split_report(workspace: Path, report_path: Path, overwrite: bool = False) -> Path:
    schema = load_report_schema()
    text = report_path.read_text(encoding="utf-8-sig")
    chapters_dir = workspace / "cache" / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    starts: list[int | None] = []
    for chapter in schema["chapters"]:
        heading = chapter.get("heading")
        if heading is None:
            starts.append(0)
            continue
        marker = f"\n{heading}\n"
        position = text.find(marker)
        if position < 0:
            if text.startswith(heading + "\n"):
                position = 0
            elif chapter["file"] in MIGRATABLE_MISSING_CHAPTERS:
                starts.append(None)
                continue
            else:
                raise ValueError(f"Cannot split report; missing chapter heading: {heading}")
        starts.append(position + (1 if position > 0 else 0))
    for index, chapter in enumerate(schema["chapters"]):
        target = chapters_dir / chapter["file"]
        if target.exists() and not overwrite:
            raise FileExistsError(f"Chapter fragment exists; pass --overwrite-fragments: {target}")
        start = starts[index]
        if start is None:
            fragment = missing_chapter_fragment(chapter)
            print(f"Created migration placeholder for missing chapter: {chapter['heading']}")
        else:
            following = next((value for value in starts[index + 1:] if value is not None), len(text))
            fragment = text[start:following].strip() + "\n"
        atomic_write_text(target, fragment)
    return chapters_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-input", required=True)
    parser.add_argument("--root", default="output")
    parser.add_argument("--overwrite-fragments", action="store_true")
    args = parser.parse_args()
    workspace, ids = get_workspace(Path(args.root).resolve(), args.paper_input)
    report = workspace / f"{ids['arxiv_id']}_阅读报告.md"
    chapters = split_report(workspace, report, args.overwrite_fragments)
    print("Chapter fragments created:", chapters)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
