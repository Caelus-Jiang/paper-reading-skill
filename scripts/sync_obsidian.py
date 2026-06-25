#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path

from common import get_workspace


IMAGE_LINK_RE = re.compile(r"!\[([^\]]*)\]\(([^)\n]+)\)")
OBSIDIAN_EMBED_RE = re.compile(r"!\[\[([^\]]+)\]\]")
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?\n)---\s*\n", re.DOTALL)
LOCAL_CONFIG_PATH = Path(__file__).resolve().parents[1] / "paper-reading.local.json"
OBSIDIAN_NOTES_ENV = "OBSIDIAN_PAPER_NOTES_DIR"
OBSIDIAN_IMAGES_ENV = "OBSIDIAN_IMAGE_DIR"


def normalize_markdown_target(target: str) -> tuple[str, bool]:
    stripped = target.strip()
    if stripped.startswith("<") and stripped.endswith(">"):
        return stripped[1:-1].strip(), True
    return stripped, False


def format_markdown_target(target: str) -> str:
    normalized = target.replace("\\", "/")
    if any(ch.isspace() for ch in normalized):
        return f"<{normalized}>"
    return normalized


def has_frontmatter(markdown: str) -> bool:
    """Check whether the markdown text starts with a YAML frontmatter block."""
    return bool(FRONTMATTER_RE.match(markdown))


def extract_frontmatter(markdown: str) -> dict[str, str] | None:
    """Parse simple key: value pairs from an existing frontmatter block."""
    match = FRONTMATTER_RE.match(markdown)
    if not match:
        return None
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def build_default_frontmatter(report_name: str, workspace_name: str) -> str:
    """Generate a minimal frontmatter block when the report lacks one."""
    title = report_name.replace("_阅读报告.md", "").replace("_", " ")
    arxiv_id = workspace_name.split("_")[0] if "_" in workspace_name else workspace_name
    tags_block = "tags:\n  - paper-reading\ncssclasses:\n  - paper-reading-report"
    return (
        "---\n"
        f'title: "{title}"\n'
        f'arxiv_id: "{arxiv_id}"\n'
        f"{tags_block}\n"
        "---\n\n"
    )


def ensure_frontmatter(markdown: str, report_name: str, workspace_name: str) -> str:
    """Inject a default frontmatter if the report does not already have one."""
    if has_frontmatter(markdown):
        return markdown
    return build_default_frontmatter(report_name, workspace_name) + markdown


def convert_to_obsidian_embeds(markdown: str, link_map: dict[str, str]) -> str:
    """Optionally convert standard Markdown image links to Obsidian embed syntax.

    Only converts images whose paths appear in link_map (i.e., images that were
    actually copied into the vault). External URLs and already-embedded images
    are left untouched.
    """
    def replace(match: re.Match[str]) -> str:
        alt_text = match.group(1)
        raw_target = match.group(2)
        target, _ = normalize_markdown_target(raw_target)
        lookup_key = target.replace("\\", "/").lstrip("./")
        if lookup_key not in link_map:
            return match.group(0)
        vault_relative = Path(link_map[lookup_key]).as_posix()
        if alt_text:
            return f"![[{vault_relative}|{alt_text}]]"
        return f"![[{vault_relative}]]"

    return IMAGE_LINK_RE.sub(replace, markdown)


def rewrite_image_links(markdown: str, link_map: dict[str, str]) -> str:
    """Rewrite standard Markdown image links to point at vault-local paths.

    This preserves the standard ![alt](path) syntax. Wikilinks and Obsidian
    embed syntax (![[]]) are never touched by this function.
    """
    def replace(match: re.Match[str]) -> str:
        alt_text = match.group(1)
        raw_target = match.group(2)
        target, _ = normalize_markdown_target(raw_target)
        lookup_key = target.replace("\\", "/").lstrip("./")
        if lookup_key not in link_map:
            return match.group(0)
        return f"![{alt_text}]({format_markdown_target(link_map[lookup_key])})"

    return IMAGE_LINK_RE.sub(replace, markdown)


def copy_images(workspace: Path, obsidian_images_dir: Path) -> dict[str, Path]:
    source_images_dir = workspace / "images"
    if not source_images_dir.exists():
        return {}

    target_paper_images_dir = obsidian_images_dir / workspace.name
    target_paper_images_dir.mkdir(parents=True, exist_ok=True)

    copied: dict[str, Path] = {}
    for source in sorted(path for path in source_images_dir.rglob("*") if path.is_file()):
        relative_to_images = source.relative_to(source_images_dir)
        target = target_paper_images_dir / relative_to_images
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied[f"images/{relative_to_images.as_posix()}"] = target
    return copied


