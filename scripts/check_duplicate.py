#!/usr/bin/env python3
"""Check for duplicate papers in the output directory before creating a new workspace.

Uses paper_index.json for fast lookup instead of scanning all directories.

Exit codes:
  0 — no duplicate found, or user confirmed overwrite
  1 — duplicate found and user chose not to overwrite
  2 — user specified --reuse with a valid existing workspace
"""

import argparse
import sys
from pathlib import Path

from common import extract_arxiv_id, fetch_arxiv_metadata
from paper_index import ensure_index, query_duplicates


def prompt_user_overwrite(matches):
    """Ask user whether to overwrite. Returns True if overwrite, False otherwise."""
    print("\n⚠️  发现已存在的同名论文笔记：")
    for match in matches:
        title = match.get("title", "未知标题")
        print(f"  📁 {match['dir_name']}  (匹配方式: {match['match_by']}, 标题: {title})")
    print()

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
    parser.add_argument("--force", action="store_true", help="Skip confirmation and overwrite directly")
    args = parser.parse_args()

    output_root = Path(args.root).resolve()
    if not output_root.exists():
        sys.exit(0)

    # --reuse: user explicitly wants to use an existing workspace
    if args.reuse:
        reuse_path = output_root / args.reuse
        if reuse_path.is_dir():
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

    if args.force:
        print(f"⚡ --force 模式: 覆盖已有笔记 {matches[0]['dir_name']}")
        sys.exit(0)

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
