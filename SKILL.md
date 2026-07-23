---
name: paper-reading
description: 对单篇 AI / 机器人 / 机器学习论文执行第一性原理速览和 reviewer-level 精读，包括任务形式化、挑战—洞见—创新链、潜在缺陷、理论与公式解析、实验审查、真实文献对照、代码—论文一致性检查和复现风险评估。适用于 arXiv 链接或 ID、单篇 PDF、论文源码与官方代码仓库；需要生成固定结构、自包含、带图片/表格/证据链的中文 Markdown 阅读报告时使用。不要用于纯摘要改写、多论文综述或脱离原文的自由发挥。
---

# Paper Reading

围绕“论文主张是否被原文、实验和实现真正支撑”组织分析。先运行确定性流水线，再阅读原文、建立证据账本、完成深度审阅，最后提炼展示在报告最前面的第一性原理速览。速览展示前置、写作后置，避免用摘要预判全文。

## 1. 每次必须先执行流水线

在 skill 根目录或包含该 skill 的工作目录运行：

```bash
bash scripts/run_pipeline.sh "<arXiv URL 或 ID>"
```

流水线固定输出到：

```text
output/{arxiv_id}_{title}/
├── {arxiv_id}_阅读报告.md
├── metadata.json
├── raw/
├── images/
├── cache/
└── logs/
```

若同一论文已存在，默认安全退出。显式恢复已有工作区：

```bash
bash scripts/run_pipeline.sh "<论文输入>" --resume "<已有工作区目录名>"
```

只重跑某阶段：

```bash
bash scripts/run_pipeline.sh "<论文输入>" --resume "<目录名>" --force-stage extract_images
```

`--force` 只重跑预处理阶段，不得覆盖成品报告。只有用户明确要求重建正文时才使用 `--overwrite-report`。

## 2. 先检查证据材料是否有效

读取 `metadata.json` 的版本和 `fetch_results`，再使用以下材料：

- 必需：`raw/abs.html`、`raw/paper.pdf`、`cache/paper_text.txt`
- 优先：`raw/source.tar`、`cache/source_unpack/`
- 结构化证据：`cache/references.json`、`cache/images_manifest.json`、`cache/claims.json`
- 可选 enrichment：`raw/ar5iv.html`、`raw/hjfy.html`、`raw/papers_cool.html`、`raw/papers_cool_related.html`

仅使用通过抓取器验证且在 metadata 中标为成功的材料。ar5iv、hjfy 或 papers.cool 失败不阻塞论文分析；明确记录缺口，不读取错误页或 JS shell 来补事实。

若用户输入带 arXiv 版本号，严格使用该版本。若未带版本号，解析最新版本；恢复旧工作区时核对版本是否变化。

## 3. 建立主张—证据账本

在写正文前填充 `cache/claims.json`。每条核心主张必须包含：

- `claim_id`
- `claim`
- `claim_kind`：`author_explicit`、`author_implicit` 或 `reviewer_inference`
- `paper_location`
- `evidence`
- `evidence_strength`：`strong`、`partial`、`indirect` 或 `insufficient`
- `reviewer_conclusion`

严格区分作者原话、由原文稳妥推出的隐含主张和 reviewer 自己的解释。不得把相关性写成因果性，不得把定性案例写成普遍结论。

阅读并遵循 [reviewer_rubric.md](references/reviewer_rubric.md) 和 [uncertainty_policy.md](references/uncertainty_policy.md)。

## 4. 执行 reviewer-level 分析

### 4.1 理论与方法

- 还原问题设定、输入输出、变量、目标函数、约束、训练与推理路径。
- 识别 A 级公式：核心目标、模块定义、更新规则和理论结论。
- 对全部 A 级公式解释符号、自然语言含义、工程映射、依赖假设和删除该项的后果。
- 公式数量由论文类型决定：理论/方法论文通常深入解释 3–8 个；纯实证或 benchmark 论文不要硬凑公式。
- 对最关键且适合数值化的 1–3 个公式给出极简 toy example。

