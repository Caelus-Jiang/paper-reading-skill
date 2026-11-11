---
name: paper-reading
description: 对单篇 arXiv AI / 机器人 / 机器学习论文执行第一性原理速览和 reviewer-level 精读，按论文类型核对核心主张、理论、实验、协议、数据、代码及外部文献证据，生成可追溯的中文 Markdown 报告。适用于 arXiv 链接或 ID 及对应 PDF；不要用于纯摘要改写、无原文依据的自由发挥或多论文综述。
---

# Paper Reading

围绕“论文主张是否被原文、实验和实现真正支撑”组织分析。先运行确定性流水线，再阅读原文、建立证据账本、完成深度审阅，最后提炼展示在报告最前面的第一性原理速览。速览展示前置、写作后置，避免用摘要预判全文。

先判定论文主类型和必要的次类型，再选择证据路径：理论论文核对假设、定理、证明依赖与反例；方法论文核对机制、实验、消融和实现；系统/数据集论文核对接口、协议、覆盖、泄漏及系统测试；实证论文核对对照、统计与外推；单篇综述或观点论文核对选材、综合方法和竞争解释。固定章节用于固定阅读问题，不要求每篇论文都有实验表、公式、图片或代码。缺少某类证据时写明“原文未提供/不适用”及其对判断的影响。

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
采用用户提供的 PDF 时，先确认稿件版本和可读性，再将该文件登记为报告的主来源。

## 3. 建立主张—证据账本

