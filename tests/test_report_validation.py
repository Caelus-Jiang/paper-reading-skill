from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import check_report_quality  # noqa: E402
import sync_obsidian  # noqa: E402
from common import reject_ambiguous_reports  # noqa: E402
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

    def test_unsupported_math_macro_is_rejected(self):
        errors, _warnings = check_report_quality.check_math(r"$\mathbbm{1}$")
        self.assertTrue(any("mathbbm" in error for error in errors))

    def test_each_claim_requires_original_location(self):
        text = """### 1.3 核心观点（Claims）的逐条梳理
| 主张 ID | 原文位置 | 证据 |
|---|---|---|
| C1 |  | 定理 1 |
"""
        self.assertTrue(any("C1" in error for error in check_report_quality.check_claim_locations(text)))

    def test_quicklook_requires_plain_text_novelty_chain_and_question(self):
        schema = load_report_schema()
        text = """## 0. 第一性原理论文速览
### 0.4 Novelty：将 Insight 落成什么创新
【长程依赖】 -> 【保留状态足够】 -> 【增加循环状态模块】
### 0.6 Motivation：如何从第一性原理想到本文
之前的方法会丢失状态，那可不可以显式保留历史？
## 1. 论文核心观点与主张的系统梳理
"""
        self.assertEqual(check_report_quality.check_quicklook(text, schema), [])
        errors = check_report_quality.check_quicklook(text.replace("显式保留历史？", "$h_t$？"), schema)
        self.assertTrue(any("no LaTeX" in error for error in errors))
        errors = check_report_quality.check_quicklook(text.replace("显式保留历史？", r"保留 \mathbf{h}？"), schema)
        self.assertTrue(any("no LaTeX" in error for error in errors))

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

    def test_nonexperimental_report_can_explain_missing_tables_and_sources(self):
        schema = load_report_schema()
        text = """### 1.3 核心观点（Claims）的逐条梳理
| 主张 | 证据 |
|---|---|
| C1 | 定理 1 |
### 3.3 实验结果的解释力度
实验结果不适用：本文是纯理论论文，核心结论由定理 1 的证明支撑；缺少实验不影响定理有效性，但不能据此判断实际性能。
### 4.5 相关论文补充表
未检索到可靠文献：核对原文参考文献后未找到直接竞争工作，因此创新性比较仍有不确定性。
## 附录 B：本报告引用的关键外部文献
未使用外部文献：原文参考文献未提供可核实的直接对照，相关性判断仅限已读取的原文。
"""
        self.assertEqual(check_report_quality.check_required_tables(text, schema), [])
        self.assertEqual(check_report_quality.check_external_evidence(text, {"required_url_prefixes": []}), [])

    def test_absence_without_reason_is_rejected(self):
        self.assertFalse(check_report_quality.explains_absence("不适用"))
        self.assertTrue(check_report_quality.check_external_evidence("## 附录 B：本报告引用的关键外部文献\n不适用", {"required_url_prefixes": []}))

    def test_no_image_is_allowed_and_repeated_prose_is_rejected(self):
        errors, _warnings, count = check_report_quality.check_images(Path("report.md"), Path("."), "没有图片。")
        self.assertEqual((errors, count), ([], 0))
        paragraph = "核心机制与证据之间的对应关系需要逐项核对。" * 7
        self.assertTrue(check_report_quality.check_repeated_paragraphs(paragraph + "\n\n" + paragraph))

    def test_ambiguous_workspace_requires_explicit_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for suffix in ("First", "Second"):
                workspace = root / f"2401.12345_{suffix}"
                workspace.mkdir()
                (workspace / "2401.12345_阅读报告.md").write_text("report", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Multiple reports"):
                reject_ambiguous_reports(root, "2401.12345")
            reject_ambiguous_reports(root, "2401.12345_First")


    def test_mathjax_tags_must_be_outside_inner_alignment_environments(self):
        for env in ("aligned", "alignedat", "gathered", "split"):
            with self.subTest(environment=env):
                argument = "{1}" if env == "alignedat" else ""
                body = rf"\begin{{{env}}}" + argument + rf"x=1\tag{{1}}\end{{{env}}}"
                errors, _warnings = check_report_quality.check_math("$$\n" + body + "\n$$")
                self.assertTrue(any("tag not allowed" in error for error in errors))
                corrected = body.replace(r"\tag{1}", "") + r"\tag{1}"
                errors, _warnings = check_report_quality.check_math("$$\n" + corrected + "\n$$")
                self.assertEqual(errors, [])

    def test_mathjax_tag_check_tracks_nested_environments_and_ignores_fences(self):
        invalid = r"\begin{aligned}\begin{cases}x\end{cases}\tag{1}\end{aligned}"
        self.assertEqual(check_report_quality.find_invalid_math_tags(invalid)[0][2], "aligned")
        self.assertEqual(check_report_quality.find_invalid_math_tags(r"\begin{align}x\tag{1}\end{align}"), [])
        errors, _warnings = check_report_quality.check_math("```latex\n$$" + invalid + "$$\n```")
        self.assertEqual(errors, [])



if __name__ == "__main__":
    unittest.main()
