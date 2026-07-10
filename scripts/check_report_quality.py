#!/usr/bin/env python3
"""Strict, schema-driven acceptance checks for paper-reading reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import fitz
import yaml
from PIL import Image

from common import find_disallowed_control_chars, get_workspace
from report_schema import DEFAULT_SCHEMA_PATH, load_report_schema, ordered_headings


FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
IMAGE_LINK_RE = re.compile(r"!\[([^\]]*)\]\(([^)\n]+)\)")
OBSIDIAN_IMAGE_RE = re.compile(r"!\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]")
PLACEHOLDER_RE = re.compile(r"PAPER_READING_PLACEHOLDER|\bTODO\b|\bTBD\b|待补充|placeholder", re.I)
MOJIBAKE_TOKENS = ("璁烘枃", "闃呰", "鍩烘湰", "闄勫綍", "鏈枃", "鏂囩尞", "锛")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run strict paper-reading report acceptance checks.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--paper-input")
    source.add_argument("--report-path")
    parser.add_argument("--root", default="output")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA_PATH))
    parser.add_argument("--require-chapter-manifest", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_output")
    return parser.parse_args()


def resolve_report(args: argparse.Namespace) -> tuple[Path, Path]:
    if args.report_path:
        report = Path(args.report_path).expanduser().resolve()
        return report, report.parent
    workspace, ids = get_workspace(Path(args.root).expanduser().resolve(), args.paper_input)
    report = workspace / f"{ids['arxiv_id']}_阅读报告.md"
    if not report.exists():
        candidates = sorted(workspace.glob("*_阅读报告.md"))
        if len(candidates) == 1:
            report = candidates[0]
    return report, workspace


def strip_code_fences(text: str) -> str:
    return re.sub(r"```[\s\S]*?```|~~~[\s\S]*?~~~", "", text)


def parse_frontmatter(text: str) -> tuple[dict, int, list[str]]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, 0, ["report must start with YAML frontmatter"]
    try:
        value = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        return {}, match.end(), [f"invalid YAML frontmatter: {exc}"]
    if not isinstance(value, dict):
        return {}, match.end(), ["YAML frontmatter must be a mapping"]
    return value, match.end(), []


def check_frontmatter(text: str, schema: dict) -> tuple[dict, list[str]]:
    frontmatter, end, errors = parse_frontmatter(text)
    if errors:
        return frontmatter, errors
    rules = schema["frontmatter"]
    missing = [key for key in rules["required_keys"] if key not in frontmatter]
    if missing:
        errors.append("frontmatter missing required keys: " + ", ".join(missing))
    empty_required = [
        key for key in rules["required_keys"]
        if key in frontmatter and frontmatter[key] in (None, "", [])
    ]
    if empty_required:
        errors.append("frontmatter required values are empty: " + ", ".join(empty_required))
    forbidden = [key for key in rules["forbidden_keys"] if key in frontmatter]
    if forbidden:
        errors.append("frontmatter contains forbidden keys: " + ", ".join(forbidden))
    tags = frontmatter.get("tags") if isinstance(frontmatter.get("tags"), list) else []
    for tag in rules.get("required_tags", []):
        if tag not in tags:
            errors.append(f"frontmatter tags must include: {tag}")
    cssclasses = frontmatter.get("cssclasses") if isinstance(frontmatter.get("cssclasses"), list) else []
    for cssclass in rules.get("required_cssclasses", []):
        if cssclass not in cssclasses:
            errors.append(f"frontmatter cssclasses must include: {cssclass}")
    remainder = text[end:].lstrip("\n")
    if not remainder.startswith(schema["abstract_prefix"]):
        errors.append("frontmatter must be followed immediately by the canonical abstract callout")
    return frontmatter, errors


def check_heading_schema(text: str, schema: dict) -> list[str]:
    visible = strip_code_fences(text)
    errors = []
    if not schema.get("allow_h1", False) and re.search(r"(?m)^# [^#]", visible):
        errors.append("H1 headings are forbidden; start with YAML and the abstract callout")
    last_position = -1
    for heading in ordered_headings(schema):
        occurrences = [match.start() for match in re.finditer(rf"(?m)^{re.escape(heading)}\s*$", visible)]
        if not occurrences:
            errors.append(f"missing required heading: {heading}")
            continue
        if len(occurrences) > 1:
            errors.append(f"duplicate required heading: {heading}")
        if occurrences[0] <= last_position:
            errors.append(f"required heading is out of order: {heading}")
        last_position = occurrences[0]
    return errors


def section_text(text: str, heading: str) -> str:
    match = re.search(rf"(?m)^{re.escape(heading)}\s*$", text)
    if not match:
        return ""
    level = len(heading) - len(heading.lstrip("#"))
    next_heading = re.search(rf"(?m)^#{{1,{level}}}\s+", text[match.end():])
    end = match.end() + next_heading.start() if next_heading else len(text)
    return text[match.end():end]


def markdown_table_has_data(section: str) -> bool:
    rows = [line.strip() for line in section.splitlines() if line.strip().startswith("|") and line.strip().endswith("|")]
    if len(rows) < 3:
        return False
    data_rows = [row for row in rows[2:] if not re.fullmatch(r"[|:\-\s]+", row)]
    return any(not PLACEHOLDER_RE.search(row) and any(cell.strip() for cell in row.strip("|").split("|")) for row in data_rows)


def check_required_tables(text: str, schema: dict) -> list[str]:
    errors = []
    for requirement in schema.get("required_tables", []):
        content = section_text(text, requirement["section"])
        if not markdown_table_has_data(content):
            errors.append(f"required {requirement['kind']} table has no populated data row: {requirement['section']}")
    claims = section_text(text, "### 1.3 核心观点（Claims）的逐条梳理")
    if "证据" not in claims:
        errors.append("claims section must distinguish evidence type/strength from reviewer conclusions")
    return errors


def normalize_target(raw: str) -> str:
    target = raw.strip()
    if target.startswith("<") and target.endswith(">"):
        return target[1:-1].strip().replace("\\", "/")
    title_match = re.match(r'^(.*?)(?:\s+["\'][^"\']*["\'])?$', target)
    return (title_match.group(1) if title_match else target).replace("\\", "/")


def validate_image(path: Path) -> str | None:
    try:
        if path.suffix.lower() == ".pdf":
            with fitz.open(path) as document:
                if document.page_count == 0:
                    return "PDF image target has no pages"
        else:
            with Image.open(path) as image:
                image.verify()
        return None
    except Exception as exc:  # noqa: BLE001
        return str(exc)


def check_images(report_path: Path, workspace: Path, text: str) -> tuple[list[str], list[str], int]:
    errors: list[str] = []
    warnings: list[str] = []
    matches = [(match.start(), normalize_target(match.group(2))) for match in IMAGE_LINK_RE.finditer(text)]
    matches.extend((match.start(), normalize_target(match.group(1))) for match in OBSIDIAN_IMAGE_RE.finditer(text))
    if not matches:
        return ["report contains no image embeds"], warnings, 0

    manifest_paths = set()
    manifest_path = workspace / "cache" / "images_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_paths = {str(item.get("saved_path") or "").lstrip("./") for item in manifest.get("figures", [])}
        except (json.JSONDecodeError, OSError) as exc:
            errors.append(f"invalid images manifest: {exc}")
    else:
        warnings.append("images manifest is missing; provenance could not be checked")

    for position, target in matches:
        if target.startswith(("http://", "https://")):
            warnings.append(f"external image bypasses local provenance: {target}")
            continue
        local = (report_path.parent / target.lstrip("./")).resolve()
        if not local.exists():
            errors.append(f"missing local image: {target}")
            continue
        validation_error = validate_image(local)
        if validation_error:
            errors.append(f"image cannot be decoded ({target}): {validation_error}")
        if manifest_paths and target.lstrip("./") not in manifest_paths:
            warnings.append(f"image is not mapped by images_manifest.json: {target}")
        following = re.sub(r"\s+", " ", text[position:text.find("\n\n", position) if text.find("\n\n", position) != -1 else position + 500])
        if len(following) < 40:
            warnings.append(f"image may lack a nearby explanation: {target}")
    return errors, warnings, len(matches)


def check_math(text: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    visible = strip_code_fences(text)
    if visible.count("$$") % 2:
        errors.append("unbalanced display-math delimiters ($$)")
    displays = re.findall(r"\$\$(.*?)\$\$", visible, flags=re.S)
    for index, body in enumerate(displays, start=1):
        nonempty_lines = [line.strip() for line in body.strip().splitlines() if line.strip()]
        if len(nonempty_lines) > 1 and not re.search(r"\\begin\{(?:aligned|gathered|array|split)\}", body):
            errors.append(f"display formula {index} is multiline without a supported LaTeX environment")
        if any(re.match(r"^[+*-]\s", line) for line in nonempty_lines):
            errors.append(f"display formula {index} contains a bare list-like operator line")
    without_displays = re.sub(r"\$\$.*?\$\$", "", visible, flags=re.S)
    inline_dollars = len(re.findall(r"(?<!\\)\$(?!\$)", without_displays))
    if inline_dollars % 2:
        errors.append("unbalanced inline-math delimiters ($)")
    tags = [int(value) for value in re.findall(r"\\tag\{(\d+)\}", visible)]
    if tags:
        expected = list(range(1, len(tags) + 1))
        if tags != expected:
            errors.append(f"formula tags must be unique and sequential from 1; found {tags}")
    references = [int(value) for value in re.findall(r"式\s*[（(](\d+)[)）]", visible)]
    missing_tags = sorted(set(references) - set(tags))
    if missing_tags:
        errors.append("formula references have no matching \\tag: " + ", ".join(map(str, missing_tags)))
    for code_span in re.findall(r"`([^`\n]+)`", visible):
        if code_span.startswith("$") or re.search(r"\\(?:mathcal|mathbf|lambda|sum|prod|frac|begin)\b", code_span):
            errors.append(f"math-like content is wrapped in backticks: `{code_span[:80]}`")
    if displays and not tags:
        warnings.append("display formulas exist but none are numbered; verify whether key formulas need tags")
    return errors, warnings


def check_chapter_manifest(workspace: Path, report_path: Path, required: bool) -> list[str]:
    path = workspace / "cache" / "chapter_manifest.json"
    if not path.exists():
        return ["chapter manifest is required but missing"] if required else []
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [f"invalid chapter manifest: {exc}"]
    actual = hashlib.sha256(report_path.read_bytes()).hexdigest()
    if manifest.get("report_sha256") != actual:
        return ["chapter manifest hash does not match the current report; merge chapters again"]
    return []


def check_claims_ledger(workspace: Path, required: bool) -> list[str]:
    path = workspace / "cache" / "claims.json"
    if not path.exists():
        return ["claims evidence ledger is required but missing"] if required else []
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [f"invalid claims evidence ledger: {exc}"]
    claims = ledger.get("claims") or []
    if required and not claims:
        return ["claims evidence ledger contains no claims"]
    required_fields = set(ledger.get("required_fields") or [])
    errors = []
    for index, claim in enumerate(claims, start=1):
        missing = sorted(field for field in required_fields if claim.get(field) in (None, "", []))
        if missing:
            errors.append(f"claim ledger item {index} missing values: {', '.join(missing)}")
        if claim.get("claim_kind") not in set(ledger.get("allowed_claim_kind") or []):
            errors.append(f"claim ledger item {index} has invalid claim_kind")
        if claim.get("evidence_strength") not in set(ledger.get("allowed_evidence_strength") or []):
            errors.append(f"claim ledger item {index} has invalid evidence_strength")
    return errors


def check_external_evidence(text: str, schema: dict) -> list[str]:
    errors = [prefix for prefix in schema.get("required_url_prefixes", []) if prefix not in text]
    result = ["missing required URL prefix: " + value for value in errors]
    appendix = section_text(text, "## 附录 B：本报告引用的关键外部文献")
    if not re.search(r"https?://", appendix):
        result.append("Appendix B must contain verified external literature links")
    return result


def run_checks(report_path: Path, workspace: Path, schema: dict, require_manifest: bool) -> tuple[list[str], list[str], dict]:
    if not report_path.exists():
        return [f"report not found: {report_path}"], [], {}
    text = report_path.read_text(encoding="utf-8-sig")
    errors: list[str] = []
    warnings: list[str] = []
    control_chars = find_disallowed_control_chars(text)
    if control_chars:
        errors.append(f"disallowed control characters: {control_chars[:10]}")
    mojibake = [token for token in MOJIBAKE_TOKENS if token in text]
    if "\ufffd" in text or mojibake:
        errors.append("suspicious encoding artifacts: " + ", ".join(mojibake or ["replacement character"]))
    placeholders = sorted(set(match.group(0) for match in PLACEHOLDER_RE.finditer(text)))
    if placeholders:
        errors.append("unfinished placeholders remain: " + ", ".join(placeholders))

    _frontmatter, frontmatter_errors = check_frontmatter(text, schema)
    errors.extend(frontmatter_errors)
    errors.extend(check_heading_schema(text, schema))
    errors.extend(check_required_tables(text, schema))
    image_errors, image_warnings, image_count = check_images(report_path, workspace, text)
    errors.extend(image_errors)
    warnings.extend(image_warnings)
    math_errors, math_warnings = check_math(text)
    errors.extend(math_errors)
    warnings.extend(math_warnings)
    errors.extend(check_external_evidence(text, schema))
    errors.extend(check_chapter_manifest(workspace, report_path, require_manifest))
    errors.extend(check_claims_ledger(workspace, require_manifest))
    return errors, warnings, {"images_checked": image_count, "bytes": len(text.encode("utf-8"))}


def main() -> int:
    args = parse_args()
    report_path, workspace = resolve_report(args)
    schema = load_report_schema(Path(args.schema).resolve())
    errors, warnings, metrics = run_checks(report_path, workspace, schema, args.require_chapter_manifest)
    payload = {"report": str(report_path), "ok": not errors, "errors": errors, "warnings": warnings, "metrics": metrics}
    if args.json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(("OK" if not errors else "ERROR") + f": strict report quality check: {report_path}")
        for error in errors:
            print(f"- ERROR: {error}", file=sys.stderr)
        for warning in warnings:
            print(f"- WARNING: {warning}")
        if metrics:
            print("Metrics:", json.dumps(metrics, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
