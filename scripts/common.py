#!/usr/bin/env python3
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Dict, Optional, Tuple
from html import unescape
from urllib.parse import urlparse

import requests

ARXIV_ID_RE = re.compile(r'(?P<base>\d{4}\.\d{4,5})(?P<version>v\d+)?', re.I)
TITLE_RE = re.compile(r'<h1[^>]*class=["\']title\s+mathjax["\'][^>]*>(.*?)</h1>', re.I | re.S)
META_TITLE_RE = re.compile(r'<meta[^>]+name=["\']citation_title["\'][^>]+content=["\'](.*?)["\']', re.I | re.S)
INVALID_PATH_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
WHITESPACE_RE = re.compile(r'\s+')
MAX_TITLE_SLUG_CHARS = 140
LEGACY_ARTIFACT_PATHS = {
    "raw_abs_html": "raw/abs.html",
    "raw_pdf": "raw/paper.pdf",
    "raw_ar5iv_html": "raw/ar5iv.html",
    "raw_src_tar": "raw/source.tar",
    "raw_hjfy_html": "raw/hjfy.html",
    "raw_papers_cool_html": "raw/papers_cool.html",
    "cache_references_json": "cache/references.json",
    "cache_images_manifest": "cache/images_manifest.json",
}
SOURCE_URL_TEMPLATES = {
    "arxiv_abs_url": "https://arxiv.org/abs/{}",
    "arxiv_pdf_url": "https://arxiv.org/pdf/{}.pdf",
    "hjfy_url": "https://hjfy.top/arxiv/{}",
    "papers_cool_url": "https://papers.cool/arxiv/{}",
    "ar5iv_url": "https://ar5iv.org/html/{}",
    "arxiv_src_url": "https://arxiv.org/src/{}",
}
FETCH_STATUS_LABELS = {
    "hjfy_visit_status": ("hjfy", "已访问", "访问失败"),
    "papers_cool_rel_status": ("papers_cool_related", "已取得相关检索页面", "未取得可验证的相关检索页面"),
}


def extract_arxiv_id(text: str) -> Optional[Tuple[str, Optional[str]]]:
    match = ARXIV_ID_RE.search(text)
    if match:
        return match.group("base"), match.group("version")
    try:
        path = urlparse(text).path
        match = ARXIV_ID_RE.search(path)
        if match:
            return match.group("base"), match.group("version")
    except Exception:
        pass
    return None


def fetch_arxiv_abs_html(paper_id: str, timeout: int = 20) -> str:
    url = f"https://arxiv.org/abs/{paper_id}"
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "paper-reading-skill"})
    r.raise_for_status()
    return r.text


def parse_latest_version(base_id: str, html: str) -> Optional[str]:
    candidates = re.findall(rf'{re.escape(base_id)}v(\d+)', html)
    if candidates:
        return f"v{max(int(x) for x in candidates)}"
    m = re.search(r'this version,\s*v(\d+)', html, re.I)
    if m:
        return f"v{m.group(1)}"
    return None


def parse_arxiv_title(html: str) -> Optional[str]:
    match = TITLE_RE.search(html) or META_TITLE_RE.search(html)
    if not match:
        return None
    title = re.sub(r"<[^>]+>", " ", match.group(1))
    title = unescape(title)
    title = re.sub(r"^\s*Title:\s*", "", title, flags=re.I)
    title = WHITESPACE_RE.sub(" ", title).strip()
    return title or None


def fetch_arxiv_metadata(base_id: str, version: Optional[str] = None, timeout: int = 20) -> Dict[str, Optional[str]]:
    paper_id = f"{base_id}{version or ''}"
    html = fetch_arxiv_abs_html(paper_id, timeout=timeout)
    return {
        "version": version or parse_latest_version(base_id, html),
        "title": parse_arxiv_title(html),
    }


def fetch_latest_version(base_id: str, timeout: int = 20) -> Optional[str]:
    return fetch_arxiv_metadata(base_id, timeout=timeout)["version"]


