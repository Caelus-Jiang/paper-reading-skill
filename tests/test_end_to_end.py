from __future__ import annotations

import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

import fitz
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from common import atomic_write_text, write_json  # noqa: E402
from check_report_quality import run_checks  # noqa: E402
from merge_chapters import merge_workspace  # noqa: E402
from report_schema import load_report_schema  # noqa: E402
from split_report import split_report  # noqa: E402


def make_metadata(workspace: Path) -> dict:
    versioned = "2401.12345v1"
    return {
        "input": "2401.12345",
        "arxiv_id": "2401.12345",
        "title": "Fixture Paper",
        "workspace_name": workspace.name,
        "version": "v1",
        "paper_id_with_version": versioned,
        "arxiv_abs_url": f"https://arxiv.org/abs/{versioned}",
        "arxiv_pdf_url": f"https://arxiv.org/pdf/{versioned}.pdf",
        "hjfy_url": f"https://hjfy.top/arxiv/{versioned}",
        "papers_cool_url": f"https://papers.cool/arxiv/{versioned}",
        "ar5iv_url": f"https://ar5iv.org/html/{versioned}",
        "arxiv_src_url": f"https://arxiv.org/src/{versioned}",
        "workspace": str(workspace),
        "report_path": str(workspace / "2401.12345_阅读报告.md"),
    }