写正文前按[原文证据规范](references/report-writing-guidelines.md#原文证据)填充 `cache/claims.json`。核对账本中的 `paper_source` 是报告实际采用的 PDF。每条核心主张记录 `claim_id`、`claim`、`claim_kind`、`citations`、`evidence`、`evidence_strength` 和 `reviewer_conclusion`。在 1.3 登记首条定位，在深读章节的论证旁展示证据和必要的英文短引。

严格区分作者原话、由原文稳妥推出的隐含主张和 reviewer 自己的解释。不得把相关性写成因果性，不得把定性案例写成普遍结论。

阅读并遵循 [reviewer_rubric.md](references/reviewer_rubric.md) 和 [uncertainty_policy.md](references/uncertainty_policy.md)。

### 3.1 梳理研究逻辑链

按 [研究逻辑链规范](references/research-logic-chain.md)，在 §1.1 背景与动机之后、详细公式之前写出论文的论证主线。位置与标题由 canonical schema 的 `research_logic` 定义。将关键问题、观察或假设、设计选择、验证证据与边界连接起来；按论文类型保留必要的分支和缺口，不推测实际研究时间线。§0.6 只保留简短动机，方法与证据章节用过渡句接回主线。自动验收仅检查该小节的位置及非空正文，论证关系由撰写者核对。

## 4. 执行 reviewer-level 分析

### 4.1 理论与方法

- 还原问题设定、输入输出、变量、目标函数、约束、训练与推理路径。
- 识别 A 级公式：核心目标、模块定义、更新规则和理论结论。
- 对全部 A 级公式解释符号、自然语言含义、工程映射、依赖假设和删除该项的后果。
- 公式数量由论文类型和核心机制决定；原文无决定性公式时不要硬凑。适合数值化的关键公式可用极简 toy example 解释。

公式和表格的具体格式读取 [inline-table-and-formula-template.md](references/inline-table-and-formula-template.md)。

### 4.2 与论文类型匹配的决定性证据

- 有实验时建立实验—主张对应矩阵；无实验时建立定理/协议/数据/系统测试与主张的对应关系。
- 对实验论文转录正文依赖的主结果、关键消融、数据规模、泛化和失败案例表；理论论文改为定位中心定理、关键证明步骤与反例；系统/数据论文核对协议、覆盖、泄漏与系统测试。
- 实验存在时审查数据集覆盖、任务选择、指标映射、baseline 来源、公平性、多 seed、显著性和失败案例。
- 若 benchmark 官方任务多于论文报告任务，明确列出选择偏差。
- 每项关键证据后写 reviewer 结论：它直接、间接还是不足以支撑哪条主张。证据可为表格、证明、反例、协议或代码定位；不按固定数量凑内容。

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

速览先让读者看懂研究对象、核心思路、决定性证据与最终边界，再深入审查。六问只压缩已核实的深度结论；正文先解释机制或论证链，再评价 Claim，完整证据与复现细节留在后文及附录，不能因精简而删掉。

- 从对象、信息、目标、约束和最小假设出发，不照抄摘要或术语定义。
- 严格区分 Inspiration、Insight 与 Novelty；作者未明说的动机链标为 reviewer 推断。
- Insight 与 Novelty 逐条使用纵向 callout：`[!tip] I1｜洞见短标题`、`[!example] N1｜具体设计短标题`。字段与示例遵循速览规范和 canonical schema；Novelty 通过 I 编号关联洞见，不再使用长括号箭头链。
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

行内数学只用 `$...$`，display 只用 `$$ ... $$`。能单行则单行；多行使用 `aligned` 等标准环境。需要编号的公式在公式块内部使用连续的 `\tag{N}`，但必须位于 `\end{aligned}` 等内部对齐环境之后、外层 `$$` 之前；不要放进 `aligned`、`alignedat`、`gathered`、`split` 内。正文以“式 (N)”对应引用。不要用反引号包装数学内容。

## 6. 按 canonical schema 分章写作

每次写报告都读取 [report_schema.json](references/report_schema.json)。它是 frontmatter、章节顺序和必需表格的唯一机器可读真源；不要在其他模板中另建平行结构。

报告必须：

- 以 YAML frontmatter 开头并包含 schema 指定字段
- 不含 `one_liner`
- 不添加 H1
- frontmatter 后立即接 `> [!abstract] 一句话概括`
- abstract callout 后立即接 `## 0. 第一性原理论文速览`，再进入原第 1 章
- 保留 schema 中全部章节并按固定顺序出现
- 在 1.3 写主张—证据表；有实验主结果时在 3.3 写主结果表；有相关论文时在 4.5 写相关论文表
- 没有适用的实验结果或外部文献时，删除对应占位表行，明确写出不适用或未找到的原因及其判断影响；不得编造表格、图片或公式来满足模板
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

- 笔记根目录：`/Users/pengjiang/Library/Mobile Documents/iCloud~md~obsidian/Documents/Peng's second brain/论文/论文笔记`
- 附件目录：`/Users/pengjiang/Library/Mobile Documents/iCloud~md~obsidian/Documents/Peng's second brain/attachments`
- 在笔记根目录现有子目录中选择与论文研究领域最匹配、最具体的目录；无法可靠归类时使用 `通用`。不要仅为单篇论文新建主题目录。

先预演：

```bash
python3 scripts/finalize_report.py \
  --paper-input "<论文输入>" \
  --root output \
  --sync-obsidian \
  --obsidian-dry-run \
  --notes-dir "<按研究领域选择的笔记目录>" \
  --images-dir "/Users/pengjiang/Library/Mobile Documents/iCloud~md~obsidian/Documents/Peng's second brain/attachments"
```

预演通过后执行同一命令并移除 `--obsidian-dry-run`。若同一基础 arXiv ID 的规范报告已存在且内容不同，确认其 frontmatter ID 一致后加 `--obsidian-overwrite`；同步器会先备份旧笔记。ID 不一致、目标歧义或无法确认来源时不得覆盖。

验收必须通过：

- UTF-8 与控制字符检查
- YAML/frontmatter 与 abstract 检查
- H1、章节完整性和顺序检查
- 占位符、关键表和外部链接检查
- 图片存在性、可解码性和 manifest provenance 检查
- 数学定界符、多行环境、连续 tag 与正文引用检查，并拒绝内部对齐环境中的 tag
- chapter manifest 与报告哈希检查
- claims ledger 字段与证据类型检查，新账本另核对核心主张覆盖、正文与账本引用一致性，以及摘录所在的 PDF 页

静态检查不能替代实际渲染。含公式且真实 Obsidian 可用时，同步后按 [mathjax-validation.md](references/mathjax-validation.md) 对全部块级与行内公式逐式调用 MathJax，记录检查数量和错误，再在页面核对多行公式及编号。引擎不可用时明确记录未验证，不得声称“显示正常”。

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