公式和表格的具体格式读取 [inline-table-and-formula-template.md](references/inline-table-and-formula-template.md)。

### 4.2 实验

- 建立实验—主张对应矩阵。
- 转录正文依赖的主结果、关键消融、数据规模、泛化和失败案例表。
- 审查数据集覆盖、任务选择、指标映射、baseline 来源、公平性、多 seed、显著性和失败案例。
- 若 benchmark 官方任务多于论文报告任务，明确列出选择偏差。
- 每张关键表后写 reviewer 结论：它直接、间接还是不足以支撑哪条主张。

### 4.3 代码—论文一致性

若存在官方代码，将仓库 URL、commit/revision 和发现写入 `cache/claims.json` 的 `code_paper_audit`：

- 论文公式与实现函数是否一致
- loss、权重、detach、mask、采样和推理流程是否一致
- 表格配置与公开 config 是否一致
- 发布是否完整，是否缺训练、评估、数据处理或关键依赖

任何不一致都必须区分“实现错误”“论文未说明”和“当前代码版本无法确认”。

### 4.4 真实文献对照

只使用已打开并核对的一手、可验证来源。明确区分 peer-reviewed 论文与 preprint。找不到直接支持或反对证据时如实写明。将外部核查链接统一放入附录 B。

执行外部检索时读取 [literature_search.md](references/literature_search.md)。社区博客仅可作为可选阅读入口，不得作为学术结论证据，也不得成为完成报告的硬条件。

### 4.5 第一性原理速览

完成上述分析后，以第一性原理思考者的角色读取并严格遵循 [first-principles-quicklook.md](references/first-principles-quicklook.md)，从基本原理和常识出发，将深度结论压缩为六问：`Task`、`Challenge`、`Insight`、`Novelty`、`Potential flaw`、`Motivation`。

- 从对象、信息、目标、约束和最小假设出发，不照抄摘要或术语定义。
- 严格区分 Inspiration、Insight 与 Novelty；作者未明说的动机链标为 reviewer 推断。
- 每个 Novelty 使用“【解决的问题】 -> 【对应 Insight】 -> 【具体创新设计】”链式表达。
- 速览内部不使用任何形式的 LaTeX，公式改用纯文本；后续深度章节仍遵循标准公式规范。
- 省略所有客套话，直接进入结构化分析。

## 5. 图片、表格与公式必须就地出现

图片来源优先级固定为：

1. arXiv 源码中的作者原始 figure，并用 PDF 核对内容
2. PDF 嵌入图片
3. PDF figure 区域裁剪
4. 最小必要的 PDF 整页 fallback，交付前尽量裁成 figure

禁止使用网页截图作为最终插图。依据 `graphics_target`、caption、label、section 和正文首次引用语境决定插入位置。

正文讨论依赖的关键表必须出现在对应分析附近；附录 A 只能补充完整宽表，不能替代正文表。图片后紧跟解释，不设“图片区”。

行内数学只用 `$...$`，display 只用 `$$ ... $$`。能单行则单行；多行使用 `aligned` 等标准环境。需要编号的公式在公式块内部使用连续的 `\tag{N}`，正文以“式 (N)”对应引用。不要用反引号包装数学内容。

## 6. 按 canonical schema 分章写作

每次写报告都读取 [report_schema.json](references/report_schema.json)。它是 frontmatter、章节顺序和必需表格的唯一机器可读真源；不要在其他模板中另建平行结构。

报告必须：

- 以 YAML frontmatter 开头并包含 schema 指定字段
- 不含 `one_liner`
- 不添加 H1
- frontmatter 后立即接 `> [!abstract] 一句话概括`
- abstract callout 后立即接 `## 0. 第一性原理论文速览`，再进入原第 1 章
- 保留 schema 中全部章节并按固定顺序出现
- 在 1.3 写主张—证据表，在 3.3 写主结果表，在 4.5 写相关论文表
- 4.5 相关论文表写标题、基础 arXiv ID、作者/年份、来源/类型、关系和概述，不添加任何网络链接；标题保持纯文本
- 在附录 B 写本报告实际使用且带核查链接的外部文献

