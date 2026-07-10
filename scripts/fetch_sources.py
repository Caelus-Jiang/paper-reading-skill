#!/usr/bin/env python3
"""Fetch paper sources atomically and reject valid-looking error payloads."""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from common import atomic_write_bytes, get_workspace, read_json, write_json


def build_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    session = requests.Session()
    session.headers.update({"User-Agent": "paper-reading-skill/2.0"})
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


def validate_payload(kind: str, content: bytes, content_type: str = "") -> None:
    if not content:
        raise ValueError("empty response")
    if kind == "pdf":
        if len(content) < 1024 or not content.lstrip().startswith(b"%PDF"):
            raise ValueError("response is not a valid PDF payload")
        return
    if kind == "tar":
        if len(content) < 32:
            raise ValueError("source archive is too small")
        try:
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:*") as archive:
                if not archive.getmembers():
                    raise ValueError("source archive contains no members")
        except (tarfile.TarError, EOFError) as exc:
            raise ValueError(f"response is not a readable tar archive: {exc}") from exc
        return

    text = content.decode("utf-8", errors="ignore")
    lowered = text.lower()
    if len(text.strip()) < 200:
        raise ValueError("HTML response is too small")
    if any(marker in lowered for marker in ("fetch failed:", "cf-chl-", "captcha", "access denied")):
        raise ValueError("HTML response looks like an error or challenge page")
    if "html" not in content_type.lower() and "<html" not in lowered and "<!doctype" not in lowered:
        raise ValueError(f"response does not look like HTML (content-type={content_type!r})")
    if kind == "arxiv_abs" and "arxiv" not in lowered:
        raise ValueError("arXiv abs marker was not found")
    if kind == "ar5iv" and not any(marker in lowered for marker in ("ltx_document", "ltx_page_main", "latexml")):
        raise ValueError("ar5iv/LaTeXML document marker was not found")


def error_path(workspace: Path, name: str) -> Path:
    return workspace / "logs" / "fetch" / f"{name}.error.json"


def save_response(
    session: requests.Session,
    name: str,
    url: str,
    path: Path,
    kind: str,
    workspace: Path,
) -> dict:
    try:
        response = session.get(url, timeout=(15, 60))
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        validate_payload(kind, response.content, content_type)
        atomic_write_bytes(path, response.content)
        error_path(workspace, name).unlink(missing_ok=True)
        return {
            "ok": True,
            "status_code": response.status_code,
            "url": response.url,
            "content_type": content_type,
            "bytes": len(response.content),
            "sha256": hashlib.sha256(response.content).hexdigest(),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:  # noqa: BLE001 - fetch errors are recorded structurally
        kept_previous = False
        if path.exists():
            try:
                validate_payload(kind, path.read_bytes(), "")
                kept_previous = True
            except Exception:  # noqa: BLE001
                path.unlink(missing_ok=True)
        payload = {
            "ok": False,
            "url": url,
            "kind": kind,
            "error": str(exc),
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "kept_previous_valid_output": kept_previous,
        }
        write_json(error_path(workspace, name), payload)
        return payload


def fetch_papers_cool_related(
    session: requests.Session,
    workspace: Path,
    base_id: str,
    paper_result: dict,
) -> dict:
    paper_path = workspace / "raw" / "papers_cool.html"
    if not paper_result.get("ok") or not paper_path.exists():
        return {"ok": False, "error": "paper page unavailable"}
    html = paper_path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(
        rf'id=["\']{re.escape(base_id)}["\'][^>]*\bkeywords=["\']([^"\']+)',
        html,
        flags=re.I,
    )
    if not match:
        return {"ok": False, "error": "papers.cool keywords unavailable"}
    keywords = [item.strip() for item in match.group(1).split(",") if item.strip()]
    if not keywords:
        return {"ok": False, "error": "papers.cool keywords were empty"}
    url = f"https://papers.cool/arxiv/search?query={quote(','.join(keywords))}"
    result = save_response(
        session,
        "papers_cool_related",
        url,
        workspace / "raw" / "papers_cool_related.html",
        "html",
        workspace,
    )
    result["keywords"] = keywords
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--root", default="output")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    workspace, ids = get_workspace(root, args.input)
    metadata_path = workspace / "metadata.json"
    metadata = read_json(metadata_path)
    session = build_session()

    specs = [
        ("arxiv_abs", ids["arxiv_abs_url"], workspace / "raw" / "abs.html", "arxiv_abs", True),
        ("arxiv_pdf", ids["arxiv_pdf_url"], workspace / "raw" / "paper.pdf", "pdf", True),
        ("ar5iv", ids["ar5iv_url"], workspace / "raw" / "ar5iv.html", "ar5iv", False),
        ("arxiv_src", ids["arxiv_src_url"], workspace / "raw" / "source.tar", "tar", False),
        ("hjfy", ids["hjfy_url"], workspace / "raw" / "hjfy.html", "html", False),
        ("papers_cool", ids["papers_cool_url"], workspace / "raw" / "papers_cool.html", "html", False),
    ]
    results = {
        name: save_response(session, name, url, path, kind, workspace)
        for name, url, path, kind, _required in specs
    }
    results["papers_cool_related"] = fetch_papers_cool_related(
        session, workspace, ids["arxiv_id"], results["papers_cool"]
    )

    metadata["fetch_results"] = results
    internal = metadata.setdefault("internal_status", {})
    internal["hjfy_visit_status"] = "已访问" if results["hjfy"].get("ok") else "访问失败"
    internal["papers_cool_rel_status"] = (
        "已取得相关检索页面" if results["papers_cool_related"].get("ok") else "未取得可验证的相关检索页面"
    )
    write_json(metadata_path, metadata)

    required_failures = [name for name, _url, _path, _kind, required in specs if required and not results[name].get("ok")]
    if required_failures:
        print("Required source fetch failed:", ", ".join(required_failures))
        return 1
    print("Fetched and validated sources into", workspace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
