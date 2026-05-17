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
import re
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


def escape_latex_specials_in_prose(text: str) -> str:
    r"""对正文(摘要/关键词)中 LaTeX 特殊字符做最小必要转义.

    D22: % 被当注释吞段
    D26 (Round 8 shared): ~ 被 LaTeX 当不间断空格 → 中文范围号 `0~3%` 渲染成空格,
       中文论文范围号必须显示为字面 `~`, 用 \textasciitilde{} 包.
    保留 \\ 反斜杠 (合法宏 \cite \textbf 等); 保留 ^ (Unicode 上标客户用的不是 LaTeX ^).
    转义: % & # $ _ ~
    """
    for ch in ("%", "&", "#", "$", "_"):
        text = re.sub(r"(?<!\\)" + re.escape(ch), "\\\\" + ch, text)
    # D26: ~ 替换为字面波浪号宏
    text = re.sub(r"(?<!\\)~", r"\\textasciitilde{}", text)
    return text


def load_metadata(meta_path: str) -> dict:
    """Load cover_metadata.json with fallback defaults."""
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"cover_metadata.json 解析失败 ({meta_path}): {e}\n"
            f"请检查文件是否为合法 JSON 格式。"
        ) from e
    except FileNotFoundError:
        raise RuntimeError(
            f"cover_metadata.json 不存在: {meta_path}\n"
            f"请确认提取步骤已正确运行。"
        )

    if not isinstance(raw, dict):
        raise RuntimeError(
            f"cover_metadata.json 内容不是字典: 实际类型为 {type(raw).__name__}"
        )

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

    D28 (Round 8 shared): 总加 'noreminder' 选项, 防 CLS 内置红字
    "Chinese Abstract has exceeded the maximum limit" 泄漏到产物.
    """
    degree = DEGREE_MAP.get(meta.get("degree_type", "master"), "master")
    return f"\\documentclass[{degree}, {print_mode}, noreminder]{{DissertUESTC}}\n"


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


def parse_abstract_text(content: str, lang: str) -> tuple:
    """Parse abstract_zh.txt / abstract_en.txt content into (body, keywords).

    CASE-A (round 2) 凝结: 客户原稿 docx 摘要段常含两类垃圾, 必须 strip:
    - 首行 header: "摘要" / "ABSTRACT" / "摘 要" — CLS \\zhabstract / \\enabstract 已自动加大标题
    - 尾行 trailer: "Abstract" / "ABSTRACT" / "摘要" / "Keywords" — 客户在中/英摘要段尾写下个 section header

    Args:
        content: raw text from abstract_zh.txt or abstract_en.txt.
        lang: "zh" or "en".

    Returns:
        (body, keywords) — both strings, body without keywords line, keywords without "关键词:" / "Keywords:" prefix.
    """
    content = content.strip()

    # Strip leading header line (case-insensitive)
    leading_pat = re.compile(r"^\s*(?:摘\s*要|ABSTRACT)\s*\n+", re.IGNORECASE)
    content = leading_pat.sub("", content)

    # Strip trailing section-bleed lines (other-language abstract header,
    # bare "Keywords" without args). Loop because sometimes both a blank line
    # and the trailer remain.
    trailing_pats = [
        re.compile(r"\n\s*(?:Abstract|ABSTRACT|摘\s*要)\s*$", re.IGNORECASE),
        re.compile(r"\n\s*(?:Keywords?|关键词)\s*[:：]?\s*$", re.IGNORECASE),
    ]
    changed = True
    while changed:
        changed = False
        for pat in trailing_pats:
            new = pat.sub("", content).rstrip()
            if new != content:
                content = new
                changed = True

    # Extract keywords line and split body
    if lang == "zh":
        kw_pat = re.compile(r"(?:关键词|Keywords?)\s*[:：]\s*(.+)", re.IGNORECASE | re.MULTILINE)
    else:
        kw_pat = re.compile(r"(?:Keywords?|关键词)\s*[:：]\s*(.+)", re.IGNORECASE | re.MULTILINE)

    keywords = ""
    body = content
    m = kw_pat.search(content)
    if m:
        keywords = m.group(1).strip()
        body = content[:m.start()].rstrip()

    keywords = _normalize_keyword_separator(keywords, lang)
    return body, keywords


def _normalize_keyword_separator(keywords: str, lang: str) -> str:
    """关键词分隔符归一化 (CASE-A round 4 lun51 fix; CASE-A EN re-tune).

    UESTC 规范要求关键词分隔符与 lang 严格对应:
      ZH: 全角逗号 '，'
      EN: 半角逗号 + 空格 ', '  (CASE-A lun51 严重错误: "分隔符 { ; } 不符合规范要求 { , }")
    客户原稿常误用 '、' / ';' / 半角 ',', 在 emit 前统一.
    """
    if not keywords:
        return keywords
    if lang == "zh":
        s = re.sub(r"\s*[、；;,，]\s*", "，", keywords)
    else:
        # CASE-A: 英文 keywords 用 ', ' 分隔 (lun51 本科规范明确). 旧默认 ';' 是
        # CASE-A round 4 误判, 见 reference/defects/D45 (待验证旧 marxism case
        # 实际偏好). 如未来某 marxism case lun51 期望 ';', 用 profile-aware 派发.
        s = re.sub(r"\s*[、；;,，]\s*", ", ", keywords)
    return s.strip("，, \t")


def emit_abstract_zh(body: str, keywords: str) -> str:
    """Generate Chinese abstract block."""
    body = escape_latex_specials_in_prose(body)
    keywords = escape_latex_specials_in_prose(keywords)
    return f"\\zhabstract\n{body}\n\\zhkeywords{{{keywords}}}\n"


def emit_abstract_en(body: str, keywords: str) -> str:
    """Generate English abstract block."""
    body = escape_latex_specials_in_prose(body)
    keywords = escape_latex_specials_in_prose(keywords)
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


def _ordered_cite_keys(cite_map) -> list:
    """Return cite_map values in numeric-string-key order ("1","2",...), skipping holes.

    Used by emit_nocite_prelude and emit_bibliography_standard so a single
    representation of "docx [1]-[N] order" is shared.
    """
    if not (cite_map and isinstance(cite_map, dict)):
        return []
    keys = []
    for i in range(1, len(cite_map) + 1):
        k = cite_map.get(str(i))
        if k:
            keys.append(k)
    return keys


def emit_nocite_prelude(cite_map: dict = None) -> str:
    """D24 fix v2 (CASE-A, 2026-05-08): emit \\nocite block BEFORE \\input{chapter}.

    bibtex 按 .aux 中 \\citation 出现顺序输出 bbl. 若 \\nocite 块紧贴 \\bibliography 在
    章节后, 章节内 \\cite 先记录, 作者非 [1]→[N] 顺序引用时 bbl 错位 (case_anon ch01 首条
    cite 是 [3,4,5]). 把 \\nocite 块提前到 \\begin{document} 后面 (章节 \\input 之前)
    让 cite_map 顺序的 \\nocite 抢先记录, bbl 就跟 cite_map 顺序.

    返回空串当 cite_map 为空 (这种情况由 emit_bibliography_standard 走 \\nocite{*} fallback).
    """
    keys = _ordered_cite_keys(cite_map)
    if not keys:
        return ""
    nocite_block = "\n".join(f"\\nocite{{{k}}}" for k in keys)
    return (
        "% D24 fix v2 (CASE-A): \\nocite 在 \\input{chapter} 前 emit, bbl 跟 cite_map 顺序\n"
        + nocite_block + "\n"
    )


def emit_bibliography_standard(bib_base: str = "ref", cite_map: dict = None,
                                nocite_in_prelude: bool = False) -> str:
    """Generate standard bibliography via BibTeX.

    CLS L2068-2092: \\bibliography overridden to add toc + markboth automatically.

    D24 (Round 8 shared): 不再用 \\nocite{*} (会按 ref.bib 字典序排), 改为按 cite_map
    顺序逐条 \\nocite{key}, 保证 bbl 顺序 = docx 原 [1]-[N]. cite_map 为空时仍 fallback
    到 \\nocite{*} 兼容.

    D24 v2 (CASE-A, 2026-05-08): nocite_in_prelude=True 时跳过 \\nocite 块 (调用方已通过
    emit_nocite_prelude 在 \\begin{document} 后 emit), 仅返回 \\bibliography{ref}.

    Args:
        bib_base: BibTeX file basename (no .bib).
        cite_map: dict {"1": "key1", "2": "key2", ...} — extracted/cite_map.json content.
        nocite_in_prelude: True 表示 \\nocite 块已在 prelude emit, 此处仅返回 \\bibliography.
    """
    if nocite_in_prelude:
        return f"\\bibliography{{{bib_base}}}\n"
    keys = _ordered_cite_keys(cite_map)
    if keys:
        nocite_block = "\n".join(f"\\nocite{{{k}}}" for k in keys)
        return (
            "% D24 fix: 按 cite_map 顺序逐条 nocite, 让 bbl = docx 原 [1]-[N] 顺序\n"
            + nocite_block + "\n"
            + f"\\bibliography{{{bib_base}}}\n"
        )
    # Fallback: 没 cite_map 时仍用 \nocite{*}
    return f"\\nocite{{*}}\n\\bibliography{{{bib_base}}}\n"


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


def emit_foreign_appendix(orig_file: str = "misc/foreign_original",
                          trans_file: str = "misc/foreign_translation") -> str:
    """Generate 外文资料原文 + 外文资料译文 sections (本科必含, spec §1.1 #20-21).

    Each section is a chapter*-style heading with toc entry + markboth + input.
    The CLS doesn't have a dedicated macro for these (research thesis spec
    doesn't have foreign appendix), so we mirror the categorized-bibliography
    pattern manually.
    """
    blocks = []
    for label, fname in [("外文资料原文", orig_file),
                         ("外文资料译文", trans_file)]:
        # CASE-A fix (2026-05-08): 旧版 fallback 用 \textit{(待补)} 在 xeCJK 下渲染不出
        # (chapter* 后无 \par 进入垂直模式 + \textit 对 CJK 无 italic). 改用显式
        # \par\noindent\textbf 强制可见占位符. 客户漏写时 PDF 不再空白页.
        placeholder = (
            f"\\par\\vspace{{1em}}\\noindent"
            f"\\textbf{{【提示】客户原 docx 未提供 {label} 章节内容。"
            f"请客户补充后重新生成。}}\\par"
        )
        blocks.extend([
            f"\\chapter*{{{label}}}",
            f"\\addcontentsline{{toc}}{{chapter}}{{{label}}}",
            f"\\markboth{{{label}}}{{{label}}}",
            f"\\IfFileExists{{{fname}.tex}}{{\\input{{{fname}}}}}{{{placeholder}}}",
        ])
    return "\n".join(blocks) + "\n"


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
    cite_map: dict = None,
) -> str:
    """Assemble a complete main.tex from metadata and content references.

    Returns the full LaTeX source as a string.

    Raises:
        ValueError: If chapter_files is empty or meta is invalid.
        RuntimeError: If legacy tokens are detected in output.
    """
    if not chapter_files:
        raise ValueError(
            "chapter_files 不能为空 — 至少需要一个章节文件。"
            "请检查提取步骤是否正确生成了 chapter/ 目录。"
        )
    if not isinstance(meta, dict):
        raise ValueError(f"meta 必须为字典，实际类型为 {type(meta).__name__}")
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
        "\\captionsetup{font={small}}\n",
        "\\captionsetup[table]{aboveskip=12bp, belowskip=6bp}\n",
        "\\captionsetup[figure]{aboveskip=6bp, belowskip=12bp}\n",
        "\\setlength{\\heavyrulewidth}{1.5pt}\n",
        "\\setlength{\\lightrulewidth}{0.75pt}\n",
        "\\setlength{\\baselineskip}{20bp}\n",
    ]

    # D27 (Round 8 shared): bachelor/master/doctor 正文 \cite 重定向为上标
    # marxism 跳过 (它用脚注引用而非 \cite, 不需要上标)
    degree_for_cite = meta.get("degree_type", "master")
    if bib_mode != "categorized" and degree_for_cite != "marxism":
        parts.extend([
            "\n% D27 fix: 正文文献引用必须为上标 [n] (uestc_*_format_spec.md)\n",
            "% \\let 备份原 \\cite 避免 \\renewcommand 递归\n",
            "\\let\\origcite=\\cite\n",
            "\\renewcommand{\\cite}[1]{\\textsuperscript{\\origcite{#1}}}\n",
        ])

    parts.extend([
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
    ])

    # D24 fix v2 (CASE-A, 2026-05-08): emit \nocite 块在章节 \input 前.
    # bibtex 按 .aux \citation 顺序输出 bbl, 提前 emit 让 cite_map 顺序抢先记录.
    if bib_mode != "categorized":
        nocite_prelude = emit_nocite_prelude(cite_map)
        if nocite_prelude:
            parts.append("\n% === \\nocite prelude (D24 v2: 在 \\input{chapter} 前 emit) ===\n")
            parts.append(nocite_prelude)

    parts.extend([
        "\n% === 正文章节 ===\n",
        emit_chapter_inputs(chapter_files),
    ])

    if has_conclusion:
        parts.append("\n% === 结语 ===\n")
        parts.append(emit_conclusion())

    parts.append("\n% === 致谢 ===\n")
    parts.append(emit_acknowledgement())

    parts.append("\n% === 参考文献 ===\n")
    if bib_mode == "categorized":
        parts.append(emit_bibliography_categorized())
    else:
        # D24 v2: \nocite 已在 prelude emit, 此处仅 emit \bibliography{ref}
        parts.append(emit_bibliography_standard(cite_map=cite_map, nocite_in_prelude=True))

    if has_accomplishments:
        parts.append("\n% === 成果 ===\n")
        parts.append(emit_achievement())

    # 外文资料原文 + 译文 (本科必含, spec §1.1 #20-21)
    # CASE-A fix: 仅本科 (degree_type=bachelor) 输出;研究生不含此 section
    if meta.get("degree_type") == "bachelor":
        parts.append("\n% === 外文资料 (本科必含) ===\n")
        parts.append(emit_foreign_appendix())

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