class CanonicalEndToEndTests(unittest.TestCase):
    def run_script(self, name: str, root: Path, workspace: Path) -> None:
        subprocess.run(
            [sys.executable, str(SCRIPTS / name), "--input", workspace.name, "--root", str(root)],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_preprocessing_pipeline_on_local_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "output"
            workspace = root / "2401.12345_Fixture_Paper"
            for name in ("raw", "images", "cache", "logs"):
                (workspace / name).mkdir(parents=True, exist_ok=True)
            write_json(workspace / "metadata.json", make_metadata(workspace))

            pdf = fitz.open()
            page = pdf.new_page(width=300, height=200)
            page.insert_text((30, 40), "Fixture paper page text")
            pdf.save(workspace / "raw" / "paper.pdf")
            pdf.close()

            source_dir = Path(temporary) / "source"
            source_dir.mkdir()
            figure = fitz.open()
            figure.new_page(width=200, height=120)
            figure.save(source_dir / "figure.pdf")
            figure.close()
            (source_dir / "main.tex").write_text(
                r"""\documentclass{article}
\begin{document}
\section{Method}
Figure~\ref{fig:fixture} shows the method.
\begin{figure}
\includegraphics{figure.pdf}
\caption{A nested \textbf{fixture} caption with state $\bs{h}$ preserved.}
\label{fig:fixture}
\end{figure}
\end{document}
""",
                encoding="utf-8",
            )
            (source_dir / "refs.bib").write_text(
                "@article{k, title={A {Nested} Reference}, author={A and B}, year={2024}}",
                encoding="utf-8",
            )
            with tarfile.open(workspace / "raw" / "source.tar", "w:gz") as archive:
                for path in source_dir.iterdir():
                    archive.add(path, arcname=path.name)

            self.run_script("extract_references.py", root, workspace)
            self.run_script("extract_images.py", root, workspace)
            self.run_script("extract_paper_text.py", root, workspace)
            self.run_script("build_report_skeleton.py", root, workspace)

            references = json.loads((workspace / "cache" / "references.json").read_text(encoding="utf-8"))
            manifest = json.loads((workspace / "cache" / "images_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(references["items"][0]["title"], "A Nested Reference")
            self.assertIn("fixture caption", manifest["figures"][0]["caption"])
            self.assertTrue((workspace / "images" / "figure_01.png").exists())
            self.assertIn("Fixture paper page text", (workspace / "cache" / "paper_text.txt").read_text(encoding="utf-8"))
            report = workspace / "2401.12345_阅读报告.md"
            self.assertFalse(report.read_text(encoding="utf-8").startswith("# "))
            self.assertIn("## 0. 第一性原理论文速览", report.read_text(encoding="utf-8"))
            self.assertTrue((workspace / "cache" / "chapters" / "00_quicklook.md").exists())
            self.assertTrue((workspace / "cache" / "chapter_manifest.json").exists())

    def test_legacy_report_split_adds_quicklook_migration_fragment(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "legacy_workspace"
            workspace.mkdir()
            schema = load_report_schema()
            legacy_parts = ["---\ntitle: Legacy\n---\n\n> [!abstract] 一句话概括\n> Legacy report."]
            legacy_parts.extend(
                f"{chapter['heading']}\n\nLegacy chapter text."
                for chapter in schema["chapters"]
                if chapter.get("heading") and chapter["file"] != "00_quicklook.md"
            )
            report = workspace / "legacy_阅读报告.md"
            atomic_write_text(report, "\n\n".join(legacy_parts) + "\n")

            split_report(workspace, report)

            quicklook = workspace / "cache" / "chapters" / "00_quicklook.md"
            self.assertTrue(quicklook.exists())
            self.assertIn("## 0. 第一性原理论文速览", quicklook.read_text(encoding="utf-8"))
            self.assertIn("PAPER_READING_PLACEHOLDER", quicklook.read_text(encoding="utf-8"))

    def test_fully_populated_fixture_passes_strict_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "2401.12345_Fixture_Paper"
            for name in ("images", "cache", "cache/chapters", "logs", "raw"):
                (workspace / name).mkdir(parents=True, exist_ok=True)
            write_json(workspace / "metadata.json", make_metadata(workspace))
            image_path = workspace / "images" / "figure_01.png"
            Image.new("RGB", (320, 180), "white").save(image_path)
            write_json(
                workspace / "cache" / "images_manifest.json",
                {"figures": [{"saved_path": "images/figure_01.png", "source": "arxiv_source"}]},
            )
            write_json(
                workspace / "cache" / "claims.json",
                {
                    "required_fields": ["claim_id", "claim", "claim_kind", "paper_location", "evidence", "evidence_strength", "reviewer_conclusion"],
                    "allowed_claim_kind": ["author_explicit", "author_implicit", "reviewer_inference"],
                    "allowed_evidence_strength": ["strong", "partial", "indirect", "insufficient"],
                    "claims": [{
                        "claim_id": "C1",
                        "claim": "Fixture claim",
                        "claim_kind": "author_explicit",
                        "paper_location": "Section 1",
                        "evidence": "Table 1",
                        "evidence_strength": "partial",
                        "reviewer_conclusion": "Partially supported"
                    }]
                },
            )

            schema = load_report_schema()
            chapter_dir = workspace / "cache" / "chapters"
            frontmatter = """---
title: "Fixture Paper"
authors: ["A. Author"]
institutions: ["Example University"]
venue: "arXiv preprint"
year: 2024
arxiv_id: "2401.12345v1"
arxiv_url: "https://arxiv.org/abs/2401.12345v1"
hjfy_url: "https://hjfy.top/arxiv/2401.12345v1"
papers_cool_url: "https://papers.cool/arxiv/2401.12345v1"
research_area: "machine-learning"
tags: ["paper-reading", "machine-learning"]
aliases: ["Fixture"]
cssclasses: ["paper-reading-report"]
---

> [!abstract] 一句话概括
> A complete fixture report.
"""
            atomic_write_text(chapter_dir / "00_frontmatter.md", frontmatter)
            for chapter in schema["chapters"][1:]:
                blocks = [chapter["heading"], "", "Evidence-backed chapter text."]
                for heading in chapter.get("subheadings") or []:
                    blocks.extend(["", heading, "", "Evidence-backed section text."])
                    if heading.startswith("### 0.4"):
                        blocks.extend(["", "【Missing memory】 -> 【Persistent state is sufficient】 -> 【Add a recurrent state module】"])
                    if heading.startswith("### 0.6"):
                        blocks.extend(["", "Can the method preserve task history explicitly?"])
                    if heading.startswith("### 1.3"):
                        blocks.extend(["", "| 主张 ID | 主张 | 证据 | 证据强度 | Reviewer 结论 |", "|---|---|---|---|---|", "| C1 | Fixture | Table 1 | 部分 | Partially supported |"])
                    if heading.startswith("### 3.3"):
                        blocks.extend(["", "| 数据集 | 方法 | 指标 | 数值 | 审稿人提示 |", "|---|---|---|---|---|", "| Fixture | Method | Score | 1.0 | Partial evidence |"])
                    if heading.startswith("### 4.5"):
                        blocks.extend(["", "| 论文标题 | arXiv ID | 作者 / 年份 | 来源 / 类型 | 与原论文关系 | 一句话概述 |", "|---|---|---|---|---|---|", "| Related | 2401.00001 | Author / 2024 | arXiv preprint | Competing | A verified competing paper |"])
                if chapter["file"] == "02_theory_and_method.md":
                    blocks.extend(["", "![Fixture figure](images/figure_01.png)", "The figure provides direct visual context for the method.", "", "式 (1) defines the fixture objective.", "", "$$ x = 1 \\tag{1} $$"])
                if chapter["file"] == "07_appendices.md":
                    blocks.extend(["", "Verified source: https://arxiv.org/abs/2401.00001"])
                atomic_write_text(chapter_dir / chapter["file"], "\n".join(blocks) + "\n")

            report = workspace / "2401.12345_阅读报告.md"
            merge_workspace(workspace, report, delete_fragments=True, overwrite_report=False)
            errors, _warnings, metrics = run_checks(report, workspace, schema, True)
            self.assertEqual(errors, [])
            self.assertEqual(metrics["images_checked"], 1)
            original = report.read_text(encoding="utf-8")
            split_report(workspace, report)
            merge_workspace(workspace, report, delete_fragments=True, overwrite_report=True)
            self.assertEqual(report.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
