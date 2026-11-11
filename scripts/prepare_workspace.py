#!/usr/bin/env python3
import argparse
from datetime import datetime, timezone
from pathlib import Path

from common import (
    arxiv_id_with_version, compact_workspace_metadata, ensure_workspace,
    read_workspace_metadata, resolve_ids, workspace_report_path, write_json,
)


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
        args.workspace_name or None,
    )

    metadata_path = workspace / "metadata.json"
    existing = {}
    if metadata_path.exists():
        existing = compact_workspace_metadata(workspace, read_workspace_metadata(metadata_path))
    now = datetime.now(timezone.utc).isoformat()
    version_history = list(existing.get("version_history") or [])
    for versioned_id in (arxiv_id_with_version(existing), arxiv_id_with_version(ids)):
        if versioned_id and versioned_id not in version_history:
            version_history.append(versioned_id)

    metadata = {
        **existing,
        **ids,
        "created_at": existing.get("created_at") or now,
        "resolved_at": now,
        "version_history": version_history,
    }
    write_json(metadata_path, metadata)
    print(workspace)
    print(workspace_report_path(workspace, metadata))


if __name__ == "__main__":
    main()
