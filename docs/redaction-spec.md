# 知识编译脱敏规范 (Redaction Specification)

> 本规范定义了从私有知识库编译开源版 AI 指令时的脱敏规则。
> All paths in this document are relative to the repository root.

## 1. PII 替换规则

| 原始字段 | 替换为 | 理由 |
|---------|--------|------|
| 真实学生姓名 | `CASE-A` / `CASE-B` | 匿名化但保留经验回溯能力 |
| 真实文件名 (如"xxx论文.docx") | `thesis.docx` | 脱敏 |
| 本地绝对路径 | `./` (相对 Repo Root) | 跨平台移植性 |
| 用户名 / 帐号 / 学号 | 删除或替换为占位符 | PII |

## 2. 经验保留规则（不准过度删除）

以下内容**必须匿名保留**，因为它们是 AI 的"肌肉记忆"：

- `CASE-A`: `\footnote{}` 不可直接放在 `\caption{}` 内部（会编译崩溃），必须用保护模式
- `CASE-A`: 宽表格（≥10列）在默认 `\tabcolsep=6pt` 下会右侧溢出
- `CASE-A`: `[H]` float 强制定位是 UESTC 规范要求，不是可选项
- 章节死循环的排查经验（Word 未使用 Heading 样式导致正则兜底也失败）
- PDF 阅读器锁定文件导致编译产物无法更新

## 3. 路径转换规则

| 私有路径模式 | 开源路径 |
|-------------|---------|
| Private skill directory `scripts/` | `./scripts/` |
| Private skill directory `templates/` | `./templates/` |
| Private skill directory `vendor/` | `./vendor/` |
| Private thesis registry | 删除（私有数据） |
| User-specific desktop paths | 删除（本机路径） |

## 4. 案例注册表

私有案例注册表 (`thesis_registry.md`) 不公开。但其中提炼出的**通用经验教训**
应以 "CASE-X" 形式编入 `SKILL.md` 的 Anti-patterns 章节。
