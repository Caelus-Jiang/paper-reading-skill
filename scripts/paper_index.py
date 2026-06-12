#!/usr/bin/env python3
"""Paper index manager — maintains a lightweight JSON index of all papers in
the output directory for fast duplicate detection.

Supports two directory layouts:
  1. Standard workspace layout (output/): subdirectories with metadata.json
  2. Flat Markdown layout (Obsidian vault): *_阅读报告.md files (recursive)

Usage:
  # Auto-detect: scan output/ and Obsidian notes dir (from paper-reading.local.json)
  python scripts/paper_index.py --rebuild

  # Scan a specific directory
  python scripts/paper_index.py --root output --rebuild
  python scripts/paper_index.py --root ~/obsidian/papers --rebuild --flat

  # Add or update a single entry (called after pipeline completes)
  python scripts/paper_index.py --root output --add <workspace_dir_name>

  # Query for duplicates by arxiv_id or title
  python scripts/paper_index.py --root output --query-id 2306.13649
  python scripts/paper_index.py --root output --query-title "On-Policy Distillation"
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

INDEX_FILENAME = "paper_index.json"
LOCAL_CONFIG_FILENAME = "paper-reading.local.json"
REPORT_FILENAME_RE = re.compile(r'^(\d{4}\.\d{4,5})_阅读报告\.md$')
TITLE_LINE_RE = re.compile(r'^-\s*论文标题[：:]\s*(.+)', re.MULTILINE)


def _find_project_root() -> Path:
    """Locate the project root by walking up from this script's directory."""
    candidate = Path(__file__).resolve().parent.parent
    if (candidate / LOCAL_CONFIG_FILENAME).exists() or (candidate / "SKILL.md").exists():
        return candidate
    # Fallback: current working directory
    return Path.cwd()


def _load_local_config(project_root: Path) -> Dict:
    """Load paper-reading.local.json from the project root."""
    config_path = project_root / LOCAL_CONFIG_FILENAME
    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _resolve_obsidian_notes_dir(project_root: Path) -> Optional[Path]:
    """Get the Obsidian notes directory from local config or environment."""
    import os
    notes_dir = os.environ.get("OBSIDIAN_PAPER_NOTES_DIR")
    if not notes_dir:
        config = _load_local_config(project_root)
        notes_dir = config.get("obsidian", {}).get("notes_dir")
    if notes_dir:
        resolved = Path(notes_dir).expanduser().resolve()
        if resolved.is_dir():
            return resolved
    return None


def _build_entry_from_metadata(dir_name: str, meta: Dict) -> Dict:
    """Extract only the fields needed for duplicate detection."""
    return {
        "dir_name": dir_name,
        "arxiv_id": meta.get("arxiv_id", ""),
        "title": meta.get("title", ""),
        "workspace_name": meta.get("workspace_name", ""),
        "version": meta.get("version", ""),
        "created_at": meta.get("created_at", ""),
        "input": meta.get("input", ""),
    }


def _extract_title_from_report(report_path: Path) -> str:
    """Read the first ~20 lines of a report Markdown file to extract the title."""
    try:
        # Only read a small portion — title is always near the top
        head = report_path.read_text(encoding="utf-8")[:2000]
        match = TITLE_LINE_RE.search(head)
        return match.group(1).strip() if match else ""
    except OSError:
        return ""


def scan_flat_notes(notes_root: Path) -> List[Dict]:
    """Recursively scan a directory for *_阅读报告.md files (e.g. Obsidian vault).

    Handles both root-level files and files nested in subdirectories like
    Diffusion/, NTP/, 轨迹预测/ etc.
    """
    entries = []
    if not notes_root.is_dir():
        return entries
    for md_file in sorted(notes_root.rglob("*_阅读报告.md")):
        if not md_file.is_file():
            continue
        match = REPORT_FILENAME_RE.match(md_file.name)
        arxiv_id = match.group(1) if match else ""
        title = _extract_title_from_report(md_file)
        relative_path = md_file.relative_to(notes_root).as_posix()
        # category is the parent subdirectory name, empty if at root
        category = md_file.parent.relative_to(notes_root).as_posix()
        if category == ".":
            category = ""
        entries.append({
            "dir_name": md_file.stem,
            "arxiv_id": arxiv_id,
            "title": title,
            "workspace_name": "",
            "version": "",
            "created_at": "",
            "input": "",
            "file_name": md_file.name,
            "relative_path": relative_path,
            "category": category,
        })
    return entries


def scan_all_workspaces(output_root: Path) -> List[Dict]:
    """Scan output_root for subdirectories with metadata.json files and build entries."""
    entries = []
    if not output_root.is_dir():
        return entries
    for candidate in sorted(output_root.iterdir()):
        if not candidate.is_dir():
            continue
        meta_path = candidate / "metadata.json"
        if not meta_path.exists():
            # Directory without metadata — record dir_name only
            entries.append({
                "dir_name": candidate.name,
                "arxiv_id": "",
                "title": "",
                "workspace_name": candidate.name,
                "version": "",
                "created_at": "",
                "input": "",
            })
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        entries.append(_build_entry_from_metadata(candidate.name, meta))
    return entries


def load_index(output_root: Path) -> Dict:
    """Load the index file. Returns empty structure if not found."""
    index_path = output_root / INDEX_FILENAME
    if index_path.exists():
        try:
            return json.loads(index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"updated_at": "", "papers": []}


