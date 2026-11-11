from __future__ import annotations

import contextlib
import io
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
import fetch_sources  # noqa: E402
import pipeline_state  # noqa: E402
import prepare_workspace  # noqa: E402
from validate_report_text import resolve_report_path  # noqa: E402


def metadata(workspace: Path, version: str = "v1") -> dict:
    base = "2401.12345"
    versioned = f"{base}{version}"
    return {
        "input": base,
        "arxiv_id": base,
        "title": "Fixture Paper",
        "workspace_name": workspace.name,
        "version": version,
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

    def test_prepare_rewrites_legacy_metadata_and_preserves_version_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "2401.12345_Fixture_Paper"
            metadata_path = workspace / "metadata.json"
            legacy = metadata(workspace)
            legacy.pop("version")
            legacy["paper_id_with_version"] = "2401.12345v1"
            legacy["resolved_at"] = legacy["updated_at"] = "2024-01-01T00:00:00+00:00"
            legacy["paths"] = {"raw_pdf": "raw/paper.pdf", "raw_src_tar": "raw/custom.tar"}
            legacy["arxiv_pdf_url"] = "https://mirror.example/paper.pdf"
            legacy["hjfy_url"] = ""
            legacy["internal_status"] = {
                "hjfy_visit_status": "人工确认无需访问",
                "papers_cool_rel_status": "未尝试",
            }
            common.write_json(metadata_path, legacy)

            with mock.patch.object(common, "resolve_ids") as resolver:
                _, ids = common.get_workspace(root, "2401.12345v1")
            resolver.assert_not_called()
            self.assertEqual(ids["version"], "v1")
            self.assertEqual(common.read_json(metadata_path), legacy)

            args = ["prepare_workspace.py", "--root", str(root), "--input", "2401.12345v2"]
            with mock.patch.object(sys, "argv", args), mock.patch.object(
                common, "fetch_arxiv_metadata", return_value={"title": "Fixture Paper", "version": "v2"}
            ), contextlib.redirect_stdout(io.StringIO()):
                prepare_workspace.main()

            saved = common.read_json(metadata_path)
            for field in ("paper_id_with_version", "workspace", "workspace_name", "report_path", "updated_at", "arxiv_abs_url"):
                self.assertNotIn(field, saved)
            self.assertEqual(saved["arxiv_id"], "2401.12345")
            self.assertEqual(saved["version"], "v2")
            self.assertEqual(saved["version_history"], ["2401.12345v1", "2401.12345v2"])
            self.assertEqual(saved["paths"], {"raw_src_tar": "raw/custom.tar"})
            self.assertEqual(saved["internal_status"], {"hjfy_visit_status": "人工确认无需访问"})
            _, ids = common.get_workspace(root, workspace.name)
            self.assertEqual(ids["arxiv_abs_url"], "https://arxiv.org/abs/2401.12345v2")
            self.assertEqual(ids["arxiv_pdf_url"], "https://mirror.example/paper.pdf")
            self.assertEqual(ids["hjfy_url"], "")

    def test_moved_workspace_uses_current_directory_for_generated_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "2401.12345_Fixture_Paper"
            legacy = metadata(root / "old-location" / workspace.name)
            legacy["paths"] = {"raw_pdf": str(Path(legacy["workspace"]) / "raw/paper.pdf")}
            common.write_json(workspace / "metadata.json", legacy)
            report = workspace / "2401.12345_阅读报告.md"
            report.write_text("fixture\n", encoding="utf-8")

            self.assertEqual(resolve_report_path(root, "2401.12345", None), report)
            self.assertEqual(pipeline_state.resolve_paths(workspace, ["{report}"], PROJECT_ROOT), [report])
            compact = common.compact_workspace_metadata(workspace, legacy)
            self.assertFalse({"workspace", "workspace_name", "report_path", "paths"} & compact.keys())
            self.assertEqual(common.read_json(workspace / "metadata.json"), legacy)

    def test_fetch_write_preserves_custom_report_and_manual_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "2401.12345_Fixture_Paper"
            path = workspace / "metadata.json"
            legacy = metadata(workspace)
            legacy["report_path"] = "custom/reading.md"
            legacy["updated_at"] = "2024-01-02T00:00:00+00:00"
            legacy["resolved_at"] = "2024-01-01T00:00:00+00:00"
            legacy["internal_status"] = {"hjfy_visit_status": "已访问", "pipeline": "人工复核"}
            legacy["fetch_results"] = {"hjfy": {"ok": True}}
            common.write_json(path, legacy)
            args = ["fetch_sources.py", "--root", str(root), "--input", workspace.name]
            with mock.patch.object(sys, "argv", args), mock.patch.object(fetch_sources, "build_session"), mock.patch.object(
                fetch_sources, "save_response", return_value={"ok": True, "url": "https://mirror.example/actual"}
            ), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(fetch_sources.main(), 0)

            saved = common.read_json(path)
            self.assertEqual(saved["updated_at"], legacy["updated_at"])
            self.assertEqual(saved["report_path"], "custom/reading.md")
            self.assertEqual(saved["internal_status"], {"pipeline": "人工复核"})
            self.assertNotIn("arxiv_pdf_url", saved)
            self.assertEqual(saved["fetch_results"]["arxiv_pdf"]["url"], "https://mirror.example/actual")
            report = workspace / saved["report_path"]
            subprocess.run(
                [sys.executable, str(SCRIPTS / "build_report_skeleton.py"), "--input", str(workspace)],
                check=True, capture_output=True, text=True,
            )
            self.assertEqual(resolve_report_path(root, workspace.name, None), report)
            self.assertIn('arxiv_url: "https://arxiv.org/abs/2401.12345v1"', report.read_text(encoding="utf-8"))

    def test_non_arxiv_urls_and_not_applicable_fields_are_preserved(self):
        workspace = Path("/workspace/tau0-vla")
        manual = {
            "arxiv_id": "tau0-vla",
            "version": "official PDF",
            "original_url": "https://example.org/official.pdf",
            "arxiv_pdf_url": "",
            "paths": {"raw_src_tar": None},
            "internal_status": {"hjfy_visit_status": "不适用：无 arXiv ID"},
        }
        self.assertEqual(common.compact_workspace_metadata(workspace, manual), manual)
        self.assertEqual(set(common.workspace_source_urls(manual).values()), {""})

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
            common.write_json(workspace / "metadata.json", metadata(workspace, "v2"))
            third, _ = pipeline_state.fingerprint(workspace, "extract_references", script, PROJECT_ROOT)
            self.assertNotEqual(second, third)


if __name__ == "__main__":
    unittest.main()
