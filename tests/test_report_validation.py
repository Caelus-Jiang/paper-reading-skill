from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import check_report_quality  # noqa: E402
import sync_obsidian  # noqa: E402
from report_schema import load_report_schema  # noqa: E402


class ReportValidationTests(unittest.TestCase):
    def test_missing_frontmatter_and_h1_are_rejected(self):
        schema = load_report_schema()
        _frontmatter, errors = check_report_quality.check_frontmatter("# Report\n", schema)
        self.assertTrue(errors)
        heading_errors = check_report_quality.check_heading_schema("# Report\n", schema)
        self.assertTrue(any("H1" in error for error in heading_errors))

    def test_math_lint_detects_unbalanced_and_nonsequential_tags(self):
        errors, _warnings = check_report_quality.check_math("$$ x \\tag{2} $$\n$y")
        self.assertTrue(any("sequential" in error for error in errors))
        self.assertTrue(any("inline-math" in error for error in errors))

    def test_code_identifiers_with_underscores_are_not_math_false_positives(self):
        errors, _warnings = check_report_quality.check_math("Use `q_0.detach()` and `no_grad`.")
        self.assertEqual(errors, [])

    def test_obsidian_sync_refuses_to_inject_frontmatter(self):
        with self.assertRaises(ValueError):
            sync_obsidian.validate_frontmatter("## 1. report\n")

    def test_related_paper_network_links_are_rejected(self):
        schema = load_report_schema()
        text = """### 1.3 核心观点（Claims）的逐条梳理
| 主张 | 证据 |
|---|---|
| C1 | E1 |
### 3.3 实验结果的解释力度
| 方法 | 指标 |
|---|---|
| M | 1 |
### 4.5 相关论文补充表
| 论文标题 | arXiv ID |
|---|---|
| [Paper](https://arxiv.org/abs/2401.00001) | 2401.00001 |
"""
        errors = check_report_quality.check_required_tables(text, schema)
        self.assertTrue(any("network links" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
