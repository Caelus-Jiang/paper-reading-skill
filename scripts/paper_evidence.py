"""Check that report citations resolve to the PDF used for the claim analysis."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import fitz

from common import ARXIV_ID_RE


CLAIMS_SCHEMA_VERSION = "2.0"
CLAIMS_HEADING = "### 1.3 核心观点（Claims）的逐条梳理"
CLAIM_FIELDS = ("claim_id", "claim", "claim_kind", "citations", "evidence", "evidence_strength", "reviewer_conclusion")
CLAIM_ID = re.compile(r"C[1-9][0-9]*")
EVIDENCE_LINE = re.compile(r"^(?:> )?\*\*原文依据（(C[1-9][0-9]*)）\*\* (.+)$", re.M)


def default_paper_source(metadata: dict) -> dict:
    base_id = metadata.get("arxiv_id") or ""
    version = metadata.get("version") or ""
    paper_id = metadata.get("paper_id_with_version") or f"{base_id}{version}"
    is_arxiv = metadata.get("is_arxiv") is not False and ARXIV_ID_RE.fullmatch(paper_id)
    return {
        "version": f"arXiv {paper_id}" if is_arxiv else version or "用户提供的 PDF",
        "pdf_path": "raw/paper.pdf",
        "pdf_url": metadata.get("arxiv_pdf_url", f"https://arxiv.org/pdf/{paper_id}.pdf" if is_arxiv else "") or "",
    }


def claim_table_rows(section: str) -> list[list[str]]:
    return [
        [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        for line in section.splitlines()
        if line.strip().startswith("|")
    ]


def one_line(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip() and len(value.splitlines()) == 1


def citation_label(source: dict, page: int, locator: str) -> str:
    label = f"{source['version']} · PDF 第 {page} 页 · {locator}"
    label = re.sub(r"([\\\[\]|])", r"\\\1", label)
    url = source.get("pdf_url")
    return f"[{label}]({url}#page={page})" if url else label


def normalize_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def quote_in_page(quote: str, page_text: str) -> bool:
    # A hyphen at a PDF line break can be either a word separator or typesetting.
    page_text = re.sub(r"(?<=\w)[-\u2010][ \t]*\n\s*(?=\w)", "\u00ad", page_text.replace("\u00ad", ""))
    quote = normalize_text(quote)
    parts = re.split(r"(?<=\w)([-\u2010]?)(?=\w)", quote)
    pattern = [r"(?<!\w)"] if re.match(r"\w", quote) else []
    for index, part in enumerate(parts):
        if index % 2 == 0:
            pattern.append(re.escape(part))
        elif part:
            pattern.append(f"[{re.escape(part)}\u00ad]")
        else:
            pattern.append("\u00ad?")
    if re.search(r"\w$", quote):
        pattern.append(r"(?!\w)")
    return re.search("".join(pattern), normalize_text(page_text)) is not None


def check_paper_evidence(workspace: Path, ledger: dict, claim_section: str, report_body: str) -> list[str]:
    source = ledger.get("paper_source")
    if not isinstance(source, dict) or not all(one_line(source.get(key)) for key in ("version", "pdf_path")):
        return ["paper_source must specify the version and workspace PDF path"]
    url = source.get("pdf_url", "")
    if not isinstance(url, str) or (url and not re.fullmatch(r"https?://[^\s#()<>|]+", url)):
        return ["paper_source.pdf_url must be a PDF URL without a page fragment, or empty"]
    relative_pdf = Path(source["pdf_path"])
    pdf_path = (workspace / relative_pdf).resolve()
    if relative_pdf.is_absolute() or not pdf_path.is_relative_to((workspace / "raw").resolve()):
        return ["paper_source.pdf_path must point to a file inside the workspace raw directory"]
    try:
        if pdf_path == (workspace / "raw/paper.pdf").resolve():
            metadata = json.loads((workspace / "metadata.json").read_text(encoding="utf-8"))
            expected = default_paper_source(metadata)
            if expected["version"].startswith("arXiv ") and (source["version"], url) != (expected["version"], expected["pdf_url"]):
                return ["paper_source version or URL does not match the workspace arXiv PDF"]
        with fitz.open(pdf_path) as document:
            if not document.is_pdf or document.needs_pass:
                return ["paper_source.pdf_path must be a readable PDF"]
            return check_claim_citations(document, source, ledger["claims"], claim_section, report_body)
    except (OSError, ValueError, RuntimeError) as exc:
        return [f"cannot validate paper evidence from {relative_pdf}: {exc}"]


def check_claim_citations(
    document: fitz.Document, source: dict, claims: list[dict], claim_section: str, report_body: str,
) -> list[str]:
    rows = claim_table_rows(claim_section)
    if not rows or "原文位置" not in rows[0] or "主张内容" not in rows[0]:
        return ["claims table must include 主张内容 and 原文位置 columns"]
    location_column = rows[0].index("原文位置")
    claim_column = rows[0].index("主张内容")
    errors = []
    table = {}
    for row in rows[2:]:
        if len(row) <= max(location_column, claim_column) or not CLAIM_ID.fullmatch(row[0]) or row[0] in table:
            errors.append(f"invalid or duplicate claims table row: {row[0]}")
            continue
        table[row[0]] = (row[claim_column], row[location_column])
    body_citations = {}
    for claim_id, citation in EVIDENCE_LINE.findall(report_body):
        body_citations.setdefault(claim_id, set()).add(citation)
    ledger_ids = set()
    page_texts = {}
    for claim in claims:
        claim_id = claim.get("claim_id")
        if not isinstance(claim_id, str) or not CLAIM_ID.fullmatch(claim_id) or claim_id in ledger_ids:
            errors.append(f"invalid or duplicate claim ID in ledger: {claim_id}")
            continue
        ledger_ids.add(claim_id)
        citations = claim.get("citations")
        if not isinstance(citations, list) or not citations:
            errors.append(f"{claim_id} must have at least one PDF citation")
            continue
        expected_lines = set()
        for index, citation in enumerate(citations, 1):
            if not isinstance(citation, dict):
                errors.append(f"{claim_id} citation {index} must be an object")
                continue
            page, locator, quote = citation.get("page"), citation.get("locator"), citation.get("quote")
            if type(page) is not int or not 1 <= page <= len(document) or not one_line(locator):
                errors.append(f"{claim_id} citation {index} needs a valid PDF page and locator")
                continue
            label = citation_label(source, page, locator)
            if index == 1 and table.get(claim_id) != (claim.get("claim"), label):
                errors.append(f"{claim_id} claim or primary citation differs between the table and ledger")
            if "quote" in citation:
                if not one_line(quote):
                    errors.append(f"{claim_id} citation {index} needs a nonempty single-line quote")
                    continue
                if page not in page_texts:
                    page_texts[page] = document[page - 1].get_text()
                if not quote_in_page(quote, page_texts[page]):
                    errors.append(f"{claim_id} quote was not found on PDF page {page}")
                label += f" · “{quote}”"
            expected_lines.add(label)
        if body_citations.get(claim_id, set()) != expected_lines:
            errors.append(f"{claim_id} original-paper citations in the report body differ from the ledger")
    if table.keys() != ledger_ids:
        errors.append("claims table and ledger must contain the same claim IDs")
    if body_citations.keys() - ledger_ids:
        errors.append("report body cites unknown claim IDs")
    return errors