def sanitize_title_for_path(title: Optional[str]) -> str:
    if not title:
        return ""
    normalized = unicodedata.normalize("NFKC", title)
    normalized = INVALID_PATH_CHARS_RE.sub(" ", normalized)
    normalized = normalized.replace("'", "").replace("`", "")
    slug = WHITESPACE_RE.sub("_", normalized).strip(" ._-")
    if len(slug) > MAX_TITLE_SLUG_CHARS:
        slug = slug[:MAX_TITLE_SLUG_CHARS].rstrip(" ._-")
    return slug


def build_workspace_name(arxiv_id: str, title: Optional[str]) -> str:
    title_slug = sanitize_title_for_path(title)
    return f"{arxiv_id}_{title_slug}" if title_slug else arxiv_id


def arxiv_id_with_version(metadata: Dict) -> str:
    base_id = str(metadata.get("arxiv_id") or "")
    candidate = f"{base_id}{metadata.get('version') or ''}"
    match = ARXIV_ID_RE.fullmatch(candidate)
    # Manually prepared workspaces can use non-arXiv IDs and descriptive versions.
    return candidate if match and match.group("base") == base_id else base_id


def default_source_urls(metadata: Dict) -> Dict[str, str]:
    base_id = str(metadata.get("arxiv_id") or "")
    match = ARXIV_ID_RE.fullmatch(base_id)
    if metadata.get("is_arxiv") is False or not match or match.group("version"):
        return {}
    versioned_id = arxiv_id_with_version(metadata)
    return {field: template.format(versioned_id) for field, template in SOURCE_URL_TEMPLATES.items()}


def workspace_source_urls(metadata: Dict) -> Dict:
    defaults = default_source_urls(metadata)
    return {field: metadata.get(field, defaults.get(field, "")) for field in SOURCE_URL_TEMPLATES}


def resolve_ids(input_text: str) -> Dict[str, str]:
    parsed = extract_arxiv_id(input_text)
    if not parsed:
        raise ValueError(f"Could not parse arXiv id from input: {input_text}")
    base_id, version = parsed
    metadata = fetch_arxiv_metadata(base_id, version)
    return {
        "input": input_text,
        "arxiv_id": base_id,
        "title": metadata["title"] or "",
        "version": metadata["version"] or "",
    }


def ensure_workspace(root: Path, arxiv_id: str, title: Optional[str] = None, workspace_name: Optional[str] = None) -> Path:
    desired_name = workspace_name or build_workspace_name(arxiv_id, title)
    base = root / desired_name
    if not base.exists():
        matches = sorted(path for path in root.glob(f"{arxiv_id}_*") if path.is_dir())
        if len(matches) == 1:
            base = matches[0]
    for sub in ["raw", "images", "cache", "logs"]:
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def write_json(path: Path, payload: Dict) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_workspace_metadata(path: Path) -> Dict:
    metadata = read_json(path)
    legacy_id = metadata.pop("paper_id_with_version", "")
    if legacy_id and not metadata.get("version"):
        match = ARXIV_ID_RE.fullmatch(str(legacy_id))
        if match and match.group("base") == metadata.get("arxiv_id"):
            metadata["version"] = match.group("version") or ""
    return metadata


def default_report_filename(arxiv_id: str) -> str:
    return f"{arxiv_id}_阅读报告.md"


def recorded_default_workspace(workspace: Path, metadata: Dict) -> Optional[Path]:
    if not metadata.get("workspace"):
        return None
    recorded = Path(metadata["workspace"]).expanduser()
    if workspace / recorded == workspace:
        return workspace
    # Older writers stored a matching directory name and absolute report path.
    report = default_report_filename(metadata.get("arxiv_id", ""))
    if (
        recorded.is_absolute()
        and metadata.get("workspace_name") == recorded.name
        and metadata.get("report_path") == str(recorded / report)
        and (recorded.name == workspace.name or not recorded.is_dir())
    ):
        return recorded
    return None


