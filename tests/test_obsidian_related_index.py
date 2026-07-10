from __future__ import annotations

import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import paper_index  # noqa: E402
import sync_obsidian  # noqa: E402


def note_text(title: str, arxiv_id: str) -> str:
    return f"""---
title: "{title}"
arxiv_id: "{arxiv_id}"
---

## Body
"""


class ObsidianRelatedIndexTests(unittest.TestCase):
    def test_cached_flat_index_avoids_repeat_scan_and_supports_incremental_upsert(self):
        with tempfile.TemporaryDirectory() as temporary:
            notes = Path(temporary)
            first = notes / "2401.00001_阅读报告.md"
            first.write_text(note_text("First Paper", "2401.00001v2"), encoding="utf-8")
            index = paper_index.load_or_rebuild_flat_index(notes)
            self.assertTrue((notes / paper_index.FLAT_INDEX_FILENAME).exists())
            self.assertEqual(index["scan_stats"]["filename_only"], 1)
            self.assertEqual(index["scan_stats"]["frontmatter_fallback"], 0)
            match, status = paper_index.lookup_flat_note(index, notes, arxiv_id="2401.00001")
            self.assertEqual(status, "matched")
            self.assertEqual(match["wikilink_target"], "2401.00001_阅读报告")

            with mock.patch.object(paper_index, "scan_flat_notes", side_effect=AssertionError("unexpected rescan")):
                cached = paper_index.load_or_rebuild_flat_index(notes)
            self.assertEqual(len(cached["papers"]), 1)

            second = notes / "2401.00002_阅读报告.md"
            second.write_text(note_text("Second Paper", "2401.00002v1"), encoding="utf-8")
            updated = paper_index.upsert_flat_note(notes, second, index_data=cached)
            match, status = paper_index.lookup_flat_note(updated, notes, arxiv_id="2401.00002")
            self.assertEqual(status, "matched")
            self.assertEqual(match["title"], "Second Paper")

    def test_filename_supplies_id_without_reading_full_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            notes = Path(temporary)
            note = notes / "2401.00003_阅读报告.md"
            note.write_text("---\ntitle: Filename Indexed\n---\n", encoding="utf-8")
            index = paper_index.rebuild_index(notes, flat=True)
            match, status = paper_index.lookup_flat_note(index, notes, arxiv_id="2401.00003")
            self.assertEqual(status, "matched")
            self.assertEqual(match["file_name"], note.name)

    def test_title_only_lookup_lazily_hydrates_and_caches_frontmatter(self):
        with tempfile.TemporaryDirectory() as temporary:
            notes = Path(temporary)
            note = notes / "2401.00005_阅读报告.md"
            note.write_text(note_text("Lazy Title", "2401.00005v1"), encoding="utf-8")
            index = paper_index.rebuild_index(notes, flat=True)
            self.assertEqual(index["papers"][0]["title"], "")
            match, status = paper_index.lookup_flat_note(
                index,
                notes,
                title="Lazy Title",
                hydrate_titles_on_miss=True,
            )
            self.assertEqual(status, "matched")
            self.assertEqual(match["title"], "Lazy Title")
            self.assertEqual(index["scan_stats"]["lazy_title_reads"], 1)

    def test_related_table_gets_wikilink_only_for_unique_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            notes = Path(temporary)
            existing = notes / "2401.00001_阅读报告.md"
            existing.write_text(note_text("Existing Paper", "2401.00001v1"), encoding="utf-8")
            index = paper_index.rebuild_index(notes, flat=True)
            markdown = """### 4.5 相关论文补充表

| 论文标题 | arXiv ID | 作者 / 年份 | 来源 / 类型 | 与原论文关系 | 一句话概述 |
|---|---|---|---|---|---|
| Existing Paper | 2401.00001 | A / 2024 | Conference | 前置工作 | Existing note |
| Missing Paper | 2401.00002 | B / 2024 | arXiv preprint | 竞争方法 | No note |

## 5. Next
"""
            rewritten, stats = sync_obsidian.rewrite_related_papers_table(markdown, index, notes)
            self.assertIn("[[2401.00001_阅读报告\\|Existing Paper]]", rewritten)
            self.assertIn("| Missing Paper | 2401.00002 |", rewritten)
            self.assertNotIn("http", rewritten)
            self.assertEqual(stats["matched"], 1)
            self.assertEqual(stats["missing"], 1)

    def test_legacy_network_link_is_removed_during_table_canonicalization(self):
        with tempfile.TemporaryDirectory() as temporary:
            notes = Path(temporary)
            index = paper_index.rebuild_index(notes, flat=True)
            markdown = """### 4.5 相关论文补充表
| 论文标题 | 作者 / 年份 | 来源 | 与原论文关系 | 核查链接 |
|---|---|---|---|---|
| [Legacy](https://arxiv.org/abs/2401.00004) | A / 2024 | arXiv | 相关 | https://arxiv.org/abs/2401.00004 |
## 5. Next
"""
            rewritten, stats = sync_obsidian.rewrite_related_papers_table(markdown, index, notes)
            self.assertNotIn("https://", rewritten)
            self.assertIn("| Legacy | 2401.00004 |", rewritten)
            self.assertEqual(stats["missing"], 1)

    def test_sync_main_writes_wikilinks_index_and_resolution_log(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            workspace = base / "workspace"
            notes = base / "notes"
            images = base / "images"
            workspace.mkdir()
            notes.mkdir()
            existing = notes / "2401.00001_阅读报告.md"
            existing.write_text(note_text("Existing", "2401.00001v1"), encoding="utf-8")
            report = workspace / "2401.99999_阅读报告.md"
            report.write_text(
                """---
title: "Target Paper"
authors: ["A"]
institutions: ["I"]
venue: "arXiv preprint"
year: 2024
arxiv_id: "2401.99999v1"
arxiv_url: "https://arxiv.org/abs/2401.99999v1"
hjfy_url: "https://hjfy.top/arxiv/2401.99999v1"
papers_cool_url: "https://papers.cool/arxiv/2401.99999v1"
research_area: "ml"
tags: ["paper-reading"]
aliases: ["Target"]
cssclasses: ["paper-reading-report"]
---

### 4.5 相关论文补充表
| 论文标题 | arXiv ID | 作者 / 年份 | 来源 / 类型 | 与原论文关系 | 一句话概述 |
|---|---|---|---|---|---|
| Existing | 2401.00001 | A / 2024 | Conference | 前置工作 | Existing note |
""",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "sync_obsidian.py"),
                    "--report-path",
                    str(report),
                    "--notes-dir",
                    str(notes),
                    "--images-dir",
                    str(images),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            synced = notes / report.name
            self.assertIn("[[2401.00001_阅读报告\\|Existing]]", synced.read_text(encoding="utf-8"))
            self.assertTrue((notes / paper_index.FLAT_INDEX_FILENAME).exists())
            log = (workspace / "logs" / "obsidian_sync.json").read_text(encoding="utf-8")
            self.assertIn('"matched": 1', log)


if __name__ == "__main__":
    unittest.main()