def build_link_map(copied_images: dict[str, Path], report_target: Path) -> dict[str, str]:
    note_dir = report_target.parent
    return {
        source_key: Path(os.path.relpath(target, start=note_dir)).as_posix()
        for source_key, target in copied_images.items()
    }


def load_local_config() -> dict:
    if not LOCAL_CONFIG_PATH.exists():
        return {}
    return json.loads(LOCAL_CONFIG_PATH.read_text(encoding="utf-8"))


def save_local_config(config: dict) -> None:
    LOCAL_CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def prompt_for_path(label: str) -> str:
    while True:
        try:
            value = input(f"{label}: ").strip()
        except EOFError:
            raise RuntimeError(
                f"Missing {label}. Pass it as an argument, set the environment variable, "
                f"or add it to {LOCAL_CONFIG_PATH}."
            ) from None
        if value:
            return value
        print("Path cannot be empty.")


def resolve_obsidian_dirs(args: argparse.Namespace) -> tuple[Path, Path]:
    config = load_local_config()
    obsidian_config = config.setdefault("obsidian", {})

    notes_dir = (
        args.notes_dir
        or os.environ.get(OBSIDIAN_NOTES_ENV)
        or obsidian_config.get("notes_dir")
    )
    images_dir = (
        args.images_dir
        or os.environ.get(OBSIDIAN_IMAGES_ENV)
        or obsidian_config.get("images_dir")
    )
    should_save = False

    if not notes_dir:
        notes_dir = prompt_for_path("Obsidian notes directory")
        obsidian_config["notes_dir"] = notes_dir
        should_save = True

    if not images_dir:
        images_dir = prompt_for_path("Obsidian images directory")
        obsidian_config["images_dir"] = images_dir
        should_save = True

    if should_save:
        save_local_config(config)
        print("Saved local Obsidian paths:", LOCAL_CONFIG_PATH)

    return Path(notes_dir).expanduser().resolve(), Path(images_dir).expanduser().resolve()


def resolve_report_source(root: Path, paper_input: str | None, report_path: str | None) -> tuple[Path, Path]:
    if report_path:
        source = Path(report_path).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"Report not found: {source}")
        return source.parent, source

    if not paper_input:
        raise ValueError("Pass either --paper-input or --report-path.")

    workspace, ids = get_workspace(root, paper_input)
    report_source = workspace / f"{ids['arxiv_id']}_阅读报告.md"
    if not report_source.exists():
        candidates = sorted(workspace.glob("*_阅读报告.md"))
        if len(candidates) == 1:
            report_source = candidates[0]
        elif ids.get("report_filename"):
            report_source = workspace / ids["report_filename"]
    if not report_source.exists():
        raise FileNotFoundError(f"Report not found: {report_source}")
    return workspace, report_source


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy a generated report and images into an Obsidian vault.")
    parser.add_argument("--paper-input", help="arXiv URL/id or workspace name used to locate the report.")
    parser.add_argument("--report-path", help="Direct path to the Markdown report.")
    parser.add_argument("--input", dest="legacy_input", help=argparse.SUPPRESS)
    parser.add_argument("--root", default="output")
    parser.add_argument("--notes-dir", help="Obsidian folder for paper note Markdown files.")
    parser.add_argument("--images-dir", help="Obsidian folder for copied paper images.")
    parser.add_argument(
        "--obsidian-embeds",
        action="store_true",
        help="Convert standard Markdown image links to Obsidian ![[]] embed syntax.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    notes_dir, images_dir = resolve_obsidian_dirs(args)
    workspace, report_source = resolve_report_source(root, args.paper_input or args.legacy_input, args.report_path)

    notes_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    report_target = notes_dir / report_source.name
    copied_images = copy_images(workspace, images_dir)
    link_map = build_link_map(copied_images, report_target)

    report_text = report_source.read_text(encoding="utf-8-sig")

    # Ensure the report has a YAML frontmatter block
    report_text = ensure_frontmatter(report_text, report_source.name, workspace.name)

    # Rewrite image paths to vault-local relative paths
    if args.obsidian_embeds:
        rewritten_report = convert_to_obsidian_embeds(report_text, link_map)
    else:
        rewritten_report = rewrite_image_links(report_text, link_map)

    report_target.write_text(rewritten_report, encoding="utf-8")

    had_frontmatter = has_frontmatter(report_source.read_text(encoding="utf-8-sig"))
    print("Obsidian report synced:", report_target)
    print("Obsidian images synced:", images_dir / workspace.name)
    print(f"Image links rewritten: {len(link_map)}")
    print(f"Frontmatter: {'existing' if had_frontmatter else 'injected'}")
    if args.obsidian_embeds:
        print("Embed syntax: converted to Obsidian ![[]] format")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