def workspace_report_path(workspace: Path, metadata: Dict) -> Path:
    filename = default_report_filename(metadata.get("arxiv_id", ""))
    recorded = recorded_default_workspace(workspace, metadata) or workspace
    if metadata.get("report_path"):
        path = workspace / Path(metadata["report_path"]).expanduser()
        if path not in (workspace / filename, recorded / filename):
            return path
    return workspace / Path(metadata.get("report_filename") or filename).expanduser()


def compact_workspace_metadata(workspace: Path, metadata: Dict) -> Dict:
    """Omit generated defaults when preparing a metadata write."""
    compact = dict(metadata)
    recorded = recorded_default_workspace(workspace, metadata)
    if recorded is not None:
        compact.pop("workspace", None)
    recorded = recorded or workspace
    if compact.get("workspace_name") in (workspace.name, recorded.name):
        compact.pop("workspace_name")

    filename = default_report_filename(metadata.get("arxiv_id", ""))
    for field in ("report_path", "report_filename"):
        if compact.get(field) and workspace / Path(compact[field]).expanduser() in (
            workspace / filename, recorded / filename
        ):
            compact.pop(field)

    paths = compact.get("paths")
    if isinstance(paths, dict):
        paths = dict(paths)
        for field, relative in LEGACY_ARTIFACT_PATHS.items():
            if paths.get(field) and workspace / Path(paths[field]).expanduser() in (
                workspace / relative, recorded / relative
            ):
                paths.pop(field)
        if paths:
            compact["paths"] = paths
        else:
            compact.pop("paths")

    if compact.get("resolved_at") and compact.get("updated_at") == compact["resolved_at"]:
        compact.pop("updated_at")

    for field, url in default_source_urls(metadata).items():
        if compact.get(field) == url:
            compact.pop(field)

    statuses = compact.get("internal_status")
    results = compact.get("fetch_results") or {}
    if isinstance(statuses, dict) and isinstance(results, dict):
        statuses = dict(statuses)
        for field, (source, success, failure) in FETCH_STATUS_LABELS.items():
            result = results.get(source)
            expected = "未尝试" if source not in results else None
            if isinstance(result, dict) and isinstance(result.get("ok"), bool):
                expected = success if result["ok"] else failure
            if expected is not None and statuses.get(field) == expected:
                statuses.pop(field)
        if statuses:
            compact["internal_status"] = statuses
        else:
            compact.pop("internal_status")
    return compact


def reject_ambiguous_reports(root: Path, paper_input: str) -> None:
    direct = Path(paper_input)
    if direct.is_dir() or (root / paper_input).is_dir():
        return
    parsed = extract_arxiv_id(paper_input)
    if not parsed:
        return
    arxiv_id = parsed[0]
    reports = []
    for workspace in sorted(root.glob(f"{arxiv_id}_*")):
        if not workspace.is_dir():
            continue
        path = workspace / "metadata.json"
        try:
            metadata = read_workspace_metadata(path)
        except (json.JSONDecodeError, OSError):
            metadata = {}
        metadata.setdefault("arxiv_id", arxiv_id)
        report = workspace_report_path(workspace, metadata)
        if report.is_file():
            reports.append(report)
    if len(reports) > 1:
        raise ValueError(
            f"Multiple reports for {arxiv_id}; pass a workspace directory or --report-path: "
            + ", ".join(str(path.parent.name) for path in reports)
        )


def _find_cached_workspace(root: Path, arxiv_id: str) -> Optional[Tuple[Path, Dict]]:
    candidates = sorted(
        path for path in root.glob(f"{arxiv_id}_*") if path.is_dir()
    )
    for candidate in candidates:
        meta_path = candidate / "metadata.json"
        if meta_path.exists():
            try:
                return candidate, read_workspace_metadata(meta_path)
            except (json.JSONDecodeError, OSError):
                continue
    return None


