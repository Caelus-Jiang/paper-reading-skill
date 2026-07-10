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


if __name__ == "__main__":
    unittest.main()
