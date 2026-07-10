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
from paper_index import (
    FLAT_INDEX_FILENAME,
    load_index,
    load_or_rebuild_flat_index,
    lookup_flat_note,
    rebuild_lookup_maps,
    scan_flat_notes,
    upsert_flat_note,
)
from report_schema import load_report_schema


IMAGE_LINK_RE = re.compile(r"!\[([^\]]*)\]\(([^)\n]+)\)")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
LOCAL_CONFIG_PATH = Path(__file__).resolve().parents[1] / "paper-reading.local.json"
OBSIDIAN_NOTES_ENV = "OBSIDIAN_PAPER_NOTES_DIR"
OBSIDIAN_IMAGES_ENV = "OBSIDIAN_IMAGE_DIR"
RELATED_PAPERS_HEADING = "### 4.5 相关论文补充表"


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


def split_table_row(line: str) -> list[str]:
    content = line.strip().strip("|")
    cells = []
    current = []
    escaped = False
    for character in content:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            current.append(character)
            escaped = True
        elif character == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    cells.append("".join(current).strip())
    return cells


def plain_paper_title(value: str) -> str:
    markdown_link = re.fullmatch(r"\[([^]]+)\]\(https?://[^)]+\)", value.strip())
    if markdown_link:
        return markdown_link.group(1).strip()
    wikilink = re.fullmatch(r"\[\[([^\]]+)\]\]", value.strip())
    if wikilink:
        target = wikilink.group(1)
        return target.split("|", 1)[-1].replace("\\|", "|").strip()
    return value.strip()


def plain_non_link_text(value: str) -> str:
    stripped = value.strip()
    if re.fullmatch(r"https?://\S+", stripped):
        return ""
    markdown_link = re.fullmatch(r"\[([^]]+)\]\(https?://[^)]+\)", stripped)
    return markdown_link.group(1).strip() if markdown_link else stripped


