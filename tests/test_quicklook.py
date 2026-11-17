from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_report_skeleton import quicklook_fragment
from check_report_quality import check_math, check_quicklook, run_checks
from report_schema import load_report_schema


METHOD = r"""策略先无梯度生成动作，取晚期中间状态。参考模型预测端点，critic 用动作梯度提出改进，并接受估计价值提高的候选。

1. 将接受的端点位移除以剩余时间 $1-\tau$，得到速度修正。
2. 固定状态和目标，让当前动作专家拟合局部速度。推理只运行更新后的动作专家。

例如端点从 0.30 改到 0.34，剩余时间为 0.2，速度修正为 0.2。"""


class QuicklookTests(unittest.TestCase):
    def setUp(self):
        self.schema = load_report_schema()
        self.heading = self.schema["quicklook"]["section"]

    def report(self, body):
        return f"{self.heading}\n\n{body}\n\n## 1. 论文核心观点与主张的系统梳理\n"

    def test_accepts_connected_method_with_steps_and_math(self):
        self.assertEqual(check_quicklook(self.report(METHOD), self.schema), [])
        formula = r"$$ T=v_{\mathrm{ref}}+\Delta A/(1-\tau) \tag{1} $$"
        text = self.report(METHOD + "\n\n" + formula)
        self.assertEqual(check_quicklook(text, self.schema), [])
        self.assertEqual(check_math(text)[0], [])
        self.assertTrue(check_math(text.replace(r"\tag{1}", r"\tag{2}"))[0])

    def test_existing_six_question_reports_remain_accepted(self):
        body = """### 0.1 Task：问题形式化
改善机器人动作。

### 0.3 Insight：从 Inspiration 到关键洞见
> [!tip] I1｜构造局部速度标签
>
> **观察**：critic 评价干净动作。
>
> **洞见**：用参考端点将动作改进换成速度修正。

### 0.4 Novelty：将 Insight 落成什么创新
> [!example] N1｜局部拟合
> 在固定状态上更新动作专家。

### 0.6 Motivation：如何从第一性原理想到本文
用端点指导避开完整链反传。"""
        self.assertEqual(check_quicklook(self.report(body), self.schema), [])

    def test_rejects_empty_hidden_or_artifact_only_overviews(self):
        for body in (
            "", "<!-- 方法说明 -->", "PAPER_READING_PLACEHOLDER",
            "```markdown\n" + METHOD + "\n```",
            "```mermaid\nflowchart LR\nA-->B\n```",
            "| 输入 | 输出 |\n|---|---|\n| 噪声 | 动作 |",
            "![方法图](images/figure.png)",
            r"$$ x=y $$", r"$x=y$", "### 只有标题",
            "> [!tip] 只有 callout 标题",
        ):
            with self.subTest(body=body):
                self.assertTrue(check_quicklook(self.report(body), self.schema))

    def test_requires_visible_section_and_stops_at_next_chapter(self):
        for text in (
            "## 1. 论文核心观点与主张的系统梳理\n" + METHOD,
            "<!--\n" + self.report(METHOD) + "\n-->",
            self.report("") + METHOD,
        ):
            with self.subTest(text=text):
                self.assertTrue(check_quicklook(text, self.schema))

    def test_scaffold_and_checker_use_the_same_schema_section(self):
        schema = copy.deepcopy(self.schema)
        chapter = next(c for c in schema["chapters"] if c["file"] == "00_quicklook.md")
        chapter["heading"] = schema["quicklook"]["section"] = "## 0. 方法概览"
        scaffold = quicklook_fragment(chapter, schema)
        self.assertTrue(check_quicklook(scaffold, schema))
        filled = scaffold.replace("PAPER_READING_PLACEHOLDER", METHOD)
        self.assertEqual(check_quicklook(filled, schema), [])
        self.assertTrue(filled.startswith(chapter["heading"]))

    def test_strict_acceptance_requires_explanatory_prose(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "report.md"
            report.write_text(self.report(""), encoding="utf-8")
            errors, _, _ = run_checks(report, report.parent, self.schema, False)
            self.assertTrue(any("method overview" in error for error in errors))
            report.write_text(self.report(METHOD), encoding="utf-8")
            errors, _, _ = run_checks(report, report.parent, self.schema, False)
            self.assertFalse(any("method overview" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
