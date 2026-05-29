#!/usr/bin/env python3
import argparse
import os
import re
import shutil
from pathlib import Path

from common import get_workspace


IMAGE_LINK_RE = re.compile(r"!\[([^\]]*)\]\(([^)\n]+)\)")


def normalize_markdown_target(target: str) -> tuple[str, bool]:
    stripped = target.strip()
    if stripped.startswith("<") and stripped.endswith(">"):
        return stripped[1:-1].strip(), True
    return stripped, False


def format_markdown_target(target: str) -> str:
    normalized = target.replace("\\", "/")
    if any(ch.isspace() for ch in normalized):
        return f"<{normalized}>"
    return normalized


def rewrite_image_links(markdown: str, link_map: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        alt_text = match.group(1)
        raw_target = match.group(2)
        target, _ = normalize_markdown_target(raw_target)
        lookup_key = target.replace("\\", "/").lstrip("./")
        if lookup_key not in link_map:
            return match.group(0)
        return f"![{alt_text}]({format_markdown_target(link_map[lookup_key])})"

    return IMAGE_LINK_RE.sub(replace, markdown)


def copy_images(workspace: Path, obsidian_images_dir: Path) -> dict[str, Path]:
    source_images_dir = workspace / "images"
    if not source_images_dir.exists():
        return {}

    target_paper_images_dir = obsidian_images_dir / workspace.name
    target_paper_images_dir.mkdir(parents=True, exist_ok=True)

    copied: dict[str, Path] = {}
    for source in sorted(path for path in source_images_dir.rglob("*") if path.is_file()):
        relative_to_images = source.relative_to(source_images_dir)
        target = target_paper_images_dir / relative_to_images
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied[f"images/{relative_to_images.as_posix()}"] = target
    return copied


def build_link_map(copied_images: dict[str, Path], report_target: Path) -> dict[str, str]:
    note_dir = report_target.parent
    return {
        source_key: Path(os.path.relpath(target, start=note_dir)).as_posix()
        for source_key, target in copied_images.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy a generated report and images into an Obsidian vault.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--notes-dir", required=True, help="Obsidian folder for paper note Markdown files.")
    parser.add_argument("--images-dir", required=True, help="Obsidian folder for copied paper images.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    notes_dir = Path(args.notes_dir).expanduser().resolve()
    images_dir = Path(args.images_dir).expanduser().resolve()

    workspace, ids = get_workspace(root, args.input)
    report_source = workspace / f"{ids['arxiv_id']}_阅读报告.md"
    if not report_source.exists():
        raise FileNotFoundError(f"Report not found: {report_source}")

    notes_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    report_target = notes_dir / report_source.name
    copied_images = copy_images(workspace, images_dir)
    link_map = build_link_map(copied_images, report_target)

    report_text = report_source.read_text(encoding="utf-8-sig")
    rewritten_report = rewrite_image_links(report_text, link_map)
    report_target.write_text(rewritten_report, encoding="utf-8")

    print("Obsidian report synced:", report_target)
    print("Obsidian images synced:", images_dir / workspace.name)
    print(f"Image links rewritten: {len(link_map)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
