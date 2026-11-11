from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_report_skeleton import quicklook_fragment
from check_report_quality import check_quicklook, section_text
from report_schema import load_report_schema


REPORT = '''## 0. 第一性原理论文速览

### 0.3 Insight：从 Inspiration 到关键洞见

> [!tip] I1｜保留决策所需的历史信息
>
> **核心洞见**：把历史线索压缩进持续更新的状态。
>
> **触发观察**：当前输入不足以恢复早期线索。
>
> **洞见类型**：信息结构 / 架构。
>
> **依据**：§2；动机链为 reviewer 推断。

### 0.4 Novelty：将 Insight 落成什么创新

> [!example] N1｜增加循环状态模块
>
> **解决问题**：早期线索在后续步骤中不可访问。
>
> **对应洞见**：I1——保留历史信息。
>
> **具体设计**：将循环状态传入下一个决策步骤。
>
> **创新归类**：架构 / 已有组件重组。
>
> **依据**：§3；缺少直接消融，证据链未闭环。

### 0.6 Motivation：如何从第一性原理想到本文

当前输入会丢失线索，那可不可以显式保留历史？

## 1. 论文核心观点与主张的系统梳理
'''


class QuicklookTests(unittest.TestCase):
    def setUp(self):
        self.schema = load_report_schema()

    def check(self, text):
        return check_quicklook(text, self.schema)

    def test_vertical_cards_and_plain_text_requirement(self):
        self.assertEqual(self.check(REPORT), [])
        for value in ('$h_t$', r'\mathbf{h}'):
            with self.subTest(value=value):
                self.assertTrue(any('no LaTeX' in e for e in self.check(REPORT.replace('显式保留历史', value))))
        self.assertTrue(any('question' in e for e in self.check(REPORT.replace('？', '。'))))

    def test_every_card_requires_nonempty_separate_fields(self):
        for rule in self.schema['quicklook']['callouts'].values():
            for label in rule['fields']:
                with self.subTest(label=label):
                    lines = REPORT.splitlines()
                    index = next(i for i, line in enumerate(lines) if line.startswith(f'> **{label}**'))
                    removed = '\n'.join(lines[:index] + lines[index+1:])
                    self.assertTrue(self.check(removed))
                    lines[index] = f'> **{label}**：'
                    self.assertTrue(self.check('\n'.join(lines)))
        inline = REPORT.replace('\n>\n> **洞见类型**', ' **洞见类型**')
        self.assertTrue(self.check(inline))
        self.assertTrue(self.check(REPORT.replace('\n>\n> **洞见类型**', '\n> **洞见类型**')))

    def test_multiple_cards_and_many_to_many_references(self):
        rules = self.schema['quicklook']['callouts']
        insight = section_text(REPORT, rules['insight']['section']).strip()
        novelty = section_text(REPORT, rules['novelty']['section']).strip()
        multiple = REPORT.replace(insight, insight+'\n\n'+insight.replace('I1', 'I2'))
        multiple = multiple.replace(novelty, novelty+'\n\n'+novelty.replace('N1', 'N2').replace('I1——', 'I1、I2——'))
        self.assertEqual(self.check(multiple), [])
        self.assertTrue(self.check(multiple.replace('N2｜', 'N1｜')))
        self.assertTrue(self.check(multiple.replace('> [!tip] I2', '> [!tip] I1')))
        self.assertTrue(self.check(multiple.replace('> [!example] N2｜增加循环状态模块', '> [!example] N2｜增加循环状态模块\n> **解决问题**：重复字段')))
        self.assertTrue(self.check(multiple.replace('> [!example] N2', '> [!note] N2')))
        self.assertTrue(self.check(multiple.replace('> [!example] N2｜增加循环状态模块\n>\n> **解决问题**：早期线索在后续步骤中不可访问。', '> [!example] N2｜不完整条目')))
        self.assertTrue(self.check(multiple.replace('\n\n> [!tip] I2', '\n>\n> [!tip] I2')))

    def test_missing_or_unknown_insight_references_are_rejected(self):
        for ref in ('I9', 'I1、I9', '保留历史'):
            with self.subTest(reference=ref):
                self.assertTrue(any('existing Insight IDs' in e for e in self.check(REPORT.replace('I1——', ref+'——'))))

    def test_old_chain_and_escaped_body_do_not_satisfy_callouts(self):
        novelty = section_text(REPORT, self.schema['quicklook']['novelty_section']).strip()
        chain = '1. 【历史丢失】 -> 【保留状态】 -> 【循环模块】'
        self.assertTrue(self.check(REPORT.replace(novelty, chain)))
        self.assertTrue(self.check(REPORT.replace(novelty, novelty+'\n\n'+chain)))
        self.assertTrue(self.check(REPORT.replace('> **具体设计**', '**具体设计**')))
        for wrapper in ('```markdown\n%s\n```', '<!--\n%s\n-->'):
            self.assertTrue(self.check(REPORT.replace(novelty, wrapper % novelty)))

    def test_no_independent_novelty_requires_explained_callout(self):
        novelty = section_text(REPORT, self.schema['quicklook']['novelty_section']).strip()
        absence = '> [!example] 未识别到可独立成立的 Novelty\n> 根据 §3，当前方法更接近已有组件的工程组合；缺少与相近方案的直接对照，独立创新性尚不能确认。'
        self.assertEqual(self.check(REPORT.replace(novelty, absence)), [])
        self.assertTrue(self.check(REPORT.replace(novelty, absence.splitlines()[0])))
        self.assertTrue(self.check(REPORT.replace(novelty, absence+'\n\n'+novelty.replace('具体设计', '遗漏字段'))))
        self.assertTrue(self.check(REPORT.replace(novelty, absence+'\n> [!example] N2｜不完整条目')))

    def test_scaffold_is_driven_by_callout_schema(self):
        chapter = next(c for c in self.schema['chapters'] if c['file'] == '00_quicklook.md')
        scaffold = quicklook_fragment(chapter, self.schema)
        self.assertIn('> [!tip] I1｜', scaffold)
        self.assertIn('> [!example] N1｜', scaffold)
        self.assertNotIn(' -> ', scaffold)
        filled = scaffold.replace('PAPER_READING_PLACEHOLDER', '基于原文的解释')
        filled = filled.replace('**对应洞见**：基于原文的解释', '**对应洞见**：I1——保留历史')
        self.assertEqual(self.check(filled), [])


if __name__ == '__main__':
    unittest.main()
