#!/usr/bin/env python3
"""Run quality checks for a generated paper-reading Markdown report."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import find_disallowed_control_chars, get_workspace

IMAGE_LINK_RE = re.compile(r"!\[[^\]]*\]\(([^)\n]+)\)")
BLOCKED_REPORT_MARKERS = [
    "TO" + "DO",
    "T" + "BD",
    "to" + "do",
    "待" + "补" + "充",
    "place" + "holder",
    "原始" + "数值",
    "变化后" + "数值",
    "假设" + "实现",
]
REQUIRED_HEADINGS = [
    "## 1. 论文核心观点与主张的系统梳理",
    "## 2. 关键论据、理论基础与数学方法的深度解析",
    "## 3. 实验设计与实验结果的充分性分析",
    "## 4. 与当前领域主流共识及反对观点的关系",
    "## 5. 对论文理论体系的严肃反驳与系统性质疑",
    "## 6. 最终结论",
    "## 附录 A：关键实验表与消融实验表",
    "## 附录 B：本报告引用的关键外部文献",
]
SUSPICIOUS_ENCODING_TOKENS = [
    "璁烘枃",
    "闃呰",
    "鍩烘湰",
    "闄勫綍",
    "寰呰ˉ",
    "鏈枃",
    "鏂囩尞",
    "锛",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check paper-reading report quality before delivery.")
    parser.add_argument("--paper-input", help="arXiv URL/id or workspace name used to locate the report.")
    parser.add_argument("--report-path", help="Direct path to the Markdown report.")
    parser.add_argument("--root", default="output", help="Root output directory used with --paper-input.")
    return parser.parse_args()


def resolve_report_path(args: argparse.Namespace) -> Path:
    if args.report_path:
        return Path(args.report_path).expanduser().resolve()
    if not args.paper_input:
        raise ValueError("Pass either --report-path or --paper-input.")

    root = Path(args.root).expanduser().resolve()
    workspace, ids = get_workspace(root, args.paper_input)
    primary_report = workspace / f"{ids['arxiv_id']}_阅读报告.md"
    if primary_report.exists():
        return primary_report

    candidates = sorted(workspace.glob("*_阅读报告.md"))
    if len(candidates) == 1:
        return candidates[0]
    raise FileNotFoundError(f"Could not locate report in workspace: {workspace}")


def normalize_markdown_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    return target.replace("\\", "/")


def is_external_target(target: str) -> bool:
    return target.startswith(("http://", "https://", "mailto:", "#"))


def check_required_headings(text: str) -> list[str]:
    return [heading for heading in REQUIRED_HEADINGS if heading not in text]


def check_blocked_markers(text: str) -> list[str]:
    return [marker for marker in BLOCKED_REPORT_MARKERS if marker in text]


def check_suspicious_encoding(text: str) -> list[str]:
    hits = [token for token in SUSPICIOUS_ENCODING_TOKENS if token in text]
    if text.count("\ufffd"):
        hits.append("replacement character")
    return hits


def check_image_links(report_path: Path, text: str) -> tuple[int, list[str]]:
    image_targets = [normalize_markdown_target(match.group(1)) for match in IMAGE_LINK_RE.finditer(text)]
    missing_targets: list[str] = []
    for target in image_targets:
        if is_external_target(target):
            continue
        resolved = (report_path.parent / target.lstrip("./")).resolve()
        if not resolved.exists():
            missing_targets.append(target)
    return len(image_targets), missing_targets


def check_formula_compatibility(text: str) -> list[str]:
    issues: list[str] = []
    # \tag{N} is allowed per SKILL.md for formula numbering inside display blocks
    # Check each code block individually for $ symbols
    code_blocks = re.findall(r'```[\s\S]*?```', text)
    for block in code_blocks:
        if '$' in block:
            issues.append("code fences appear to contain math delimiters; verify math is not written as code")
            break
    return issues


def main() -> int:
    args = parse_args()
    report_path = resolve_report_path(args)
    text = report_path.read_text(encoding="utf-8-sig")

    errors: list[str] = []

    control_chars = find_disallowed_control_chars(text)
    if control_chars:
        preview = ", ".join(f"offset={offset}:0x{code_point:02x}" for offset, code_point in control_chars[:10])
        errors.append(f"disallowed control characters: {preview}")

    missing_headings = check_required_headings(text)
    if missing_headings:
        errors.append("missing required headings: " + ", ".join(missing_headings))

    blocked_marker_hits = check_blocked_markers(text)
    if blocked_marker_hits:
        errors.append("blocked unfinished markers remain: " + ", ".join(blocked_marker_hits))

    encoding_hits = check_suspicious_encoding(text)
    if encoding_hits:
        errors.append("suspicious encoding artifacts: " + ", ".join(encoding_hits))

    image_count, missing_images = check_image_links(report_path, text)
    if image_count == 0:
        errors.append("report contains no Markdown image links")
    if missing_images:
        errors.append("missing local image targets: " + ", ".join(missing_images[:20]))

    formula_issues = check_formula_compatibility(text)
    errors.extend(formula_issues)

    if errors:
        print(f"ERROR: report quality check failed: {report_path}", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"OK: report quality check passed: {report_path}")
    print(f"Images checked: {image_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
