# Obsidian / MathJax 公式渲染验证

## 已确认的编号位置错误

MathJax 会对 `aligned`、`alignedat`、`gathered`、`split` 内的 `\tag` 报错，例如 `\tag not allowed in aligned environment`。连续编号、合法的数学定界符和静态验收通过，都不能排除这种运行时错误。不要将此限制泛化到支持编号的 `align`、`gather` 等环境。

多行公式统一使用下列结构：编号在所有内部对齐环境结束之后，仍在外层 `$$` 内。移动编号即可，保留公式项、原编号与正文引用，不要删掉编号来掩盖错误。

```markdown
$$
\begin{aligned}
J &= J_{\mathrm{task}} \\
&\quad + \lambda J_{\mathrm{aux}}
\end{aligned}
\tag{1}
$$
```

静态检查需覆盖已有错误编号和新生成编号；还要检查嵌套环境中的编号。修复后重新运行本技能的格式/报告验收，报告若使用章节manifest，应通过分章修改与合并刷新哈希。

## 在真实 Obsidian 引擎中逐式检查

有可用的 Obsidian CLI 与运行中的目标vault时，对最终笔记执行实际渲染验证；只有静态校验不得称作“已验证显示正常”。先确认 `obsidian vault` 和目标文件路径；路径已被用户改名时使用现有路径，不另建规范文件名副本。无需安装新渲染库。

以下是只读检查；将 `folder/note.md` 改为目标文件在vault中的真实路径。外层单引号保护反斜杠、美元符号与代码反引号，避免shell展开。若从Python调用CLI，应使用 `subprocess.run(["obsidian", "eval", "code=" + code], ...)`，不要把代码插入双引号shell命令。

```bash
obsidian eval code='(async () => {
  const path = "folder/note.md";
  const file = app.vault.getAbstractFileByPath(path);
  if (!file) throw new Error("Target note not found");
  if (typeof MathJax === "undefined" || !MathJax.tex2chtmlPromise)
    throw new Error("Obsidian MathJax is not ready");
  const text = (await app.vault.read(file))
    .replace(/^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/, "")
    .replace(/```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`/g, "");
  const formulas = [...text.matchAll(/\$\$([\s\S]*?)\$\$|(?<!\\)\$([^$\n]+?)(?<!\\)\$/g)];
  let display = 0, inline = 0;
  const failures = [];
  for (const [index, match] of formulas.entries()) {
    const isDisplay = match[1] !== undefined;
    isDisplay ? display++ : inline++;
    try {
      const el = await MathJax.tex2chtmlPromise(match[1] ?? match[2], {display: isDisplay});
      const errors = [...el.querySelectorAll("mjx-merror, merror, [data-mjx-error]")]
        .map(e => e.getAttribute("data-mjx-error") || e.textContent);
      if (errors.length) failures.push({index: index + 1, display: isDisplay, errors});
    } catch (error) {
      failures.push({index: index + 1, display: isDisplay, errors: [String(error)]});
    }
  }
  return JSON.stringify({path, version: MathJax.version,
    checked: formulas.length, display, inline, failures,
    ok: formulas.length > 0 && failures.length === 0});
})()'
```

检查输出JSON中的 `ok`、数量和失败详情，不能只看CLI退出码：CLI可能以退出码0输出 `Error:`。先通过静态定界符检查，再核对提取出的块级和行内公式数量与实际笔记一致；非标准定界符、跨行行内公式、复杂嵌套代码片段需另行核对提取范围。笔记确实没有公式时记“不适用”，不能把意外提取到0个公式当验证通过。

该检查为每一个公式传入正确的 `display` 模式，捕获异常与错误节点；不修改笔记、不插入测试节点、不重置全局MathJax编号状态。对于2503.23478v1的这次修复，修复前7个块级公式触发该错误，修复后8个块级、59个行内公式全部通过；这些数量是回归样本，不是未来笔记的固定配额。

## 页面验证与结果边界

逐式引擎通过后，在Obsidian阅读视图或实时预览中核对至少一个修复过的多行公式及其编号，并查看页面中 `mjx-merror` / `[data-mjx-error]`。DOM通常只包含当前渲染区，页面中没有错误节点不能替代全文逐式检查。截图用于确认排版、换行或裁切，不作为全文语法正确性的唯一证据。

没有CLI、vault未打开或MathJax不可用时，不自动安装依赖、不更改用户设置、不声称运行时验收通过；完成静态修复，并准确记录“实际Obsidian渲染未验证”及缺少的条件。修改实际笔记前保留可恢复副本；只修复数学语法，保留用户的文件名、frontmatter和其他编辑。
