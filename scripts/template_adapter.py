#!/usr/bin/env python3
"""
template_adapter.py — DissertationUESTC 模板适配层

将 cover_metadata.json 中的元数据翻译为 DissertUESTC.cls 所需的 LaTeX 命令序列。
run_v2.py 通过此模块生成 main.tex，不再硬编码任何 LaTeX 命令字符串。

宏签名参考:
  - tutorial.tex L28-106 (uestccover / uestczhtitlepage / uestcentitlepage / declaration)
  - DissertUESTC.cls L2319-2369 (acknowledgement / achievement)
  - DissertUESTC.cls L1858-1893 (zhabstract / enabstract / zhkeywords / enkeywords)
"""

import json
import os
from typing import Optional


# =============================================================================
# Degree-type mapping (旧 profile 字段 → CLS documentclass option)
# =============================================================================
DEGREE_MAP = {
    "bachelor": "bachelor",
    "master": "master",
    "promaster": "promaster",
    "doctor": "doctor",
    "prodoctor": "prodoctor",
    "engdoctor": "doctor",          # legacy alias
    "doublebachelor": "doublebachelor",
    "intmaster": "intmaster",
    "intdoctor": "intdoctor",
}

# 旧模板命令 → 绝对不允许出现在新产出中
FORBIDDEN_LEGACY_TOKENS = [
    "thesis-uestc",
    "main_multifile.tex",
    r"\thesisbibliography",
    r"\thesisaccomplish",
    r"\makecover",
    r"\begin{chineseabstract}",
    r"\end{chineseabstract}",
    r"\begin{englishabstract}",
    r"\end{englishabstract}",
    r"\chinesekeyword",
    r"\englishkeyword",
    r"\thesistableofcontents",
    r"\thesisacknowledgement",
]


def _safe(value: Optional[str], fallback: str = "") -> str:
    """Return value or fallback, never None."""
    if value is None or str(value).strip() == "":
        return fallback
    return str(value).strip()