def save_index(output_root: Path, index_data: Dict) -> None:
    """Write the index file."""
    index_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    index_path = output_root / INDEX_FILENAME
    index_path.write_text(
        json.dumps(index_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def rebuild_index(output_root: Path, flat: bool = False) -> Dict:
    """Full scan and rebuild the index from scratch.

    Args:
        output_root: Directory to scan.
        flat: If True, scan for flat Markdown files (Obsidian layout)
              instead of workspace subdirectories.
    """
    entries = scan_flat_notes(output_root) if flat else scan_all_workspaces(output_root)
    index_data = {"updated_at": "", "papers": entries}
    save_index(output_root, index_data)
    return index_data


def ensure_index(output_root: Path) -> Dict:
    """Load the index if it exists, otherwise rebuild it."""
    index_data = load_index(output_root)
    if index_data["papers"]:
        return index_data
    return rebuild_index(output_root)


def add_entry(output_root: Path, dir_name: str) -> Dict:
    """Add or update a single entry in the index from its metadata.json."""
    index_data = ensure_index(output_root)
    workspace_path = output_root / dir_name
    meta_path = workspace_path / "metadata.json"

    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            meta = {}
    else:
        meta = {}

    new_entry = _build_entry_from_metadata(dir_name, meta)

    # Replace existing entry with same dir_name, or append
    papers = index_data["papers"]
    replaced = False
    for i, paper in enumerate(papers):
        if paper["dir_name"] == dir_name:
            papers[i] = new_entry
            replaced = True
            break
    if not replaced:
        papers.append(new_entry)

    save_index(output_root, index_data)
    return index_data


def query_by_arxiv_id(index_data: Dict, arxiv_id: str) -> List[Dict]:
    """Find all entries matching an arxiv_id."""
    if not arxiv_id:
        return []
    return [
        paper for paper in index_data["papers"]
        if paper.get("arxiv_id") == arxiv_id
    ]


def query_by_title(index_data: Dict, title: str) -> List[Dict]:
    """Find all entries whose title matches (case-insensitive)."""
    if not title:
        return []
    normalized = title.strip().lower()
    return [
        paper for paper in index_data["papers"]
        if (paper.get("title") or "").strip().lower() == normalized
    ]


def query_duplicates(index_data: Dict, arxiv_id: str, title: str) -> List[Dict]:
    """Find entries matching by arxiv_id or title, deduplicated by dir_name."""
    seen_dirs = set()
    results = []
    for match in query_by_arxiv_id(index_data, arxiv_id):
        if match["dir_name"] not in seen_dirs:
            match["match_by"] = "arxiv_id"
            results.append(match)
            seen_dirs.add(match["dir_name"])
    for match in query_by_title(index_data, title):
        if match["dir_name"] not in seen_dirs:
            match["match_by"] = "title"
            results.append(match)
            seen_dirs.add(match["dir_name"])
    return results


def rebuild_all_indexes(project_root: Optional[Path] = None) -> None:
    """Auto-detect output/ and Obsidian directories, rebuild indexes for both."""
    if project_root is None:
        project_root = _find_project_root()

    rebuilt_any = False

    # 1. output/ directory (workspace layout)
    output_dir = Path.cwd() / "output"
    if not output_dir.is_dir():
        output_dir = project_root / "output"
    if output_dir.is_dir():
        index_data = rebuild_index(output_dir, flat=False)
        print(f"✅ output 索引已重建: {output_dir}  ({len(index_data['papers'])} 篇)")
        rebuilt_any = True

    # 2. Obsidian notes directory (flat/recursive layout)
    obsidian_dir = _resolve_obsidian_notes_dir(project_root)
    if obsidian_dir:
        index_data = rebuild_index(obsidian_dir, flat=True)
        print(f"✅ Obsidian 索引已重建: {obsidian_dir}  ({len(index_data['papers'])} 篇)")
        rebuilt_any = True
    else:
        print("ℹ️  未找到 Obsidian 配置，跳过 Obsidian 索引")

    if not rebuilt_any:
        print("⚠️  未找到任何可扫描的目录")


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper index manager.")
    parser.add_argument("--root", default=None,
                        help="Target directory. If omitted with --rebuild, auto-detect output/ and Obsidian dirs")
    parser.add_argument("--rebuild", action="store_true", help="Full scan and rebuild the index")
    parser.add_argument("--flat", action="store_true",
                        help="Scan flat Markdown files (e.g. Obsidian vault) instead of workspace subdirectories")
    parser.add_argument("--add", metavar="DIR_NAME", help="Add/update a single workspace entry")
    parser.add_argument("--query-id", metavar="ARXIV_ID", help="Query by arxiv_id")
    parser.add_argument("--query-title", metavar="TITLE", help="Query by title")
    args = parser.parse_args()

    # --rebuild without --root: auto-detect both output/ and Obsidian
    if args.rebuild and args.root is None:
        rebuild_all_indexes()
        sys.exit(0)

    output_root = Path(args.root or "output").resolve()

    if args.rebuild:
        index_data = rebuild_index(output_root, flat=args.flat)
        layout_label = "扁平 Markdown" if args.flat else "工作区"
        print(f"✅ 索引已重建（{layout_label}模式），共 {len(index_data['papers'])} 篇论文")
        sys.exit(0)

    if args.add:
        index_data = add_entry(output_root, args.add)
        print(f"✅ 已更新索引，共 {len(index_data['papers'])} 篇论文")
        sys.exit(0)

    if args.query_id:
        index_data = ensure_index(output_root)
        matches = query_by_arxiv_id(index_data, args.query_id)
        if matches:
            print(json.dumps(matches, ensure_ascii=False, indent=2))
        else:
            print("未找到匹配的论文")
        sys.exit(0)

    if args.query_title:
        index_data = ensure_index(output_root)
        matches = query_by_title(index_data, args.query_title)
        if matches:
            print(json.dumps(matches, ensure_ascii=False, indent=2))
        else:
            print("未找到匹配的论文")
        sys.exit(0)

    parser.print_help()


if __name__ == "__main__":
    main()
