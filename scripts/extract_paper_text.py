#!/usr/bin/env python3
"""Extract page-addressable text from the validated canonical PDF."""

from __future__ import annotations

import argparse
from pathlib import Path

import fitz

from common import atomic_write_text, get_workspace, write_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--root", default="output")
    args = parser.parse_args()

    workspace, _ = get_workspace(Path(args.root).resolve(), args.input)
    pdf_path = workspace / "raw" / "paper.pdf"
    if not pdf_path.exists():
        raise FileNotFoundError(f"Validated PDF not found: {pdf_path}")

    page_records = []
    chunks = []
    offset = 0
    with fitz.open(pdf_path) as document:
        for page_number, page in enumerate(document, start=1):
            text = page.get_text("text").replace("\x00", "").strip()
            block = f"\n\n===== PDF PAGE {page_number} =====\n\n{text}\n"
            chunks.append(block)
            page_records.append(
                {
                    "page": page_number,
                    "start_offset": offset,
                    "end_offset": offset + len(block),
                    "characters": len(text),
                }
            )
            offset += len(block)
    combined = "".join(chunks).lstrip()
    atomic_write_text(workspace / "cache" / "paper_text.txt", combined)
    write_json(
        workspace / "cache" / "paper_text.json",
        {
            "schema_version": "1.0",
            "method": "pymupdf_page_text",
            "source": "raw/paper.pdf",
            "page_count": len(page_records),
            "pages": page_records,
        },
    )
    print("Extracted PDF text pages:", len(page_records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
