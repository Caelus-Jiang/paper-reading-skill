#!/usr/bin/env python3
import argparse
from datetime import datetime, timezone
from pathlib import Path

from common import ensure_workspace, read_json, resolve_ids, write_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--workspace-name", default="", help="Use an explicitly selected existing workspace name.")
    args = parser.parse_args()

    ids = resolve_ids(args.input)
    root = Path(args.root).resolve()
    workspace = ensure_workspace(
        root,
        ids["arxiv_id"],
        ids.get("title"),
        args.workspace_name or ids.get("workspace_name"),
    )
    ids["workspace_name"] = workspace.name

    metadata_path = workspace / "metadata.json"
    existing = read_json(metadata_path) if metadata_path.exists() else {}
    now = datetime.now(timezone.utc).isoformat()
    version_history = list(existing.get("version_history") or [])
    for version in (existing.get("paper_id_with_version"), ids.get("paper_id_with_version")):
        if version and version not in version_history:
            version_history.append(version)

    metadata = {
        **existing,
        **ids,
        "workspace": str(workspace),
        "report_path": str(workspace / f'{ids["arxiv_id"]}_阅读报告.md'),
        "created_at": existing.get("created_at") or now,
        "updated_at": now,
        "resolved_at": now,
        "version_history": version_history,
        "internal_status": existing.get("internal_status") or {
            "hjfy_visit_status": "未尝试",
            "papers_cool_rel_status": "未尝试",
        },
        "paths": {
            "raw_abs_html": str(workspace / "raw" / "abs.html"),
            "raw_pdf": str(workspace / "raw" / "paper.pdf"),
            "raw_ar5iv_html": str(workspace / "raw" / "ar5iv.html"),
            "raw_src_tar": str(workspace / "raw" / "source.tar"),
            "raw_hjfy_html": str(workspace / "raw" / "hjfy.html"),
            "raw_papers_cool_html": str(workspace / "raw" / "papers_cool.html"),
            "cache_references_json": str(workspace / "cache" / "references.json"),
            "cache_images_manifest": str(workspace / "cache" / "images_manifest.json"),
        },
    }
    write_json(metadata_path, metadata)
    print(workspace)
    print(metadata["report_path"])


if __name__ == "__main__":
    main()