def load_metadata(meta_path: str) -> dict:
    """Load cover_metadata.json with fallback defaults."""
    with open(meta_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # Apply fallback defaults for fields the old extractor doesn't produce
    defaults = {
        "title_cn": "",
        "title_en": "",
        "author_cn": "~",
        "author_en": "~",
        "student_id": "",
        "major_cn": "",
        "major_en": "",
        "school_cn": "",
        "school_en": "",
        "advisor_name_cn": "~",
        "advisor_title_cn": "",
        "advisor_unit": "电子科技大学",
        "advisor_unit_addr": "成都",
        "advisor_en": "~",
        "degree_type": "master",
        "cls_num": "",
        "udc": "",
        "submit_date": "",
        "defense_date": "",
        "grant_unit": "电子科技大学",
        "grant_date": "",
    }
    for k, v in defaults.items():
        if k not in raw or raw[k] is None or str(raw[k]).strip() == "":
            raw[k] = v
    return raw


# =============================================================================
# Emitters — each returns a LaTeX string fragment
# =============================================================================

def emit_documentclass(meta: dict, print_mode: str = "nonprint") -> str:
    """Generate \\documentclass line.

    Args:
        meta: Metadata dict with 'degree_type' key.
        print_mode: One of 'nonprint', 'print', 'review'.
    """
    degree = DEGREE_MAP.get(meta.get("degree_type", "master"), "master")
    return f"\\documentclass[{degree}, {print_mode}]{{DissertUESTC}}\n"


def emit_cover(meta: dict) -> str:
    """Generate \\uestccover command.

    Signature: \\uestccover{题目}{专业}{学号}{姓名}{导师}{职称}{学院}
    """
    lines = [
        f"\\uestccover{{{_safe(meta['title_cn'])}}}",
        f"            {{{_safe(meta['major_cn'])}}}",
        f"            {{{_safe(meta['student_id'])}}}",
        f"            {{{_safe(meta['author_cn'])}}}",
        f"            {{{_safe(meta['advisor_name_cn'])}}}",
        f"            {{{_safe(meta['advisor_title_cn'])}}}",
        f"            {{{_safe(meta['school_cn'])}}}",
    ]
    return "\n".join(lines) + "\n"


def emit_zh_titlepage(meta: dict) -> str:
    """Generate Chinese title page setup + \\uestczhtitlepage.

    Only for graduate students (master/promaster/doctor).
    """
    degree = meta.get("degree_type", "master")
    if degree == "bachelor":
        return "% 学士论文无中文扉页\n"

    lines = [
        f"\\ClsNum{{{_safe(meta['cls_num'])}}}",
        f"\\ClsLv{{公开}}",
        f"\\UDC{{{_safe(meta['udc'])}}}",
        f"\\DissertationTitle{{{_safe(meta['title_cn'])}}}",
        f"\\Author{{{_safe(meta['author_cn'])}}}",
        f"\\Supervisor{{{_safe(meta['advisor_name_cn'])}}}"
        f"{{{_safe(meta['advisor_title_cn'])}}}"
        f"{{{_safe(meta['advisor_unit'])}}}"
        f"{{{_safe(meta['advisor_unit_addr'])}}}",
        f"\\Major{{{_safe(meta['major_cn'])}}}",
        f"\\Date{{{_safe(meta['submit_date'])}}}{{{_safe(meta['defense_date'])}}}",
        f"\\Grant{{{_safe(meta['grant_unit'])}}}{{{_safe(meta['grant_date'])}}}",
        "\\uestczhtitlepage",
    ]
    return "\n".join(lines) + "\n"


def emit_en_titlepage(meta: dict) -> str:
    """Generate English title page.

    Signature: \\uestcentitlepage{题目}{专业}{学号}{作者}{导师}{副导师}{学院}
    """
    degree = meta.get("degree_type", "master")
    if degree == "bachelor":
        return "% 学士论文无英文扉页\n"

    lines = [
        f"\\uestcentitlepage{{{_safe(meta['title_en'])}}}",
        f"                 {{{_safe(meta['major_en'])}}}",
        f"                 {{{_safe(meta['student_id'])}}}",
        f"                 {{{_safe(meta.get('author_en', ''))}}}",
        f"                 {{{_safe(meta.get('advisor_en', ''))}}}{{}}",
        f"                 {{{_safe(meta['school_en'])}}}",
    ]
    return "\n".join(lines) + "\n"


def emit_declaration(meta: dict) -> str:
    """Generate \\declaration command.

    Signature: \\declaration{日期}{作者签名}{导师签名}
    """
    degree = meta.get("degree_type", "master")
    if degree == "bachelor":
        return "% 学士论文无独创性声明\n"
    return "\\declaration{}{}{}\n"


def emit_abstract_zh(body: str, keywords: str) -> str:
    """Generate Chinese abstract block."""
    return f"\\zhabstract\n{body}\n\\zhkeywords{{{keywords}}}\n"


def emit_abstract_en(body: str, keywords: str) -> str:
    """Generate English abstract block."""
    return f"\\enabstract\n{body}\n\\enkeywords{{{keywords}}}\n"


def emit_toc() -> str:
    """Generate table of contents."""
    return "\\tableofcontents\n"


def emit_chapter_inputs(chapter_files: list) -> str:
    """Generate \\input lines for chapters.

    Args:
        chapter_files: e.g. ['chapter/ch01', 'chapter/ch02'] (no .tex extension)
    """
    lines = [f"\\input{{{cf}}}" for cf in chapter_files]
    return "\n".join(lines) + "\n"


def emit_conclusion(conclusion_file: str = "misc/conclusion") -> str:
    """Generate conclusion \\input (结语 as standalone chapter)."""
    return f"\\input{{{conclusion_file}}}\n"


def emit_acknowledgement(ack_file: str = "misc/acknowledgement") -> str:
    """Generate acknowledgement block using new template macro.

    CLS L2320: \\acknowledgement automatically creates chapter* + markboth + toc entry.
    """
    return f"\\acknowledgement\n\\input{{{ack_file}}}\n"


def emit_bibliography_standard(bib_base: str = "ref") -> str:
    """Generate standard bibliography via BibTeX.

    CLS L2068-2092: \\bibliography overridden to add toc + markboth automatically.
    """
    return f"\\bibliography{{{bib_base}}}\n"


def emit_bibliography_categorized(bib_file: str = "bibliography_categorized") -> str:
    """Generate categorized bibliography for Marxism School.

    Since we bypass BibTeX and use \\input, we must manually create
    the chapter heading, toc entry, and markboth that the CLS's
    \\bibliography wrapper would normally provide.
    """
    lines = [
        "\\chapter*{参考文献}",
        "\\addcontentsline{toc}{chapter}{参考文献}",
        "\\markboth{参考文献}{参考文献}",
        f"\\input{{{bib_file}}}",
    ]
    return "\n".join(lines) + "\n"


def emit_achievement(acc_file: str = "misc/accomplishments") -> str:
    """Generate achievement block using new template macro.

    CLS L2354: \\achievement automatically creates chapter* + markboth + toc entry
    and sets the title based on degree type.
    """
    return f"\\achievement\n\\input{{{acc_file}}}\n"


# =============================================================================
# Full main.tex assembly
# =============================================================================

def assemble_main_tex(
    meta: dict,
    chapter_files: list,
    abstract_zh_body: str = "",
    abstract_zh_keywords: str = "",
    abstract_en_body: str = "",
    abstract_en_keywords: str = "",
    has_conclusion: bool = True,
    has_accomplishments: bool = True,
    bib_mode: str = "standard",
    print_mode: str = "nonprint",
) -> str:
    """Assemble a complete main.tex from metadata and content references.

    Returns the full LaTeX source as a string.
    """
    # Apply fallback defaults so callers don't need to go through load_metadata
    _defaults = {
        "title_cn": "", "title_en": "", "author_cn": "~", "author_en": "~",
        "student_id": "", "major_cn": "", "major_en": "",
        "school_cn": "", "school_en": "",
        "advisor_name_cn": "~", "advisor_title_cn": "",
        "advisor_unit": "电子科技大学", "advisor_unit_addr": "成都",
        "advisor_en": "~", "degree_type": "master",
        "cls_num": "", "udc": "", "submit_date": "", "defense_date": "",
        "grant_unit": "电子科技大学", "grant_date": "",
    }
    for k, v in _defaults.items():
        if k not in meta or meta[k] is None or str(meta[k]).strip() == "":
            meta[k] = v

    parts = [
        "% !TEX Program = xelatex\n",
        "% Generated by thesis-formatter pipeline (DissertUESTC adapter)\n",
        emit_documentclass(meta, print_mode),
        "\\usepackage{tabularx}  % For complex adaptive tables\n",
        "\\usepackage{booktabs}  % For standard three-line tables\n",
        "\\usepackage{multirow}  % For cell merging\n",
        "\\usepackage{caption}\n",
        "\\usepackage{float}     % For [H] absolute table positioning\n",
        "\\captionsetup[table]{aboveskip=12bp, belowskip=6bp}\n",
        "\\captionsetup[figure]{aboveskip=6bp, belowskip=12bp}\n",
        "\\setlength{\\heavyrulewidth}{1.5pt}\n",
        "\\setlength{\\lightrulewidth}{0.75pt}\n",
        "\\setlength{\\baselineskip}{20bp}\n",
        "\n\\begin{document}\n\n",
        "% === 封面 ===\n",
        emit_cover(meta),
        "\n% === 中文扉页 ===\n",
        emit_zh_titlepage(meta),
        "\n% === 英文扉页 ===\n",
        emit_en_titlepage(meta),
        "\n% === 独创性声明 ===\n",
        emit_declaration(meta),
        "\n% === 中文摘要 ===\n",
        emit_abstract_zh(abstract_zh_body, abstract_zh_keywords),
        "\n% === 英文摘要 ===\n",
        emit_abstract_en(abstract_en_body, abstract_en_keywords),
        "\n% === 目录 ===\n",
        emit_toc(),
        "\n% === 正文章节 ===\n",
        emit_chapter_inputs(chapter_files),
    ]

    if has_conclusion:
        parts.append("\n% === 结语 ===\n")
        parts.append(emit_conclusion())

    parts.append("\n% === 致谢 ===\n")
    parts.append(emit_acknowledgement())

    parts.append("\n% === 参考文献 ===\n")
    if bib_mode == "categorized":
        parts.append(emit_bibliography_categorized())
    else:
        parts.append(emit_bibliography_standard())

    if has_accomplishments:
        parts.append("\n% === 成果 ===\n")
        parts.append(emit_achievement())

    parts.append("\n\\end{document}\n")

    result = "".join(parts)

    # Sanity check: no legacy tokens should appear
    for token in FORBIDDEN_LEGACY_TOKENS:
        if token in result:
            raise RuntimeError(
                f"LEGACY TOKEN DETECTED in generated main.tex: '{token}'. "
                f"This indicates a bug in the template adapter."
            )

    return result


# =============================================================================
# CLI for standalone testing
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="DissertUESTC Template Adapter")
    parser.add_argument("--meta", required=True, help="Path to cover_metadata.json")
    parser.add_argument("--chapters", nargs="+", default=["chapter/ch01"],
                        help="Chapter file paths (without .tex)")
    parser.add_argument("--bib-mode", choices=["standard", "categorized"],
                        default="standard")
    parser.add_argument("--output", default=None, help="Output path (default: stdout)")
    args = parser.parse_args()

    meta = load_metadata(args.meta)
    result = assemble_main_tex(
        meta=meta,
        chapter_files=args.chapters,
        bib_mode=args.bib_mode,
    )

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(result)
        print(f"✅ Written to {args.output}")
    else:
        print(result)