def table_cell(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().replace("|", "\\|")


def _column_index(headers: list[str], *needles: str) -> int | None:
    for index, header in enumerate(headers):
        normalized = re.sub(r"\s+", "", header).casefold()
        if any(needle.casefold() in normalized for needle in needles):
            return index
    return None


def _cell(cells: list[str], index: int | None) -> str:
    return cells[index].strip() if index is not None and index < len(cells) else ""


def rewrite_related_papers_table(markdown: str, index_data: dict, notes_root: Path) -> tuple[str, dict]:
    """Canonicalize §4.5 and inject vault wikilinks only for unique cached matches."""
    heading_match = re.search(rf"(?m)^{re.escape(RELATED_PAPERS_HEADING)}\s*$", markdown)
    stats = {"rows": 0, "matched": 0, "missing": 0, "ambiguous": 0, "matches": []}
    if not heading_match:
        return markdown, stats
    next_heading = re.search(r"(?m)^#{1,3}\s+", markdown[heading_match.end():])
    section_end = heading_match.end() + next_heading.start() if next_heading else len(markdown)
    section = markdown[heading_match.end():section_end]
    lines = section.splitlines()
    table_start = next((index for index, line in enumerate(lines) if line.strip().startswith("|") and line.strip().endswith("|")), None)
    if table_start is None:
        return markdown, stats
    table_end = table_start
    while table_end < len(lines) and lines[table_end].strip().startswith("|") and lines[table_end].strip().endswith("|"):
        table_end += 1
    table_lines = lines[table_start:table_end]
    if len(table_lines) < 2:
        return markdown, stats

    headers = split_table_row(table_lines[0])
    title_index = _column_index(headers, "论文标题", "论文")
    arxiv_index = _column_index(headers, "arxivid", "arxivid", "arxiv")
    author_index = _column_index(headers, "作者/年份", "作者", "年份")
    source_index = _column_index(headers, "来源/类型", "来源", "类型", "venue")
    relation_index = _column_index(headers, "与原论文关系", "关系")
    overview_index = _column_index(headers, "一句话概述", "概述", "证据备注", "备注")
    link_index = _column_index(headers, "核查链接", "网络链接", "链接")

    output = [
        "| 论文标题 | arXiv ID | 作者 / 年份 | 来源 / 类型 | 与原论文关系 | 一句话概述 |",
        "|---|---|---|---|---|---|",
    ]
    for line in table_lines[2:]:
        cells = split_table_row(line)
        if not cells or all(not cell.strip() for cell in cells):
            continue
        raw_title = _cell(cells, title_index)
        title = plain_paper_title(raw_title)
        explicit_id = _cell(cells, arxiv_index)
        legacy_link = _cell(cells, link_index)
        arxiv_match = re.search(
            r"\d{4}\.\d{4,5}(?:v\d+)?",
            f"{explicit_id} {legacy_link} {raw_title} {' '.join(cells)}",
        )
        arxiv_id = arxiv_match.group(0) if arxiv_match else ""
        entry, status = lookup_flat_note(
            index_data,
            notes_root,
            arxiv_id=arxiv_id,
            title=title,
            hydrate_titles_on_miss=not bool(arxiv_id),
        )
        rendered_title = table_cell(title)
        if entry:
            rendered_title = f"[[{entry['wikilink_target']}\\|{table_cell(title)}]]"
            stats["matched"] += 1
            stats["matches"].append(
                {
                    "arxiv_id": arxiv_id,
                    "title": title,
                    "relative_path": entry["relative_path"],
                    "wikilink_target": entry["wikilink_target"],
                }
            )
        else:
            stats[status] = stats.get(status, 0) + 1
        output.append(
            "| " + " | ".join(
                [
                    rendered_title,
                    table_cell(arxiv_id),
                    table_cell(_cell(cells, author_index)),
                    table_cell(plain_non_link_text(_cell(cells, source_index))),
                    table_cell(_cell(cells, relation_index)),
                    table_cell(_cell(cells, overview_index)),
                ]
            ) + " |"
        )
        stats["rows"] += 1

    lines[table_start:table_end] = output
    rewritten_section = "\n".join(lines)
    return markdown[:heading_match.end()] + rewritten_section + markdown[section_end:], stats


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
    parser.add_argument(
        "--rebuild-related-index",
        action="store_true",
        help="Explicitly rescan all Obsidian paper notes before resolving related-paper wikilinks.",
    )
    args = parser.parse_args()

    workspace, report_source = resolve_source(args)
    if not report_source.is_file():
        raise FileNotFoundError(f"Report not found: {report_source}")
    markdown = report_source.read_text(encoding="utf-8-sig")
    frontmatter = validate_frontmatter(markdown)
    notes_dir, images_dir = resolve_dirs(args)
    report_target = notes_dir / report_source.name

    related_index_path = notes_dir / FLAT_INDEX_FILENAME
    if args.dry_run:
        if related_index_path.exists() and not args.rebuild_related_index:
            related_index = load_index(notes_dir, flat=True, index_path=related_index_path)
        else:
            related_index = {
                "schema_version": 2,
                "layout": "flat",
                "root": str(notes_dir),
                "papers": scan_flat_notes(notes_dir),
            }
            rebuild_lookup_maps(related_index)
    else:
        related_index = load_or_rebuild_flat_index(
            notes_dir,
            rebuild=args.rebuild_related_index,
            index_path=related_index_path,
        )

    images = referenced_images(markdown, workspace)
    copied = copy_referenced_images(images, workspace, images_dir, dry_run=args.dry_run)
    rewritten, related_stats = rewrite_related_papers_table(markdown, related_index, notes_dir)
    rewritten = rewrite_image_links(rewritten, build_link_map(copied, report_target), args.obsidian_embeds)

    if report_target.exists() and report_target.read_text(encoding="utf-8-sig") != rewritten:
        if not args.overwrite:
            raise FileExistsError(f"Obsidian note differs; pass --overwrite explicitly: {report_target}")
        if not args.dry_run:
            stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
            atomic_copy(report_target, report_target.with_suffix(report_target.suffix + f".{stamp}.bak"))
    if not args.dry_run:
        notes_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(report_target, rewritten)
        related_index = upsert_flat_note(
            notes_dir,
            report_target,
            metadata=frontmatter,
            index_data=related_index,
            index_path=related_index_path,
        )
        write_json(
            workspace / "logs" / "obsidian_sync.json",
            {
                "synced_at": datetime.now(timezone.utc).isoformat(),
                "source": str(report_source),
                "source_sha256": sha256(report_source),
                "target": str(report_target),
                "images": {key: str(value) for key, value in copied.items()},
                "related_paper_links": related_stats,
                "related_index": {
                    "path": str(related_index_path),
                    "updated_at": related_index.get("updated_at", ""),
                    "paper_count": len(related_index.get("papers", [])),
                },
            },
        )
    print(("Dry-run" if args.dry_run else "Synced") + f": {report_target}")
    print("Referenced images:", len(copied))
    print(
        "Related paper wikilinks: "
        f"{related_stats['matched']} matched, {related_stats['missing']} missing, "
        f"{related_stats['ambiguous']} ambiguous"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
