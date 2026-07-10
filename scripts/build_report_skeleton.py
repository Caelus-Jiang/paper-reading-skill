#!/usr/bin/env python3
"""Create a canonical, non-destructive chapter scaffold and initial report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import atomic_write_text, get_workspace, read_json, write_json
from merge_chapters import merge_workspace
from report_schema import DEFAULT_SCHEMA_PATH, load_report_schema


PLACEHOLDER = "<!-- PAPER_READING_PLACEHOLDER: replace with evidence-backed content -->"


def yaml_string(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def frontmatter_fragment(metadata: dict) -> str:
    arxiv_id = str(metadata.get("paper_id_with_version") or metadata.get("arxiv_id") or "")
    year_text = "20" + arxiv_id[:2] if len(arxiv_id) >= 2 and arxiv_id[:2].isdigit() else "null"
    authors = metadata.get("authors") or []
    institutions = metadata.get("institutions") or []
    aliases = metadata.get("aliases") or []
    return "\n".join(
        [
            "---",
            f"title: {yaml_string(metadata.get('title') or '')}",
            f"authors: {yaml_string(authors)}",
            f"institutions: {yaml_string(institutions)}",
            f"venue: {yaml_string(metadata.get('venue') or 'arXiv preprint')}",
            f"year: {year_text}",
            f"arxiv_id: {yaml_string(arxiv_id)}",
            f"arxiv_url: {yaml_string(metadata.get('arxiv_abs_url') or '')}",
            f"hjfy_url: {yaml_string(metadata.get('hjfy_url') or '')}",
            f"papers_cool_url: {yaml_string(metadata.get('papers_cool_url') or '')}",
            'research_area: ""',
            "tags:",
            "  - paper-reading",
            f"aliases: {yaml_string(aliases)}",
            "cssclasses:",
            "  - paper-reading-report",
            "---",
            "",
            "> [!abstract] 一句话概括",
            f"> {PLACEHOLDER}",
        ]
    )


def table_for_heading(heading: str) -> str | None:
    if heading.startswith("### 1.3 "):
        return "| 主张 ID | 主张内容 | 原文位置 | 证据类型 | 证据强度 | reviewer 结论 |\n|---|---|---|---|---|---|\n| C1 | PAPER_READING_PLACEHOLDER |  |  |  |  |"
    if heading.startswith("### 3.1 "):
        return "| 实验组 | 对应主张 | 是否充分验证 | 缺失项 |\n|---|---|---|---|\n| PAPER_READING_PLACEHOLDER |  |  |  |"
    if heading.startswith("### 3.3 "):
        return "| 设置 / 数据集 | 方法 | 指标 | 数值 | 审稿人提示 |\n|---|---|---|---|---|\n| PAPER_READING_PLACEHOLDER |  |  |  |  |"
    if heading.startswith("### 4.5 "):
        return "| 论文标题 | arXiv ID | 作者 / 年份 | 来源 / 类型 | 与原论文关系 | 一句话概述 |\n|---|---|---|---|---|---|\n| PAPER_READING_PLACEHOLDER |  |  |  |  |  |"
    return None


def chapter_fragment(chapter: dict) -> str:
    blocks = [chapter["heading"]]
    for heading in chapter.get("subheadings") or []:
        blocks.extend(["", heading, "", PLACEHOLDER])
        table = table_for_heading(heading)
        if table:
            blocks.extend(["", table])
    return "\n".join(blocks).rstrip() + "\n"


def quicklook_fragment(chapter: dict) -> str:
    prompts = {
        "### 0.1 ": ["- **输入 / 输出 / 目标 / 约束 / 假设**：PAPER_READING_PLACEHOLDER"],
        "### 0.2 ": ["- **基本困难与证据**：PAPER_READING_PLACEHOLDER"],
        "### 0.3 ": ["- **Inspiration -> Insight -> 洞见类型**：PAPER_READING_PLACEHOLDER"],
        "### 0.4 ": ["- 【PAPER_READING_PLACEHOLDER】 -> 【PAPER_READING_PLACEHOLDER】 -> 【PAPER_READING_PLACEHOLDER】"],
        "### 0.5 ": [
            "1. **情境延伸**：PAPER_READING_PLACEHOLDER",
            "2. **坏数据性质**：PAPER_READING_PLACEHOLDER",
            "3. **最值得写成论文的困难**：PAPER_READING_PLACEHOLDER",
        ],
        "### 0.6 ": ["- PAPER_READING_PLACEHOLDER？"],
    }
    blocks = [chapter["heading"]]
    for heading in chapter.get("subheadings") or []:
        lines = next((value for prefix, value in prompts.items() if heading.startswith(prefix)), [PLACEHOLDER])
        blocks.extend(["", heading, "", *lines])
    return "\n".join(blocks).rstrip() + "\n"


def appendix_fragment(chapter: dict) -> str:
    return "\n".join(
        [
            chapter["heading"],
            "",
            PLACEHOLDER,
            "",
            chapter["subheadings"][0],
            "",
            PLACEHOLDER,
        ]
    ) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--root", default="output")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA_PATH))
    parser.add_argument("--overwrite-report", action="store_true")
    args = parser.parse_args()

    workspace, ids = get_workspace(Path(args.root).resolve(), args.input)
    metadata = read_json(workspace / "metadata.json")
    report_path = workspace / f"{ids['arxiv_id']}_阅读报告.md"
    if report_path.exists() and not args.overwrite_report:
        print("Report already exists; skeleton left untouched:", report_path)
        return 0

    schema_path = Path(args.schema).resolve()
    schema = load_report_schema(schema_path)
    chapters_dir = workspace / "cache" / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    claims_path = workspace / "cache" / "claims.json"
    if not claims_path.exists() or args.overwrite_report:
        write_json(
            claims_path,
            {
                "schema_version": "1.0",
                "claims": [],
                "required_fields": [
                    "claim_id",
                    "claim",
                    "claim_kind",
                    "paper_location",
                    "evidence",
                    "evidence_strength",
                    "reviewer_conclusion"
                ],
                "allowed_claim_kind": ["author_explicit", "author_implicit", "reviewer_inference"],
                "allowed_evidence_strength": ["strong", "partial", "indirect", "insufficient"],
                "code_paper_audit": {"official_code_url": "", "revision": "", "findings": []}
            },
        )
    for chapter in schema["chapters"]:
        if chapter["file"] == "00_frontmatter.md":
            content = frontmatter_fragment(metadata)
        elif chapter["file"] == "00_quicklook.md":
            content = quicklook_fragment(chapter)
        elif chapter["file"] == "07_appendices.md":
            content = appendix_fragment(chapter)
        else:
            content = chapter_fragment(chapter)
        atomic_write_text(chapters_dir / chapter["file"], content)

    merge_workspace(
        workspace,
        report_path,
        schema_path,
        delete_fragments=False,
        overwrite_report=args.overwrite_report,
    )
    print("Report skeleton created without H1:", report_path)
    print("Chapter fragments:", chapters_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
