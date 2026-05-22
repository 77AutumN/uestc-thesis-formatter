<div align="center">

# 电子科技大学毕业论文格式排版引擎

**Word 一键转 LaTeX, 自动排出符合学校规范的 PDF**

`uestc-thesis-formatter` · 已实测 21 case · 覆盖 7 个学院

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![UESTC](https://img.shields.io/badge/UESTC-电子科技大学-red.svg)](https://www.uestc.edu.cn)
[![AI-Native](https://img.shields.io/badge/AI--Native-AGENTS.md-blueviolet.svg)](AGENTS.md)

</div>

---

## ✨ 这是什么

每年毕业季, 成电学子都要面临一个隐藏的"终极 Boss": 被教务处反复打回的论文格式修改意见 —— 段前几磅、行距几倍、参考文献标点全/半角、上下标位置, 一项项手抠到吐血。

这个项目把这些重复劳作做成自动化流水线: 你给一份 `.docx`, 它自动生成符合 UESTC 规范的 LaTeX 工程 + PDF。马克思主义学院的脚注式引用、本科的封面表格、研究生的 BibTeX 参考文献, 都内置识别。

## 🚀 快速开始

### 前置条件

- Python 3.10+
- [Pandoc](https://pandoc.org/installing.html) (≥ 3.0)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (用于 XeLaTeX 编译)
- 或本地安装 TeX Live 2023+ (含 XeLaTeX + CTeX 宏集)

### 三步上手

```bash
# 1. 拉代码 + 子模块
git clone https://github.com/77AutumN/uestc-thesis-formatter.git
cd uestc-thesis-formatter
git submodule update --init --recursive

# 2. 装依赖
pip install -r requirements.txt

# 3. 把你的论文丢进去
python scripts/run_v2.py 你的论文.docx --profile uestc-bachelor --output-dir ./output/
```

Profile 选择见下表; 想跑别的学位换成 `uestc` (研究生) 或 `uestc-marxism` (马院) 即可。

## ✅ 已验证学院 / Tested Schools

本管线已基于 21 个真实论文 case 完成实测 (脱敏后的缺陷热度索引见 [`docs/defects/INDEX.md`](docs/defects/INDEX.md)):

| 学位 | 已实测学院 |
|------|----------|
| **本科** (`uestc-bachelor`) | 信息与通信工程 · 电子科学与工程 · 集成电路科学与工程 · 计算机科学与工程 · 数学科学 · 公共管理 |
| **硕士** (`uestc-marxism`) | 马克思主义学院 |
| 其他学院 / 理工硕博 | Profile 路径设计支持, 尚无真实 case, 欢迎试用反馈 |

If your school isn't on the list yet, the pipeline likely still works — open an issue with your `.docx` (after manual PII removal) and we'll triage.

## 📋 支持的 Profile

| Profile | 引用方式 | 参考文献 | 编译链 | 状态 |
|---------|---------|---------|--------|------|
| **uestc** (标准理工硕/博) | `\cite{}` + BibTeX | 编号列表 | xelatex→bibtex→xelatex×2 | ✅ |
| **uestc-bachelor** (本科) | `\cite{}` + BibTeX (上标 [N]) | 编号列表 | xelatex→bibtex→xelatex×2 | ✅ |
| **uestc-marxism** (马克思主义学院) | 脚注制 ①-⑳ (每页重置) | 四分类 (著作/期刊/论文/网页) | xelatex×3 | ✅ 已验证 |
| **stem** (理工通用基础) | `\cite{}` + BibTeX | 编号列表 | xelatex→bibtex→xelatex×2 | 🧪 alpha |

## 💡 它能帮我做什么

- **🪄 一键 Word → PDF**: 给我一份 `.docx`, 我吐一份符合学校格式规范的 PDF, 中间所有 LaTeX 工程都自动生成, 不需要你装 TeX Live。
- **🎓 认得学院**: 内置 4 套 Profile (本科 / 研究生 / 马院硕士 / 理工通用 alpha), 不同学院的引用方式 (脚注 vs BibTeX)、参考文献分类 (4 类 vs 编号列表)、封面布局, 自动选对。
- **🔬 会检查**: 编译前后跑 24+ 项格式自检 (摘要字数、图表编号连续性、参考文献分类、上标引用、版心溢出等), 不让你交瑕疵 PDF。
- **🩺 会救图救公式**: Word 里嵌的 WMF 公式、表格里被吞的子图、丢失的 Heading 样式, 都能从 docx XML 抢回来。
- **🤖 配 AI IDE 用更舒服**: Cursor / Claude Code / GitHub Copilot 直接 `@/thesis` 或 `/thesis` 一键启动。
- **📓 50 个真实坑都已记录**: 21 个真实论文 case 踩出来的 50 张缺陷卡片在 [`docs/defects/INDEX.md`](docs/defects/INDEX.md), 同症状下次就不复发。

## ⚠️ 已知问题

- **LaTeX 模板补丁未并回上游**: `vendor/DissertationUESTC` 是 git submodule 锁到上游, 项目内做的几个小补丁 (caption 字号 / 表格线宽等) 还在另一条 PR 上等并入。直接 clone 跑通没问题, 仅本科 caption 渲染会有细微差别, 不影响内容合规。
- **部分测试需要预编译产物才能跑**: `tests/test_bachelor_*_compliance.py` 需要 `work/workA/` 下有预跑过的论文制品才能验证。clean clone 下会 self-skip, 不影响主流水线测试 (515 项) 在 CI 里完整跑。
- **`stem` profile 还在 alpha**: 框架接好了, 但端到端 fixture 薄弱, 真用可能有粗糙处, 欢迎试 + 反馈。

<details>
<summary><b>🏗️ 架构概览</b> (贡献者展开)</summary>

```
Word .docx
    │
    ▼
┌─────────────────────┐
│  pandoc_ast_extract  │  ← Pandoc AST 深度解析 + 封面元数据提取
└────────┬────────────┘
         │ chapters/*.tex + metadata
         ▼
┌─────────────────────┐
│  hooks/              │  ← 提取后置钩子 (profile-aware)
│   ├── extract_hidden │     结语/成果拆分
│   ├── format_abstract│     摘要格式化
│   └── format_punct.  │     标点规范化
└────────┬────────────┘
         │ cleaned .tex files
         ▼
┌─────────────────────┐
│  template_adapter    │  ← 组装 main.tex (DissertUESTC)
│  refs_to_footnotes   │  ← [马院] 引用 → 脚注转换
│  categorize_refs     │  ← [马院] 四分类参考文献
└────────┬────────────┘
         │ main.tex + bibliography
         ▼
┌─────────────────────┐
│  run_v2.py Step 6    │  ← Docker XeLaTeX 编译 (canonical)
│  postflight_check    │  ← PDF 质量审计
└─────────────────────┘
         │
         ▼
    thesis.pdf ✅
```

</details>

<details>
<summary><b>📁 项目结构</b> (贡献者展开)</summary>

```
uestc-thesis-formatter/
├── AGENTS.md                       # 🤖 AI 入口（Canonical Index）
├── scripts/                        # 核心引擎
│   ├── run_v2.py                   # Pipeline 编排器
│   ├── pandoc_ast_extract.py       # Pandoc AST 解析器
│   ├── template_adapter.py         # main.tex 组装器 (DissertUESTC)
│   ├── profile_loader.py           # Profile 配置加载器
│   ├── refs_to_bib.py              # BibTeX 生成 [标准]
│   ├── refs_to_footnotes.py        # 引用→脚注 [马院]
│   ├── categorize_refs.py          # 四分类参考文献 [马院]
│   ├── normalize_citations.py      # 引用标记规范化
│   ├── compile.ps1                 # Docker 调试助手（非主编译入口）
│   ├── hooks/                      # 提取后置钩子 (profile-aware)
│   │   ├── format_abstract.py      # 摘要格式化
│   │   ├── format_punctuation.py   # 标点规范化
│   │   └── extract_hidden_sections.py  # 隐藏章节提取
│   ├── preflight_check.py          # 输入质量检查
│   └── postflight_check.py         # PDF 输出审计
│
├── templates/                      # Profile 配置（单一事实源）
│   ├── uestc/                      # 标准理工模板
│   │   ├── profile.json
│   │   └── checklist.md
│   ├── uestc-marxism/              # 马克思主义学院模板
│   │   ├── profile.json
│   │   └── checklist.md
│   └── failure-report.md           # 结构化故障报告模板
│
├── SKILL.md                        # 完整 Pipeline 规范 (顶层, AI 入口)
├── vendor/DissertationUESTC/       # 上游 LaTeX 模板 (submodule)
├── docs/
│   ├── redaction-spec.md           # 知识编译脱敏规范
│   └── defects/                    # 50+ 张缺陷卡片 (脱敏) + INDEX + dashboard.json
├── tools/redact.py                 # PII 脱敏工具 (CI gate 调用)
├── .github/workflows/              # PII Gate + pytest CI
├── requirements.txt
└── LICENSE
```

</details>

<details>
<summary><b>🤖 AI IDE 支持</b> (Cursor / Claude Code / Copilot 用户展开)</summary>

本项目原生支持多种 AI 编程助手。在任何支持的 IDE 输入 `/thesis` 或 `@/thesis`, AI 会自动加载完整流水线规范并引导你完成排版。

| AI 工具 | 入口文件 | 作用 |
|---------|---------|------|
| 通用 | `AGENTS.md` | 标准入口索引 (4 条 Bootstrap 规则) |
| Cursor | `.cursorrules` | 转接到 `AGENTS.md` |
| Claude Code | `CLAUDE.md` | 转接到 `AGENTS.md` |
| GitHub Copilot | `.github/copilot-instructions.md` | 转接到 `AGENTS.md` |

</details>

## 🔒 隐私与公开发布

这是项目的"公开知识精炼版"仓库, 实际开发的私有 skill 树不公开, 公开仓库只放脱敏后的脚本、文档、规范。

- 所有 PII (姓名 / 13 位学号 / 真实案例号 / Windows 绝对路径) 在 commit 前都会被 [`tools/redact.py`](tools/redact.py) 自动替换成 `CASE-A` 等脱敏符号
- 每次 PR 都跑 [`.github/workflows/redact-check.yml`](.github/workflows/redact-check.yml) 自动审计 + git grep 双保险, 任何 PII 残留直接拦截 merge
- 详细规则见 [`docs/redaction-spec.md`](docs/redaction-spec.md)

## 🙏 致谢

本项目基于 [DissertationUESTC](https://github.com/MGG1996/DissertationUESTC) LaTeX 模板构建，原始项目源自 [x-magus/ThesisUESTC](https://github.com/x-magus/ThesisUESTC)，遵循 [LPPL (LaTeX Project Public License)](https://www.latex-project.org/lppl/) 协议。

本项目的贡献在于 **自动化的 Word → LaTeX 转换引擎** 和 **多学院 Profile 系统**，而非 LaTeX 模板本身。

## 📄 License

- **Python 代码** (`scripts/`, `run_v2.py` 等)：[MIT License](LICENSE)
- **LaTeX 模板** (`vendor/DissertationUESTC/`)：[LPPL](https://www.latex-project.org/lppl/)

---

<div align="center">
Made with ❤️ for UESTC graduate students
</div>
