#!/usr/bin/env python3
"""Check for duplicate papers in the output directory before creating a new workspace.

Uses paper_index.json for fast lookup instead of scanning all directories.

Exit codes:
  0 — no duplicate found, or overwrite was explicitly selected
  1 — duplicate found and execution must stop
  2 — an existing workspace was explicitly selected for resume
"""

import argparse
import sys
from pathlib import Path

from common import extract_arxiv_id, fetch_arxiv_metadata, read_json
from paper_index import ensure_index, query_duplicates


def prompt_user_overwrite(matches):
    """Ask user whether to overwrite. Returns True if overwrite, False otherwise."""
    print("\n⚠️  发现已存在的同名论文笔记：")
    for match in matches:
        title = match.get("title", "未知标题")
        print(f"  📁 {match['dir_name']}  (匹配方式: {match['match_by']}, 标题: {title})")
    print()

    if not sys.stdin.isatty():
        raise RuntimeError("Interactive duplicate prompt is unavailable on a non-TTY input.")
    while True:
        answer = input("是否覆盖已有笔记？(y/n): ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("请输入 y 或 n")


def main():
    parser = argparse.ArgumentParser(description="Check for duplicate papers in output directory.")
    parser.add_argument("--input", required=True, help="arXiv URL or ID")
    parser.add_argument("--root", default="output", help="Output root directory")
    parser.add_argument("--reuse", default="", help="Specify an existing workspace directory name to reuse")
    parser.add_argument("--force", action="store_true", help="Compatibility alias for --on-duplicate overwrite")
    parser.add_argument(
        "--on-duplicate",
        choices=("abort", "resume", "overwrite", "prompt"),
        default="abort",
        help="Deterministic duplicate policy; defaults to the safe non-interactive abort mode.",
    )
    args = parser.parse_args()

    output_root = Path(args.root).resolve()
    if not output_root.exists():
        sys.exit(0)

    # --reuse: user explicitly wants to use an existing workspace
    if args.reuse:
        reuse_path = output_root / args.reuse
        if reuse_path.is_dir():
            parsed_input = extract_arxiv_id(args.input)
            metadata_path = reuse_path / "metadata.json"
            if parsed_input and metadata_path.exists():
                reused_metadata = read_json(metadata_path)
                if reused_metadata.get("arxiv_id") != parsed_input[0]:
                    print(
                        f"❌ --reuse workspace belongs to {reused_metadata.get('arxiv_id')}, not {parsed_input[0]}",
                        file=sys.stderr,
                    )
                    sys.exit(1)
            print(f"✅ 复用已有论文笔记: {args.reuse}")
            print(f"REUSE_WORKSPACE={reuse_path}")
            sys.exit(2)
        else:
            print(f"❌ 指定的论文笔记目录不存在: {args.reuse}", file=sys.stderr)
            # List available directories from index
            index_data = ensure_index(output_root)
            print("可用的目录:", file=sys.stderr)
            for paper in index_data["papers"]:
                print(f"  📁 {paper['dir_name']}", file=sys.stderr)
            sys.exit(1)

    # Resolve arxiv_id and title from input
    parsed = extract_arxiv_id(args.input)
    if not parsed:
        sys.exit(0)

    base_id, version = parsed
    try:
        metadata = fetch_arxiv_metadata(base_id, version)
        title = metadata.get("title") or ""
    except Exception:
        title = ""

    # Query index for duplicates
    index_data = ensure_index(output_root)
    matches = query_duplicates(index_data, base_id, title)
    if not matches:
        sys.exit(0)

    policy = "overwrite" if args.force else args.on_duplicate
    if policy == "overwrite":
        print(f"⚡ --force 模式: 覆盖已有笔记 {matches[0]['dir_name']}")
        sys.exit(0)

    if policy == "resume":
        print(f"RESUME_WORKSPACE={output_root / matches[0]['dir_name']}")
        sys.exit(2)

    if policy == "abort":
        print(f"Duplicate paper exists: {matches[0]['dir_name']}", file=sys.stderr)
        print("Use --resume <dir>, --on-duplicate resume, or --on-duplicate overwrite explicitly.", file=sys.stderr)
        sys.exit(1)

    overwrite = prompt_user_overwrite(matches)
    if overwrite:
        print("✅ 用户选择覆盖，继续执行 pipeline...")
        sys.exit(0)
    else:
        print("\n❌ 用户选择不覆盖，退出。")
        print(f"💡 如需直接使用已有笔记，可运行:")
        print(f"   bash scripts/run_pipeline.sh \"{args.input}\" --reuse \"{matches[0]['dir_name']}\"")
        sys.exit(1)


if __name__ == "__main__":
    main()
