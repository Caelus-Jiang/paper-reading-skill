from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_report_skeleton import chapter_fragment
from check_report_quality import check_research_logic, run_checks, section_text
from report_schema import load_report_schema


class ResearchLogicTests(unittest.TestCase):
    def setUp(self):
        self.schema = load_report_schema()
        self.rule = self.schema["research_logic"]

    def report(self, body):
        return f"{self.rule['parent_section']}\n\n背景。\n\n{self.rule['heading']}\n\n{body}\n\n### 1.2 问题设定\n\n任务。\n"

    def test_accepts_method_and_theory_without_forcing_figures(self):
        for body in (
            "§2 的停滞观察启发门控设计，§3 的预测对照检验监督模型；算法效果由 §4 另行验证。",
            "在假设 A 下，引理 1 支持定理 2；§4 的反例说明去掉该假设后结论不再成立。",
        ):
            with self.subTest(body=body):
                self.assertEqual(check_research_logic(self.report(body), self.schema), [])

    def test_rejects_missing_misplaced_or_hidden_sections(self):
        report = self.report("§2 的观察启发方案，§3 检验其效果。")
        parent, logic = self.rule['parent_section'], self.rule['heading']
        for bad in (
            report.replace(logic, "#### 其他内容"),
            report.replace(parent, "### 1.2 问题设定"),
            report.replace(logic, f"```markdown\n{logic}\n```"),
            report.replace(logic, f"<!-- {logic} -->"),
            report.replace(logic, logic + "\n\n" + logic),
        ):
            with self.subTest(report=bad):
                self.assertTrue(check_research_logic(bad, self.schema))

    def test_rejects_empty_or_visual_only_explanations(self):
        for body in ("", "<!-- explanation -->", "PAPER_READING_PLACEHOLDER", "```mermaid\nflowchart LR\nA-->B\n```", "| 阶段 | 问题 |\n|---|---|\n| 观察 | 现象 |"):
            with self.subTest(body=body):
                self.assertTrue(check_research_logic(self.report(body), self.schema))

    def test_scaffold_and_checker_follow_custom_schema(self):
        schema = copy.deepcopy(self.schema)
        schema['research_logic']['heading'] = '#### 论证路线'
        chapter = next(c for c in schema['chapters'] if c['file'] == '01_core_claims.md')
        text = chapter_fragment(chapter, schema)
        self.assertIn('#### 论证路线', section_text(text, self.rule['parent_section']))
        self.assertTrue(check_research_logic(text, schema))
        filled = text.replace('<!-- PAPER_READING_PLACEHOLDER: replace with evidence-backed content -->', '§2 的证据启发设计，§3 的独立对照检验其机制及效果。')
        self.assertEqual(check_research_logic(filled, schema), [])

    def test_strict_acceptance_runs_the_logic_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / 'report.md'
            valid = self.report('§2 的观察启发设计，§3 的对照检验方法效果。')
            report.write_text(valid.replace(self.rule['heading'], '#### 其他说明'))
            errors, _, _ = run_checks(report, report.parent, self.schema, False)
            self.assertTrue(any('research logic' in error for error in errors))
            report.write_text(valid)
            errors, _, _ = run_checks(report, report.parent, self.schema, False)
            self.assertFalse(any('research logic' in error for error in errors))


if __name__ == '__main__':
    unittest.main()
