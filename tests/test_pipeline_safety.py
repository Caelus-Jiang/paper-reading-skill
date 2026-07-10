from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import common  # noqa: E402
import pipeline_state  # noqa: E402


def metadata(workspace: Path, version: str = "v1") -> dict:
    base = "2401.12345"
    versioned = f"{base}{version}"
    return {
        "input": base,
        "arxiv_id": base,
        "title": "Fixture Paper",
        "workspace_name": workspace.name,
        "version": version,
        "paper_id_with_version": versioned,
        "arxiv_abs_url": f"https://arxiv.org/abs/{versioned}",
        "arxiv_pdf_url": f"https://arxiv.org/pdf/{versioned}.pdf",
        "hjfy_url": f"https://hjfy.top/arxiv/{versioned}",
        "papers_cool_url": f"https://papers.cool/arxiv/{versioned}",
        "ar5iv_url": f"https://ar5iv.org/html/{versioned}",
        "arxiv_src_url": f"https://arxiv.org/src/{versioned}",
        "workspace": str(workspace),
        "report_path": str(workspace / f"{base}_阅读报告.md"),
    }


class PipelineSafetyTests(unittest.TestCase):
    def test_skeleton_never_overwrites_without_explicit_flag(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "output"
            workspace = root / "2401.12345_Fixture_Paper"
            for name in ("raw", "images", "cache", "logs"):
                (workspace / name).mkdir(parents=True, exist_ok=True)
            common.write_json(workspace / "metadata.json", metadata(workspace))
            command = [
                sys.executable,
                str(SCRIPTS / "build_report_skeleton.py"),
                "--input",
                workspace.name,
                "--root",
                str(root),
            ]
            subprocess.run(command, check=True, capture_output=True, text=True)
            report = workspace / "2401.12345_阅读报告.md"
            report.write_text("DO NOT OVERWRITE\n", encoding="utf-8")
            subprocess.run(command, check=True, capture_output=True, text=True)
            self.assertEqual(report.read_text(encoding="utf-8"), "DO NOT OVERWRITE\n")

    def test_explicit_arxiv_version_bypasses_mismatched_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "2401.12345_Fixture_Paper"
            workspace.mkdir()
            common.write_json(workspace / "metadata.json", metadata(workspace, "v1"))
            v2 = metadata(workspace, "v2")
            with mock.patch.object(common, "resolve_ids", return_value=v2) as resolver:
                _workspace, ids = common.get_workspace(root, "2401.12345v2")
            resolver.assert_called_once()
            self.assertEqual(ids["version"], "v2")

    def test_stage_fingerprint_changes_when_input_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            (workspace / "raw").mkdir(parents=True)
            (workspace / "cache" / "pipeline_state").mkdir(parents=True)
            common.write_json(workspace / "metadata.json", metadata(workspace))
            source = workspace / "raw" / "source.tar"
            source.write_bytes(b"one")
            script = SCRIPTS / "extract_references.py"
            first, _ = pipeline_state.fingerprint(workspace, "extract_references", script, PROJECT_ROOT)
            source.write_bytes(b"two")
            second, _ = pipeline_state.fingerprint(workspace, "extract_references", script, PROJECT_ROOT)
            self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
