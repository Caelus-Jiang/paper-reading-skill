#!/usr/bin/env python3
"""Explicit, atomic and provenance-aware Obsidian synchronization."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from common import atomic_write_text, get_workspace, write_json
from report_schema import load_report_schema


IMAGE_LINK_RE = re.compile(r"!\[([^\]]*)\]\(([^)\n]+)\)")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
LOCAL_CONFIG_PATH = Path(__file__).resolve().parents[1] / "paper-reading.local.json"
OBSIDIAN_NOTES_ENV = "OBSIDIAN_PAPER_NOTES_DIR"
OBSIDIAN_IMAGES_ENV = "OBSIDIAN_IMAGE_DIR"


def normalize_markdown_target(target: str) -> str:
    value = target.strip()
    if value.startswith("<") and value.endswith(">"):
        return value[1:-1].strip().replace("\\", "/")
    title_match = re.match(r'^(.*?)(?:\s+["\'][^"\']*["\'])?$', value)
    return (title_match.group(1) if title_match else value).replace("\\", "/")


def format_markdown_target(target: str) -> str:
    normalized = target.replace("\\", "/")
    return f"<{normalized}>" if any(char.isspace() for char in normalized) else normalized


def validate_frontmatter(markdown: str) -> dict:
    match = FRONTMATTER_RE.match(markdown)
    if not match:
        raise ValueError("Refusing to sync a report without YAML frontmatter.")
    data = yaml.safe_load(match.group(1)) or {}
    if not isinstance(data, dict):
        raise ValueError("Report frontmatter must be a YAML mapping.")
    schema = load_report_schema()
    missing = [key for key in schema["frontmatter"]["required_keys"] if key not in data]
    if missing:
        raise ValueError("Refusing to sync incomplete frontmatter; missing: " + ", ".join(missing))
    forbidden = [key for key in schema["frontmatter"]["forbidden_keys"] if key in data]
    if forbidden:
        raise ValueError("Refusing to sync forbidden frontmatter keys: " + ", ".join(forbidden))
    return data


def referenced_images(markdown: str, workspace: Path) -> dict[str, Path]:
    referenced: dict[str, Path] = {}
    for match in IMAGE_LINK_RE.finditer(markdown):
        target = normalize_markdown_target(match.group(2))
        if target.startswith(("http://", "https://", "data:")):
            continue
        source = (workspace / target.lstrip("./")).resolve()
        try:
            source.relative_to(workspace.resolve())
        except ValueError:
            raise ValueError(f"Image target escapes the workspace: {target}") from None
        if not source.is_file():
            raise FileNotFoundError(f"Referenced image does not exist: {source}")
        referenced[target.lstrip("./")] = source
    return referenced


def atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def copy_referenced_images(
    images: dict[str, Path],
    workspace: Path,
    images_dir: Path,
    *,
    dry_run: bool,
) -> dict[str, Path]:
    target_root = images_dir / workspace.name
    copied = {}
    for source_key, source in images.items():
        relative = Path(source_key).relative_to("images") if source_key.startswith("images/") else Path(source.name)
        target = target_root / relative
        if not dry_run:
            atomic_copy(source, target)
        copied[source_key] = target
    return copied


def build_link_map(copied: dict[str, Path], report_target: Path) -> dict[str, str]:
    return {
        source: Path(os.path.relpath(target, start=report_target.parent)).as_posix()
        for source, target in copied.items()
    }


def rewrite_image_links(markdown: str, link_map: dict[str, str], obsidian_embeds: bool) -> str:
    def replace(match: re.Match[str]) -> str:
        alt = match.group(1)
        target = normalize_markdown_target(match.group(2)).lstrip("./")
        if target not in link_map:
            return match.group(0)
        rewritten = link_map[target]
        if obsidian_embeds:
            return f"![[{rewritten}|{alt}]]" if alt else f"![[{rewritten}]]"
        return f"![{alt}]({format_markdown_target(rewritten)})"

    return IMAGE_LINK_RE.sub(replace, markdown)


def load_config() -> dict:
    if not LOCAL_CONFIG_PATH.exists():
        return {}
    return json.loads(LOCAL_CONFIG_PATH.read_text(encoding="utf-8"))


def resolve_dirs(args: argparse.Namespace) -> tuple[Path, Path]:
    config = load_config().get("obsidian", {})
    notes = args.notes_dir or os.environ.get(OBSIDIAN_NOTES_ENV) or config.get("notes_dir")
    images = args.images_dir or os.environ.get(OBSIDIAN_IMAGES_ENV) or config.get("images_dir")
    if not notes or not images:
        if not sys.stdin.isatty():
            raise RuntimeError("Obsidian paths are required in non-interactive mode; pass --notes-dir and --images-dir.")
        notes = notes or input("Obsidian notes directory: ").strip()
        images = images or input("Obsidian images directory: ").strip()
    return Path(notes).expanduser().resolve(), Path(images).expanduser().resolve()


def resolve_source(args: argparse.Namespace) -> tuple[Path, Path]:
    if args.report_path:
        report = Path(args.report_path).expanduser().resolve()
        return report.parent, report
    workspace, ids = get_workspace(Path(args.root).resolve(), args.paper_input)
    report = workspace / f"{ids['arxiv_id']}_阅读报告.md"
    return workspace, report


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize an accepted report into Obsidian.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--paper-input")
    source.add_argument("--report-path")
    parser.add_argument("--root", default="output")
    parser.add_argument("--notes-dir")
    parser.add_argument("--images-dir")
    parser.add_argument("--obsidian-embeds", action="store_true")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing different note after creating a backup.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    workspace, report_source = resolve_source(args)
    if not report_source.is_file():
        raise FileNotFoundError(f"Report not found: {report_source}")
    markdown = report_source.read_text(encoding="utf-8-sig")
    validate_frontmatter(markdown)
    notes_dir, images_dir = resolve_dirs(args)
    report_target = notes_dir / report_source.name

    images = referenced_images(markdown, workspace)
    copied = copy_referenced_images(images, workspace, images_dir, dry_run=args.dry_run)
    rewritten = rewrite_image_links(markdown, build_link_map(copied, report_target), args.obsidian_embeds)

    if report_target.exists() and report_target.read_text(encoding="utf-8-sig") != rewritten:
        if not args.overwrite:
            raise FileExistsError(f"Obsidian note differs; pass --overwrite explicitly: {report_target}")
        if not args.dry_run:
            stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
            atomic_copy(report_target, report_target.with_suffix(report_target.suffix + f".{stamp}.bak"))
    if not args.dry_run:
        notes_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(report_target, rewritten)
        write_json(
            workspace / "logs" / "obsidian_sync.json",
            {
                "synced_at": datetime.now(timezone.utc).isoformat(),
                "source": str(report_source),
                "source_sha256": sha256(report_source),
                "target": str(report_target),
                "images": {key: str(value) for key, value in copied.items()},
            },
        )
    print(("Dry-run" if args.dry_run else "Synced") + f": {report_target}")
    print("Referenced images:", len(copied))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