新工作区已在 `cache/chapters/` 创建章节片段。先写证据账本和深度章节，再回写 `00_quicklook.md`；不要直接一次生成整篇。

若恢复的成品报告没有章节片段，先拆分：

```bash
python3 scripts/split_report.py --paper-input "<论文输入>" --root output
```

完成所有片段后合并：

```bash
python3 scripts/merge_chapters.py \
  --paper-input "<论文输入>" \
  --root output \
  --overwrite-report
```

合并脚本写入 `cache/chapter_manifest.json` 并默认删除片段；manifest 保留顺序和哈希，可证明最终报告来自哪些章节。

完整写作规范读取 [report-writing-guidelines.md](references/report-writing-guidelines.md)。

## 7. 最终验收与默认同步

除非用户明确要求“不同步”“不要同步”或“仅保留本地报告”，完成报告和 `cache/claims.json` 后必须同步到 Obsidian。同步前先执行 dry-run；只有 dry-run 与严格验收均通过后才实际写入。

默认路径：

- 笔记根目录：`/Users/jiangpeng/Peng's second brain/论文/论文笔记`
- 附件目录：`/Users/jiangpeng/Peng's second brain/attachments`
- 在笔记根目录现有子目录中选择与论文研究领域最匹配、最具体的目录；无法可靠归类时使用 `通用`。不要仅为单篇论文新建主题目录。

先预演：

```bash
python3 scripts/finalize_report.py \
  --paper-input "<论文输入>" \
  --root output \
  --sync-obsidian \
  --obsidian-dry-run \
  --notes-dir "<按研究领域选择的笔记目录>" \
  --images-dir "/Users/jiangpeng/Peng's second brain/attachments"
```

预演通过后执行同一命令并移除 `--obsidian-dry-run`。若同一基础 arXiv ID 的规范报告已存在且内容不同，确认其 frontmatter ID 一致后加 `--obsidian-overwrite`；同步器会先备份旧笔记。ID 不一致、目标歧义或无法确认来源时不得覆盖。

验收必须通过：

- UTF-8 与控制字符检查
- YAML/frontmatter 与 abstract 检查
- H1、章节完整性和顺序检查
- 占位符、关键表和外部链接检查
- 图片存在性、可解码性和 manifest provenance 检查
- 数学定界符、多行环境、连续 tag 与正文引用检查
- chapter manifest 与报告哈希检查
- claims ledger 字段与证据类型检查

只有用户明确要求不同步时，才运行不带 `--sync-obsidian` 的验收命令：

```bash
python3 scripts/finalize_report.py --paper-input "<论文输入>" --root output
```

同步器只复制正文实际引用的图片，并拒绝替报告补造 frontmatter。

同步器使用 Obsidian 笔记目录下的隐藏增量索引 `.paper-reading-index.json` 查找相关论文阅读报告。规范报告名固定为 `{arxiv_id}_阅读报告.md`，因此优先按基础 arXiv ID 做常数时间查找；只有缺少 ID 时才回退到规范化标题。唯一命中时把 4.5 的论文标题改写为 `[[{arxiv_id}_阅读报告|论文标题]]`，未命中或命中歧义时不添加链接。首次同步会全量建索引，之后每次同步只增量更新当前报告；vault 在同步器之外发生批量改动后，显式加 `--rebuild-related-index` 重建。

## 8. 失败与不确定性

- 缺少源码时使用 PDF，不要伪造源码证据。
- enrichment 站点失败时继续分析论文原文，并在内部 metadata 记录状态。
- 没有可验证外部文献时明确写“当前未检索到可靠文献”。
- 没有直接消融或统计证据时写“证据链未闭环”。
- 验收失败时修复报告或证据账本后重跑，不得跳过校验交付。
