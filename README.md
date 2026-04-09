<div align="center">

# UESTC Thesis Formatter

**电子科技大学学位论文 Word → LaTeX 自动排版引擎**

*Automated Word-to-LaTeX formatting pipeline for UESTC graduate theses*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![UESTC](https://img.shields.io/badge/UESTC-电子科技大学-red.svg)](https://www.uestc.edu.cn)

</div>

---

## ✨ Features / 功能

- **一键 Word → LaTeX**：从 `.docx` 自动提取论文结构（章节、摘要、致谢、参考文献），生成符合 UESTC 规范的 `.tex` 文件
- **马克思主义学院专用模式**：支持脚注引用制（每页底部 ①-⑳ 编号）+ 四分类参考文献（著作/期刊/学位论文/网页报纸）
- **Pandoc AST 引擎**：基于 Pandoc JSON AST 的深度解析，精确处理图表、公式、交叉引用
- **自动 QA 校验**：Pre-flight（输入检查）+ Post-flight（PDF 质量审计），含 23 项合规检查点
- **Docker 编译**：内置 XeLaTeX 编译脚本，支持 Docker 一键构建

## 🏗️ Architecture / 架构

```
Word .docx
    │
    ▼
┌─────────────────────┐
│  extract_docx.py    │  ← 封面元数据提取
│  pandoc_ast_extract  │  ← Pandoc AST 深度解析
└────────┬────────────┘
         │ chapters/*.tex + metadata
         ▼
┌─────────────────────┐
│  template_adapter    │  ← 组装 main.tex (DissertUESTC 宏)
│  refs_to_footnotes   │  ← [马院] 引用 → 脚注转换
│  categorize_refs     │  ← [马院] 四分类参考文献
└────────┬────────────┘
         │ main.tex + bibliography
         ▼
┌─────────────────────┐
│  compile.ps1        │  ← XeLaTeX × 4 编译
│  postflight_check   │  ← PDF 质量审计
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
git clone https://github.com/your-username/uestc-thesis-formatter.git
cd uestc-thesis-formatter

# 2. Install dependencies
pip install -r requirements.txt

# 3. (Optional) Clone upstream LaTeX template
git submodule update --init --recursive
```

### Usage / 使用

```bash
# 标准模式：提取 Word 并生成 LaTeX
python scripts/extract_docx.py --input thesis.docx --output-dir ./output/

# 完整 Pipeline (v2)：提取 + 组装 + 编译
python scripts/run_v2.py --input thesis.docx --profile marxism --output-dir ./output/
```

## 📁 Project Structure / 项目结构

```
uestc-thesis-formatter/
├── scripts/                    # 核心引擎
│   ├── pandoc_ast_extract.py   # Pandoc AST 解析器 (1700+ lines)
│   ├── extract_docx.py         # Word 封面元数据提取
│   ├── template_adapter.py     # main.tex 组装器
│   ├── refs_to_footnotes.py    # 引用 → 脚注转换 [马院]
│   ├── categorize_refs.py      # 四分类参考文献 [马院]
│   ├── normalize_citations.py  # 引用标记规范化
│   ├── preflight_check.py      # 输入质量检查
│   ├── postflight_check.py     # PDF 输出审计
│   ├── thesis_validator.py     # 3-Gate 合规验证
│   ├── compile.ps1             # XeLaTeX 编译脚本
│   └── run_v2.py               # Pipeline 编排器
├── profiles/                   # 学院配置
│   ├── marxism.json            # 马克思主义学院
│   └── stem.json               # 理工科标准模式
├── templates/                  # 模板规范
│   └── uestc-marxism/
│       ├── profile.json        # 详细配置
│       └── checklist.md        # 23 项 QA 清单
├── tests/                      # 测试套件
├── examples/                   # 示例数据
│   └── sample_meta.json        # 封面元数据示例
├── references/                 # 排版规范
│   └── uestc_format_spec.md    # UESTC 论文格式标准
├── thesis_acceptance.json      # 合规验收标准
├── requirements.txt
└── LICENSE
```

## 📋 Supported Profiles / 支持的学院模式

| Profile | 引用方式 | 参考文献 | 状态 |
|---------|---------|---------|------|
| **marxism** (马克思主义学院) | 脚注制 ①-⑳ (每页重置) | 四分类 (著作/期刊/论文/网页) | ✅ 已验证 |
| **stem** (理工科标准) | `\cite{}` 上标编号 | BibTeX 统一列表 | 🚧 开发中 |

## 🙏 Credits / 致谢

本项目基于 [DissertationUESTC](https://github.com/MGG1996/DissertationUESTC) LaTeX 模板构建，原始项目源自 [x-magus/ThesisUESTC](https://github.com/x-magus/ThesisUESTC)，遵循 [LPPL (LaTeX Project Public License)](https://www.latex-project.org/lppl/) 协议。

本项目的贡献在于 **自动化的 Word → LaTeX 转换引擎** 和 **马克思主义学院专用脚注/分类参考文献 Pipeline**，而非 LaTeX 模板本身。

## 📄 License

- **Python 代码** (`scripts/`, `run.py` 等)：[MIT License](LICENSE)
- **LaTeX 模板** (`vendor/DissertationUESTC/`)：[LPPL](https://www.latex-project.org/lppl/)

---

<div align="center">
Made with ❤️ for UESTC graduate students
</div>