def _search_metadata_by_input(root: Path, input_text: str) -> Optional[Tuple[Path, Dict]]:
    """Search all metadata.json files for one whose input field matches input_text.

    Also checks ``original_url`` to support non-arXiv papers whose metadata
    was created manually (e.g. OpenAI CDN PDFs).
    """
    for meta_path in sorted(root.rglob("metadata.json")):
        try:
            meta = read_workspace_metadata(meta_path)
            matchable_fields = (
                meta.get("input"),
                meta.get("openreview_forum_url"),
                meta.get("openreview_pdf_url"),
                meta.get("original_url"),
            )
            if input_text in matchable_fields:
                return meta_path.parent, meta
        except (json.JSONDecodeError, OSError):
            continue
    return None


def get_workspace(root: Path, input_text: str):
    # ---- Direct directory path: skip all ID resolution ----
    direct = Path(input_text)
    if not direct.is_absolute():
        direct = root / input_text
    if direct.is_dir():
        meta_path = direct / "metadata.json"
        if meta_path.exists():
            cached = read_workspace_metadata(meta_path)
            ids = _build_ids_from_metadata(cached, input_text)
            for sub in ["raw", "images", "cache", "logs"]:
                (direct / sub).mkdir(parents=True, exist_ok=True)
            return direct, ids

    # Try local cache first to avoid unnecessary network requests
    parsed = extract_arxiv_id(input_text)
    if parsed:
        base_id, requested_version = parsed
        found = _find_cached_workspace(root, base_id)
        candidate, cached = found if found else (root, {})
        cached_version = str(cached.get("version") or "")
        version_matches = not requested_version or requested_version == cached_version
        if cached and cached.get("arxiv_id") == base_id and version_matches:
            ids = _build_ids_from_metadata(cached, input_text)
            name = cached.get("workspace_name")
            recorded = recorded_default_workspace(candidate, cached)
            if name and (recorded is None or name != recorded.name) and (root / name).is_dir():
                candidate = root / name
            workspace = ensure_workspace(candidate.parent, base_id, workspace_name=candidate.name)
            return workspace, ids

    # Fallback: search metadata.json files by input URL (e.g., OpenReview links, non-arXiv PDFs)
    if not parsed:
        found = _search_metadata_by_input(root, input_text)
        if found:
            candidate, cached = found
            ids = _build_ids_from_metadata(cached, input_text)
            override = cached.get("workspace")
            if override and recorded_default_workspace(candidate, cached) is None:
                alternate = Path(override).expanduser()
                if alternate.is_dir():
                    return alternate, ids
            return candidate, ids

    # Fall back to network fetch when no local cache exists
    ids = resolve_ids(input_text)
    workspace = ensure_workspace(root, ids["arxiv_id"], ids.get("title"))
    return workspace, _build_ids_from_metadata(ids, input_text)


def _build_ids_from_metadata(cached: Dict, input_text: str) -> Dict:
    return {
        "input": input_text,
        "arxiv_id": "",
        "title": "",
        "version": "",
        **cached,
        **workspace_source_urls(cached),
    }


def http_get(url: str, timeout: int = 30):
    return requests.get(url, timeout=timeout, headers={"User-Agent": "paper-reading-skill"})


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Write a file atomically so interrupted stages never leave valid-looking partial output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(text, encoding=encoding)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


ALLOWED_MARKDOWN_CONTROL_CHARS = {"\n", "\r", "\t"}


def find_disallowed_control_chars(text: str) -> list[tuple[int, int]]:
    return [
        (index, ord(char))
        for index, char in enumerate(text)
        if ord(char) < 32 and char not in ALLOWED_MARKDOWN_CONTROL_CHARS
    ]


def assert_markdown_text_is_safe(text: str, source: str = "markdown") -> None:
    control_chars = find_disallowed_control_chars(text)
    if not control_chars:
        return

    preview = ", ".join(
        f"offset={offset}:0x{code_point:02x}"
        for offset, code_point in control_chars[:10]
    )
    raise ValueError(
        f"Refusing to write {source}: disallowed control characters detected. "
        "This often happens when LaTeX is embedded in a normal Python string "
        "instead of a raw string. "
        f"Examples: {preview}"
    )


def write_markdown_report(path: Path, text: str) -> None:
    assert_markdown_text_is_safe(text, str(path))
    atomic_write_text(path, text)
