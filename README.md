<div align="center">

# UESTC Thesis Formatter

**电子科技大学学位论文 Word → LaTeX 自动排版引擎**

*Automated Word-to-LaTeX formatting pipeline for UESTC graduate theses*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![UESTC](https://img.shields.io/badge/UESTC-电子科技大学-red.svg)](https://www.uestc.edu.cn)
[![AI-Native](https://img.shields.io/badge/AI--Native-AGENTS.md-blueviolet.svg)](#-ai-native-support)

</div>

---

## ✨ Features / 功能

- **一键 Word → LaTeX**：从 `.docx` 自动提取论文结构（章节、摘要、致谢、参考文献），生成符合 UESTC 规范的 `.tex` 文件
- **多学院 Profile 支持**：通过 `--profile` 参数切换学院配置（标准理工/马克思主义学院），自动应用对应的引用、文献、标点规则
- **Pandoc AST 引擎**：基于 Pandoc JSON AST 的深度解析，精确处理图表、公式、交叉引用
- **自动 QA 校验**：Pre-flight（输入检查）+ Post-flight（PDF 质量审计），含 12 项合规检查点
- **Docker 编译**：内置 XeLaTeX 编译脚本，支持 Docker 一键构建
- **AI-Native**：内置 `AGENTS.md` + `SKILL.md` 契约，支持 Cursor / Claude / Copilot / Antigravity 等 AI IDE 直接操作

## 🏗️ Architecture / 架构

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

## 🚀 Quick Start / 快速开始

### Prerequisites / 前置条件

- Python 3.10+
- [Pandoc](https://pandoc.org/installing.html) (≥ 3.0)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (用于 XeLaTeX 编译)
- 或本地安装 TeX Live 2023+ (含 XeLaTeX + CTeX 宏集)

### Installation / 安装

```bash
# 1. Clone
git clone https://github.com/77AutumN/uestc-thesis-formatter.git
cd uestc-thesis-formatter

# 2. Install dependencies
pip install -r requirements.txt

# 3. 初始化底层 LaTeX 模板子模块
git submodule update --init --recursive
```

### Usage / 使用

```bash
# 标准理工模式
python scripts/run_v2.py thesis.docx --profile uestc --output-dir ./output/

# 马克思主义学院模式
python scripts/run_v2.py thesis.docx --profile uestc-marxism --output-dir ./output/

# 仅提取（不编译）
python scripts/pandoc_ast_extract.py --input thesis.docx --output-dir ./output/extracted/
```

## 📁 Project Structure / 项目结构

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
├── .agent/                         # AI 知识层
│   ├── skills/thesis-formatter/
│   │   └── SKILL.md                # 完整 Pipeline 规范
│   └── workflows/
│       └── thesis.md               # 处理 SOP 工作流
│
├── vendor/DissertationUESTC/       # 上游 LaTeX 模板 (submodule)
├── docs/redaction-spec.md          # 知识编译脱敏规范
├── requirements.txt
└── LICENSE
```

## 📋 Supported Profiles / 支持的学院模式

| Profile | 引用方式 | 参考文献 | 编译链 | 状态 |
|---------|---------|---------|--------|------|
| **uestc** (标准理工) | `\cite{}` + BibTeX | 编号列表 | xelatex→bibtex→xelatex×2 | ✅ |
| **uestc-marxism** (马克思主义学院) | 脚注制 ①-⑳ (每页重置) | 四分类 (著作/期刊/论文/网页) | xelatex×3 | ✅ 已验证 |

## 🤖 AI-Native Support

本项目原生支持多种 AI IDE / 编程助手：

| AI Tool | 入口文件 | 作用 |
|---------|---------|------|
| **通用** | `AGENTS.md` | Canonical Index（4 条 Bootstrap 规则） |
| **Cursor** | `.cursorrules` | Thin Proxy → AGENTS.md |
| **Claude Code** | `CLAUDE.md` | Thin Proxy → AGENTS.md |
| **GitHub Copilot** | `.github/copilot-instructions.md` | Thin Proxy → AGENTS.md |

AI 一键启动：在任何支持的 IDE 中输入 `/thesis` 或 `@/thesis`，AI 将自动加载完整 Pipeline 规范并引导你完成论文排版。

## 🙏 Credits / 致谢

本项目基于 [DissertationUESTC](https://github.com/MGG1996/DissertationUESTC) LaTeX 模板构建，原始项目源自 [x-magus/ThesisUESTC](https://github.com/x-magus/ThesisUESTC)，遵循 [LPPL (LaTeX Project Public License)](https://www.latex-project.org/lppl/) 协议。

本项目的贡献在于 **自动化的 Word → LaTeX 转换引擎** 和 **多学院 Profile 系统**，而非 LaTeX 模板本身。

## 📄 License

- **Python 代码** (`scripts/`, `run_v2.py` 等)：[MIT License](LICENSE)
- **LaTeX 模板** (`vendor/DissertationUESTC/`)：[LPPL](https://www.latex-project.org/lppl/)

---

<div align="center">
Made with ❤️ for UESTC graduate students
</div>
