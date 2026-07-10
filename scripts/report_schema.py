#!/usr/bin/env python3
"""Shared accessors for the canonical paper-reading report schema."""

from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA_PATH = PROJECT_ROOT / "references" / "report_schema.json"


def load_report_schema(path: Path | None = None) -> dict:
    schema_path = path or DEFAULT_SCHEMA_PATH
    return json.loads(schema_path.read_text(encoding="utf-8"))


def ordered_headings(schema: dict) -> list[str]:
    headings: list[str] = []
    for chapter in schema["chapters"]:
        if chapter.get("heading"):
            headings.append(chapter["heading"])
        headings.extend(chapter.get("subheadings") or [])
    return headings


def required_h2_headings(schema: dict) -> list[str]:
    values: list[str] = []
    for chapter in schema["chapters"]:
        heading = chapter.get("heading")
        if heading:
            values.append(heading)
        values.extend(value for value in chapter.get("subheadings") or [] if value.startswith("## "))
    return values
