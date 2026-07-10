#!/usr/bin/env python3
"""Incremental indexes for pipeline workspaces and Obsidian paper notes."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import yaml


INDEX_FILENAME = "paper_index.json"
FLAT_INDEX_FILENAME = ".paper-reading-index.json"
INDEX_SCHEMA_VERSION = 2
LOCAL_CONFIG_FILENAME = "paper-reading.local.json"
REPORT_FILENAME_RE = re.compile(r"^(\d{4}\.\d{4,5})_阅读报告\.md$")
ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?", re.I)
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
TITLE_LINE_RE = re.compile(r"^-\s*论文标题[：:]\s*(.+)", re.MULTILINE)


def normalize_title(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title or "").casefold()
    return "".join(character for character in normalized if character.isalnum())


def base_arxiv_id(value: str) -> str:
    match = ARXIV_ID_RE.search(value or "")
    return match.group(1) if match else ""


def _find_project_root() -> Path:
    candidate = Path(__file__).resolve().parent.parent
    return candidate if (candidate / "SKILL.md").exists() else Path.cwd()


def _load_local_config(project_root: Path) -> Dict:
    path = project_root / LOCAL_CONFIG_FILENAME
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _resolve_obsidian_notes_dir(project_root: Path) -> Optional[Path]:
    notes_dir = os.environ.get("OBSIDIAN_PAPER_NOTES_DIR") or _load_local_config(project_root).get("obsidian", {}).get("notes_dir")
    if not notes_dir:
        return None
    resolved = Path(notes_dir).expanduser().resolve()
    return resolved if resolved.is_dir() else None


def _extract_report_metadata(report_path: Path) -> Dict[str, str]:
    try:
        head = report_path.read_text(encoding="utf-8-sig")[:8192]
        match = FRONTMATTER_RE.match(head)
        if match:
            data = yaml.safe_load(match.group(1)) or {}
            if isinstance(data, dict):
                return {
                    "title": str(data.get("title") or "").strip(),
                    "arxiv_id": str(data.get("arxiv_id") or "").strip(),
                }
        legacy = TITLE_LINE_RE.search(head)
        return {"title": legacy.group(1).strip() if legacy else "", "arxiv_id": ""}
    except (OSError, yaml.YAMLError):
        return {"title": "", "arxiv_id": ""}


def _build_entry_from_metadata(dir_name: str, metadata: Dict) -> Dict:
    return {
        "dir_name": dir_name,
        "arxiv_id": metadata.get("arxiv_id", ""),
        "title": metadata.get("title", ""),
        "workspace_name": metadata.get("workspace_name", ""),
        "version": metadata.get("version", ""),
        "created_at": metadata.get("created_at", ""),
        "input": metadata.get("input", ""),
    }


def _build_flat_entry(note: Path, notes_root: Path, metadata: Dict | None = None) -> Dict:
    extracted = metadata or _extract_report_metadata(note)
    filename_match = REPORT_FILENAME_RE.match(note.name)
    filename_id = filename_match.group(1) if filename_match else ""
    versioned = str(extracted.get("arxiv_id") or "")
    stat = note.stat()
    return {
        "dir_name": note.stem,
        "arxiv_id": base_arxiv_id(versioned) or filename_id,
        "version": ARXIV_ID_RE.search(versioned).group(2) if ARXIV_ID_RE.search(versioned) and ARXIV_ID_RE.search(versioned).group(2) else "",
        "title": str(extracted.get("title") or "").strip(),
        "title_key": normalize_title(str(extracted.get("title") or "")),
        "file_name": note.name,
        "relative_path": note.relative_to(notes_root).as_posix(),
        "wikilink_target": note.stem,
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
        "metadata_source": extracted.get("_index_source", "frontmatter"),
    }


def scan_flat_notes(notes_root: Path) -> List[Dict]:
    if not notes_root.is_dir():
        return []
    entries = []
    for path in sorted(notes_root.rglob("*_阅读报告.md")):
        if not path.is_file():
            continue
        filename_match = REPORT_FILENAME_RE.match(path.name)
        if filename_match:
            # Canonical names make the common lookup path metadata-free: no report read is needed.
            metadata = {
                "title": "",
                "arxiv_id": filename_match.group(1),
                "_index_source": "canonical_filename",
            }
        else:
            metadata = _extract_report_metadata(path)
            metadata["_index_source"] = "frontmatter_fallback"
        entries.append(_build_flat_entry(path, notes_root, metadata))
    return entries


def scan_all_workspaces(output_root: Path) -> List[Dict]:
    entries = []
    if not output_root.is_dir():
        return entries
    for candidate in sorted(output_root.iterdir()):
        if not candidate.is_dir():
            continue
        metadata_path = candidate / "metadata.json"
        if not metadata_path.exists():
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        entries.append(_build_entry_from_metadata(candidate.name, metadata))
    return entries


def rebuild_lookup_maps(index_data: Dict) -> None:
    by_arxiv_id: dict[str, list[str]] = {}
    by_title: dict[str, list[str]] = {}
    for entry in index_data.get("papers", []):
        relative_path = entry.get("relative_path") or entry.get("dir_name") or ""
        if entry.get("arxiv_id"):
            by_arxiv_id.setdefault(base_arxiv_id(entry["arxiv_id"]), []).append(relative_path)
        title_key = entry.get("title_key") or normalize_title(entry.get("title", ""))
        if title_key:
            by_title.setdefault(title_key, []).append(relative_path)
    index_data["by_arxiv_id"] = by_arxiv_id
    index_data["by_title"] = by_title


def _index_path(root: Path, flat: bool, explicit: Path | None = None) -> Path:
    return explicit or root / (FLAT_INDEX_FILENAME if flat else INDEX_FILENAME)


def load_index(root: Path, *, flat: bool = False, index_path: Path | None = None) -> Dict:
    path = _index_path(root, flat, index_path)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("schema_version") == INDEX_SCHEMA_VERSION:
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "schema_version": INDEX_SCHEMA_VERSION,
        "layout": "flat" if flat else "workspace",
        "root": str(root),
        "updated_at": "",
        "papers": [],
        "by_arxiv_id": {},
        "by_title": {},
    }


def save_index(root: Path, index_data: Dict, *, flat: bool = False, index_path: Path | None = None) -> Path:
    path = _index_path(root, flat, index_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    index_data["schema_version"] = INDEX_SCHEMA_VERSION
    index_data["layout"] = "flat" if flat else "workspace"
    index_data["root"] = str(root)
    index_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    rebuild_lookup_maps(index_data)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(index_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def rebuild_index(root: Path, flat: bool = False, index_path: Path | None = None) -> Dict:
    papers = scan_flat_notes(root) if flat else scan_all_workspaces(root)
    data = load_index(root, flat=flat, index_path=index_path)
    data["papers"] = papers
    if flat:
        data["scan_stats"] = {
            "paper_count": len(papers),
            "filename_only": sum(entry.get("metadata_source") == "canonical_filename" for entry in papers),
            "frontmatter_fallback": sum(entry.get("metadata_source") == "frontmatter_fallback" for entry in papers),
        }
    save_index(root, data, flat=flat, index_path=index_path)
    return data


def ensure_index(output_root: Path) -> Dict:
    """Workspace index freshness is checked because duplicate detection must see external changes."""
    path = _index_path(output_root, False)
    data = load_index(output_root)
    if data["papers"] and path.exists():
        mtime = path.stat().st_mtime_ns
        metadata_files = list(output_root.rglob("metadata.json"))
        if all(candidate.stat().st_mtime_ns <= mtime for candidate in metadata_files if candidate.is_file()):
            return data
    return rebuild_index(output_root)


def load_or_rebuild_flat_index(notes_root: Path, *, rebuild: bool = False, index_path: Path | None = None) -> Dict:
    """Load the cached vault index without scanning; rebuild only once or when explicitly requested."""
    path = _index_path(notes_root, True, index_path)
    if rebuild or not path.exists():
        return rebuild_index(notes_root, flat=True, index_path=path)
    data = load_index(notes_root, flat=True, index_path=path)
    if not data.get("updated_at"):
        return rebuild_index(notes_root, flat=True, index_path=path)
    return data


def upsert_flat_note(
    notes_root: Path,
    note: Path,
    *,
    metadata: Dict | None = None,
    index_data: Dict | None = None,
    index_path: Path | None = None,
) -> Dict:
    data = index_data or load_or_rebuild_flat_index(notes_root, index_path=index_path)
    entry_metadata = dict(metadata or _extract_report_metadata(note))
    entry_metadata["_index_source"] = "sync_upsert"
    entry = _build_flat_entry(note, notes_root, entry_metadata)
    data["papers"] = [paper for paper in data.get("papers", []) if paper.get("relative_path") != entry["relative_path"]]
    data["papers"].append(entry)
    save_index(notes_root, data, flat=True, index_path=index_path)
    return data


def hydrate_flat_titles(index_data: Dict, notes_root: Path) -> int:
    """Read frontmatter only for filename-only entries, once, on a rare title-only lookup."""
    hydrated = 0
    for entry in index_data.get("papers", []):
        if entry.get("title") or entry.get("metadata_source") != "canonical_filename":
            continue
        path = notes_root / str(entry.get("relative_path") or "")
        if not path.is_file():
            continue
        metadata = _extract_report_metadata(path)
        if metadata.get("title"):
            entry["title"] = metadata["title"]
            entry["title_key"] = normalize_title(metadata["title"])
            entry["metadata_source"] = "frontmatter_lazy"
            hydrated += 1
    if hydrated:
        rebuild_lookup_maps(index_data)
        stats = index_data.setdefault("scan_stats", {})
        stats["lazy_title_reads"] = int(stats.get("lazy_title_reads") or 0) + hydrated
    return hydrated


def lookup_flat_note(
    index_data: Dict,
    notes_root: Path,
    *,
    arxiv_id: str = "",
    title: str = "",
    hydrate_titles_on_miss: bool = False,
) -> tuple[Dict | None, str]:
    paths = []
    base_id = base_arxiv_id(arxiv_id)
    if base_id:
        paths = list(index_data.get("by_arxiv_id", {}).get(base_id, []))
    if not paths and title:
        paths = list(index_data.get("by_title", {}).get(normalize_title(title), []))
        if not paths and hydrate_titles_on_miss:
            hydrate_flat_titles(index_data, notes_root)
            paths = list(index_data.get("by_title", {}).get(normalize_title(title), []))
    entries = {entry.get("relative_path"): entry for entry in index_data.get("papers", [])}
    valid = [entries[path] for path in paths if path in entries and (notes_root / path).is_file()]
    if len(valid) == 1:
        return valid[0], "matched"
    if len(valid) > 1:
        return None, "ambiguous"
    return None, "missing"


def add_entry(output_root: Path, dir_name: str) -> Dict:
    data = ensure_index(output_root)
    metadata_path = output_root / dir_name / "metadata.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        metadata = {}
    entry = _build_entry_from_metadata(dir_name, metadata)
    data["papers"] = [paper for paper in data["papers"] if paper.get("dir_name") != dir_name]
    data["papers"].append(entry)
    save_index(output_root, data)
    return data


def query_by_arxiv_id(index_data: Dict, arxiv_id: str) -> List[Dict]:
    base_id = base_arxiv_id(arxiv_id)
    return [paper for paper in index_data.get("papers", []) if base_arxiv_id(paper.get("arxiv_id", "")) == base_id] if base_id else []


def query_by_title(index_data: Dict, title: str) -> List[Dict]:
    key = normalize_title(title)
    return [paper for paper in index_data.get("papers", []) if normalize_title(paper.get("title", "")) == key] if key else []


def query_duplicates(index_data: Dict, arxiv_id: str, title: str) -> List[Dict]:
    results = []
    seen = set()
    for match_by, matches in (("arxiv_id", query_by_arxiv_id(index_data, arxiv_id)), ("title", query_by_title(index_data, title))):
        for match in matches:
            if match.get("dir_name") in seen:
                continue
            result = dict(match)
            result["match_by"] = match_by
            results.append(result)
            seen.add(match.get("dir_name"))
    return results


def rebuild_all_indexes(project_root: Optional[Path] = None) -> None:
    project_root = project_root or _find_project_root()
    output_dir = Path.cwd() / "output"
    if not output_dir.is_dir():
        output_dir = project_root / "output"
    if output_dir.is_dir():
        data = rebuild_index(output_dir)
        print(f"output index rebuilt: {len(data['papers'])} papers")
    obsidian_dir = _resolve_obsidian_notes_dir(project_root)
    if obsidian_dir:
        data = rebuild_index(obsidian_dir, flat=True)
        print(f"Obsidian index rebuilt: {len(data['papers'])} papers")


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper index manager.")
    parser.add_argument("--root", default=None)
    parser.add_argument("--index-path")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--flat", action="store_true")
    parser.add_argument("--add", metavar="DIR_NAME")
    parser.add_argument("--query-id", metavar="ARXIV_ID")
    parser.add_argument("--query-title", metavar="TITLE")
    args = parser.parse_args()

    if args.rebuild and args.root is None:
        rebuild_all_indexes()
        return
    root = Path(args.root or "output").resolve()
    index_path = Path(args.index_path).expanduser().resolve() if args.index_path else None
    if args.rebuild:
        data = rebuild_index(root, flat=args.flat, index_path=index_path)
        print(f"Index rebuilt: {len(data['papers'])} papers")
        return
    if args.add:
        data = add_entry(root, args.add)
        print(f"Index updated: {len(data['papers'])} papers")
        return
    data = load_or_rebuild_flat_index(root, index_path=index_path) if args.flat else ensure_index(root)
    matches = query_by_arxiv_id(data, args.query_id) if args.query_id else query_by_title(data, args.query_title or "")
    if args.query_id or args.query_title:
        print(json.dumps(matches, ensure_ascii=False, indent=2) if matches else "No matching paper")
        return
    parser.print_help()


if __name__ == "__main__":
    main()
