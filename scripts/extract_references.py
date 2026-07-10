#!/usr/bin/env python3
"""Extract structured references from source bibliography, ar5iv, or TeX fallbacks."""

from __future__ import annotations

import argparse
import io
import re
import tarfile
from html import unescape
from pathlib import Path

from bs4 import BeautifulSoup

from common import get_workspace, write_json


def clean_latex(value: str) -> str:
    value = value.replace("\n", " ")
    value = re.sub(r"\\(?:textit|emph|textbf|url|href)\s*\{([^{}]*)\}", r"\1", value)
    value = re.sub(r"\\[A-Za-z@]+\*?(?:\[[^]]*\])?", " ", value)
    value = value.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", unescape(value)).strip(" ,.;")


def split_top_level(value: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    quoted = False
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"' and depth == 0:
            quoted = not quoted
        elif not quoted:
            if char == "{":
                depth += 1
            elif char == "}" and depth:
                depth -= 1
            elif char == "," and depth == 0:
                parts.append(value[start:index].strip())
                start = index + 1
    parts.append(value[start:].strip())
    return [part for part in parts if part]


def parse_bibtex(text: str, source_name: str) -> list[dict]:
    entries: list[dict] = []
    cursor = 0
    while True:
        match = re.search(r"@(\w+)\s*([({])", text[cursor:], flags=re.I)
        if not match:
            break
        entry_type = match.group(1).lower()
        open_char = match.group(2)
        close_char = "}" if open_char == "{" else ")"
        start = cursor + match.end()
        depth = 1
        quoted = False
        escaped = False
        end = None
        for index in range(start, len(text)):
            char = text[index]
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                quoted = not quoted
            if quoted:
                continue
            if char == open_char:
                depth += 1
            elif char == close_char:
                depth -= 1
                if depth == 0:
                    end = index
                    break
        if end is None:
            break
        body = text[start:end]
        cursor = end + 1
        fields = split_top_level(body)
        if not fields:
            continue
        citation_key = fields[0]
        parsed_fields: dict[str, str] = {}
        for field in fields[1:]:
            if "=" not in field:
                continue
            key, raw = field.split("=", 1)
            raw = raw.strip()
            if len(raw) >= 2 and ((raw[0] == "{" and raw[-1] == "}") or (raw[0] == raw[-1] == '"')):
                raw = raw[1:-1]
            parsed_fields[key.strip().lower()] = clean_latex(raw)
        title = parsed_fields.get("title", "")
        if entry_type in {"string", "preamble", "comment"} or not title:
            continue
        entries.append(
            {
                "citation_key": citation_key.strip(),
                "entry_type": entry_type,
                "title": title,
                "authors": parsed_fields.get("author", ""),
                "year": parsed_fields.get("year", ""),
                "venue": parsed_fields.get("booktitle") or parsed_fields.get("journal", ""),
                "doi": parsed_fields.get("doi", ""),
                "arxiv_id": parsed_fields.get("eprint", ""),
                "url": parsed_fields.get("url", ""),
                "source": source_name,
            }
        )
    return entries


def parse_bbl_or_tex(text: str, source_name: str) -> list[dict]:
    matches = list(re.finditer(r"\\bibitem(?:\[[^]]*\])?\{([^}]+)\}", text))
    entries = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        raw = clean_latex(text[match.end():end])
        if len(raw) < 20:
            continue
        year_match = re.search(r"\b(19|20)\d{2}\b", raw)
        entries.append(
            {
                "citation_key": match.group(1),
                "entry_type": "bibitem",
                "title": "",
                "authors": "",
                "year": year_match.group(0) if year_match else "",
                "venue": "",
                "doi": "",
                "arxiv_id": "",
                "url": "",
                "raw_text": raw,
                "source": source_name,
            }
        )
    return entries


def source_bibliographies(source_tar: Path) -> tuple[list[dict], list[str]]:
    entries: list[dict] = []
    errors: list[str] = []
    if not source_tar.exists():
        return entries, errors
    try:
        with tarfile.open(source_tar, "r:*") as archive:
            members = [
                member for member in archive.getmembers()
                if member.isfile() and Path(member.name).suffix.lower() in {".bib", ".bbl", ".tex"}
                and member.size <= 10 * 1024 * 1024
            ]
            members.sort(key=lambda member: (Path(member.name).suffix.lower() != ".bib", member.name))
            for member in members:
                handle = archive.extractfile(member)
                if handle is None:
                    continue
                text = io.TextIOWrapper(handle, encoding="utf-8", errors="ignore").read()
                if member.name.lower().endswith(".bib"):
                    entries.extend(parse_bibtex(text, f"arxiv_src:{member.name}"))
                elif "\\bibitem" in text:
                    entries.extend(parse_bbl_or_tex(text, f"arxiv_src:{member.name}"))
    except (tarfile.TarError, OSError) as exc:
        errors.append(f"source archive bibliography extraction failed: {exc}")
    return entries, errors


def parse_references_from_ar5iv(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    nodes = soup.select(".ltx_bibitem, li[id*='bib'], .ltx_bibliography li")
    entries = []
    for node in nodes:
        text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
        if len(text) < 20:
            continue
        year_match = re.search(r"\b(19|20)\d{2}\b", text)
        link = node.find("a", href=True)
        entries.append(
            {
                "citation_key": node.get("id", ""),
                "entry_type": "html_reference",
                "title": "",
                "authors": "",
                "year": year_match.group(0) if year_match else "",
                "venue": "",
                "doi": "",
                "arxiv_id": "",
                "url": link["href"] if link else "",
                "raw_text": text,
                "source": "ar5iv_html",
            }
        )
    return entries


def dedupe(entries: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for entry in entries:
        identity = entry.get("doi") or entry.get("arxiv_id") or entry.get("title") or entry.get("raw_text") or entry.get("citation_key")
        key = re.sub(r"\W+", "", str(identity).lower())
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(entry)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--root", default="output")
    args = parser.parse_args()

    workspace, _ = get_workspace(Path(args.root).resolve(), args.input)
    entries, errors = source_bibliographies(workspace / "raw" / "source.tar")
    sources = ["arxiv_source_bibliography"] if entries else []
    ar5iv_path = workspace / "raw" / "ar5iv.html"
    if ar5iv_path.exists():
        html_entries = parse_references_from_ar5iv(ar5iv_path.read_text(encoding="utf-8", errors="ignore"))
        if html_entries:
            sources.append("ar5iv_html")
            entries.extend(html_entries)
    entries = dedupe(entries)
    write_json(
        workspace / "cache" / "references.json",
        {
            "schema_version": "2.0",
            "sources": sources,
            "count": len(entries),
            "items": entries,
            "extraction_errors": errors,
            "note": "中间证据索引；写入报告的外部文献仍须逐条核查一手来源。",
        },
    )
    print("Extracted structured references:", len(entries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
