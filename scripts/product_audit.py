#!/usr/bin/env python3
"""product_audit.py — 产物审计器 (Step 6c, postflight 之后)

填补流水线现有 7 层检测的盲区, 15 项硬/软检测:

  Check 1 (P0): 媒体资产完整性
  Check 2 (P0): LaTeX log 语义错误 (multiply-defined / undefined ref/cite)
  Check 3 (P1 warn): 占位符识别 (XX老师/TODO/略/...)

  Round 7 阶段 C 新增 (CASE-A v6→v10 客户视觉发现的 4 类 P0):
  Check 4 (P0): 摘要长度 parity — PDF 摘要文本字数 vs extracted abstract 字数 偏差 > 30% → ❌ (D22 % 吞段)
  Check 5 (P0): bbl 顺序 vs cite_map — \\bibitem 顺序与 docx 原 [1]-[N] 不一致 → ❌ (D24 \\nocite{*})
  Check 6 (P0): 引用上标字号 — PDF [N]/[N, M] span size > body * 0.85 (即非上标) → ❌ (D27 cite 行内)
  Check 7 (P0): PDF 残留字样 — "has exceeded the maximum limit" / "\\textsuperscript{" 字面 / "??" → ❌ (D28 reminder)

CASE-A 触发本审计器加固 — 客户视觉抽查发现 4 轮反复 = 双层保险缺位代价.

Usage:
    python product_audit.py --workdir <DissertationUESTC dir> [--docx <input.docx>] [--extracted <extracted dir>]
    # 退出码: 0 全绿; 1 P0 红灯阻断; 2 仅 P1 警告(不阻断, 但提醒)

extracted dir 默认从 workdir 父目录推测 (workdir=`output_<id>/DissertationUESTC/` → extracted=`output_<id>/extracted/`).
"""

from __future__ import annotations
import argparse
import glob
import html
import json
import os
import re
import sys
import zipfile
from typing import Dict, List, Set, Tuple

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


# ============================================================
# Check 1: 媒体资产完整性
# ============================================================

INCLUDEGRAPHICS_RE = re.compile(
    r"\\includegraphics(?:\[[^\]]*\])?\{(?:media/)?([^}]+)\}"
)


def list_media_files(workdir: str) -> Set[str]:
    """列 DissertationUESTC/media/* 文件 (basename only)"""
    media_dir = os.path.join(workdir, "media")
    if not os.path.isdir(media_dir):
        return set()
    return {
        f for f in os.listdir(media_dir)
        if os.path.isfile(os.path.join(media_dir, f))
        and not f.startswith(".")
    }


def collect_includegraphics_refs(workdir: str) -> Set[str]:
    """grep chapter/*.tex + misc/*.tex 的所有 \\includegraphics 引用 (basename)"""
    refs: Set[str] = set()
    patterns = [
        os.path.join(workdir, "chapter", "*.tex"),
        os.path.join(workdir, "misc", "*.tex"),
    ]
    for pattern in patterns:
        for tex_path in glob.glob(pattern):
            try:
                with open(tex_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except OSError:
                continue
            for m in INCLUDEGRAPHICS_RE.finditer(content):
                # m.group(1) 可能含路径前缀如 "fig/x.png" 或 "x.png"
                refs.add(os.path.basename(m.group(1)))
    return refs


def count_docx_media(docx_path: str) -> int:
    """统计 docx 内嵌图数 (word/media/image*)"""
    try:
        with zipfile.ZipFile(docx_path) as z:
            return sum(
                1 for n in z.namelist()
                if n.startswith("word/media/") and not n.endswith("/")
            )
    except (FileNotFoundError, zipfile.BadZipFile):
        return -1


# 校徽等模板自带, 不属于客户引用范围
ALLOWED_UNREFERENCED = {"image1.png", "image1.jpeg", "image1.jpg", "logo.png"}


def check_media_integrity(workdir: str, docx_path: str) -> Tuple[bool, List[str]]:
    """返回 (passed, lines).

    passed=False 当 unreferenced 超出允许集 OR 有 dangling 引用.
    """
    lines = ["[Check 1] 媒体资产完整性"]
    media = list_media_files(workdir)
    refs = collect_includegraphics_refs(workdir)
    docx_count = count_docx_media(docx_path) if docx_path else -1

    unreferenced = media - refs
    dangling = refs - media
    real_unreferenced = unreferenced - ALLOWED_UNREFERENCED

    lines.append(f"  docx 内嵌图: {docx_count if docx_count >= 0 else '?'} 张")
    lines.append(f"  media/ 实际复制: {len(media)} 张")
    lines.append(f"  \\includegraphics 引用: {len(refs)} 处")

    passed = True
    if real_unreferenced:
        lines.append(
            f"  ❌ 未引用 media ({len(real_unreferenced)} 张): "
            f"{sorted(real_unreferenced)}"
        )
        lines.append(
            f"     建议: 跑 figure recovery 或手补 \\includegraphics 到对应章节"
        )
        passed = False
    elif unreferenced:
        lines.append(
            f"  ⚠️  未引用 media (允许集): {sorted(unreferenced)} (校徽等模板自带)"
        )

    if dangling:
        lines.append(f"  ❌ dangling 引用 ({len(dangling)} 处): {sorted(dangling)}")
        lines.append(f"     建议: \\includegraphics 指向的文件不在 media/")
        passed = False

    if docx_count > 0 and docx_count != len(media):
        lines.append(
            f"  ⚠️  docx 图数 ({docx_count}) ≠ media/ 数 ({len(media)}) "
            f"(extract 阶段图复制可能漏)"
        )

    if passed:
        lines.append("  ✅ 媒体资产完整性通过")
    return passed, lines


# ============================================================
# Check 2: LaTeX log 语义解析
# ============================================================

LOG_PATTERNS = [
    ("multiply_defined", re.compile(r"LaTeX Warning: Label `([^']+)' multiply defined"), True),
    ("undefined_ref",    re.compile(r"LaTeX Warning: Reference `([^']+)' on page \d+ undefined"), True),
    ("undefined_cite",   re.compile(r"(?:Package natbib )?Warning: Citation `([^']+)' on page \d+ undefined"), True),
    ("too_many_passes",  re.compile(r"'xelatex' needed too many passes"), False),  # warning only
]


def check_latex_log(workdir: str) -> Tuple[bool, List[str]]:
    """解析 main.log, 返回 (passed, lines)"""
    lines = ["[Check 2] LaTeX log 语义"]
    log_path = os.path.join(workdir, "main.log")
    if not os.path.isfile(log_path):
        lines.append(f"  ⚠️  main.log 不存在, 跳过")
        return True, lines

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            log = f.read()
    except OSError as e:
        lines.append(f"  ⚠️  读 log 失败: {e}")
        return True, lines

    hits: Dict[str, Set[str]] = {k: set() for k, _, _ in LOG_PATTERNS}
    for kind, pat, _ in LOG_PATTERNS:
        for m in pat.finditer(log):
            try:
                hits[kind].add(m.group(1))
            except IndexError:
                hits[kind].add("(no name)")

    passed = True
    for kind, _, is_hard in LOG_PATTERNS:
        items = hits[kind]
        if not items:
            continue
        if is_hard:
            passed = False
            icon = "❌"
        else:
            icon = "⚠️"
        label = {
            "multiply_defined": "multiply-defined labels",
            "undefined_ref": "undefined references",
            "undefined_cite": "undefined citations",
            "too_many_passes": "xelatex needed too many passes",
        }[kind]
        sample = sorted(items)[:5]
        suffix = f" (+{len(items)-5} more)" if len(items) > 5 else ""
        lines.append(f"  {icon} {label}: {sample}{suffix}")

    if passed and not any(hits.values()):
        lines.append("  ✅ LaTeX log 无语义错误")
    elif passed:
        lines.append("  ✅ 仅 warning, 无阻断错误")
    return passed, lines


# ============================================================
# Check 3: 占位符识别 (P1 warning)
# ============================================================

PLACEHOLDER_PATTERNS = [
    ("XX占位",         re.compile(r"XX[老教]师|XX\s*教授|XX大学|XX学院")),
    ("中文连续点",     re.compile(r"…{2,}|\.{4,}")),
    ("占位短词",       re.compile(r"\b(TODO|TBD|FIXME|XXX)\b|\[CITATION\]|Lorem ipsum|占位|待补充")),
    ("略字单段",       re.compile(r"^\s*略\s*$", re.MULTILINE)),
]


def check_placeholders(workdir: str) -> Tuple[bool, List[str]]:
    """扫 chapter+misc, 返回 (passed=True 永远(只 warning), lines)"""
    lines = ["[Check 3] 占位符识别 (warning, 不阻断)"]
    targets = (
        glob.glob(os.path.join(workdir, "chapter", "*.tex"))
        + glob.glob(os.path.join(workdir, "misc", "*.tex"))
    )
    total_hits = 0
    for tex_path in targets:
        try:
            with open(tex_path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        rel = os.path.relpath(tex_path, workdir)
        # 按行号定位
        for kind, pat in PLACEHOLDER_PATTERNS:
            for m in pat.finditer(text):
                line_no = text.count("\n", 0, m.start()) + 1
                ctx_start = max(0, m.start() - 20)
                ctx_end = min(len(text), m.end() + 30)
                ctx = text[ctx_start:ctx_end].replace("\n", " ").strip()
                lines.append(f"  ⚠️  {rel}:{line_no} [{kind}] …{ctx}…")
                total_hits += 1

    if total_hits == 0:
        lines.append("  ✅ 未检测到占位符")
    else:
        lines.append(
            f"  ⚠️  共 {total_hits} 处占位符 — 客户原稿可能未填正文 "
            f"(P0 不动客户原文, 仅告知客户补正文)"
        )
    return True, lines  # 永远不阻断


# ============================================================
# Check 4 (Round 7-C): 摘要长度 parity
# ============================================================

def _read_extracted_abstract(extracted_dir: str, lang: str) -> str:
    """读 extracted/abstract_zh.txt 或 abstract_en.txt, 去 '关键词/Keywords' 段."""
    path = os.path.join(extracted_dir, f"abstract_{lang}.txt")
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    # 去关键词段 (中文用"关键词", 英文用"Keywords")
    for kw in ("关键词:", "关键词：", "Keywords:", "Keywords：", "ABSTRACT"):
        idx = text.find(kw)
        if idx > 0:
            text = text[:idx]
    return text.strip()


def _extract_pdf_abstract(pdf_path: str, lang: str) -> str:
    """PyMuPDF 提 PDF 中文/英文摘要 zone 文本."""
    try:
        import fitz
    except ImportError:
        return ""
    if not os.path.isfile(pdf_path):
        return ""
    doc = fitz.open(pdf_path)
    out = []
    for i in range(min(8, len(doc))):  # 只看前 8 页
        t = doc[i].get_text()
        if lang == "zh" and ("摘\n要" in t or "摘 要" in t or t.strip().startswith("摘")):
            # 取从"摘要"到"关键词"或"ABSTRACT" 之前
            start = max(t.find("摘\n要"), t.find("摘 要"), t.find("摘要"))
            end = len(t)
            for marker in ("关键词:", "关键词：", "ABSTRACT", "I\n", "II\n"):
                m_idx = t.find(marker, start + 5)
                if m_idx > 0:
                    end = min(end, m_idx)
            out.append(t[start:end])
        elif lang == "en" and ("ABSTRACT" in t):
            start = t.find("ABSTRACT")
            end = len(t)
            for marker in ("Keywords:", "Keywords：", "II\n", "III\n", "IV\n"):
                m_idx = t.find(marker, start + 8)
                if m_idx > 0:
                    end = min(end, m_idx)
            out.append(t[start:end])
    doc.close()
    return "\n".join(out)


def check_abstract_parity(workdir: str, extracted_dir: str) -> Tuple[bool, List[str]]:
    """对比 PDF 摘要字数 vs extracted/abstract_*.txt 字数.

    偏差 > 30% → ❌ (D22 % 吞段症状: PDF 字数骤降 50%+).
    """
    lines = ["[Check 4] 摘要长度 parity (Round 7-C)"]
    pdf_path = os.path.join(workdir, "main.pdf")
    if not os.path.isfile(pdf_path):
        lines.append("  ⚠️  main.pdf 不存在, 跳过")
        return True, lines
    if not os.path.isdir(extracted_dir):
        lines.append(f"  ⚠️  extracted dir 不存在 ({extracted_dir}), 跳过")
        return True, lines

    passed = True
    for lang, name in [("zh", "中文摘要"), ("en", "英文摘要")]:
        src = _read_extracted_abstract(extracted_dir, lang)
        pdf = _extract_pdf_abstract(pdf_path, lang)
        if not src:
            lines.append(f"  ⚠️  {name} extracted 文本为空, 跳过")
            continue
        # 中文按字符数, 英文按 word 数
        if lang == "zh":
            src_n = len([c for c in src if c.strip()])
            pdf_n = len([c for c in pdf if c.strip()])
        else:
            src_n = len(src.split())
            pdf_n = len(pdf.split())
        if src_n == 0:
            continue
        ratio = pdf_n / src_n
        unit = "字" if lang == "zh" else "词"
        lines.append(f"  {name}: extracted {src_n} {unit}, PDF {pdf_n} {unit} (ratio {ratio:.2f})")
        if ratio < 0.70 or ratio > 1.30:
            lines.append(
                f"  ❌ {name} 字数偏差 > 30% (ratio {ratio:.2f}) — "
                f"疑似 D22 摘要 % 被 LaTeX 注释吞段 / 或字段未渲染"
            )
            passed = False

    if passed:
        lines.append("  ✅ 摘要长度 parity 通过")
    return passed, lines


# ============================================================
# Check 5 (Round 7-C): bbl 顺序 vs cite_map 一致性
# ============================================================

BIBITEM_RE = re.compile(r"^\\bibitem\{([^}]+)\}", re.MULTILINE)


def check_bbl_order(workdir: str, extracted_dir: str) -> Tuple[bool, List[str]]:
    """对比 main.bbl 的 \\bibitem 顺序 vs cite_map.json 的 1..N 顺序.

    任一错位 → ❌ (D24 \\nocite{*} 致 bbl 字典序而非原序).
    """
    import json
    lines = ["[Check 5] bbl 顺序 vs cite_map (Round 7-C)"]
    bbl_path = os.path.join(workdir, "main.bbl")
    cm_path = os.path.join(extracted_dir, "cite_map.json")
    if not os.path.isfile(bbl_path):
        lines.append("  ⚠️  main.bbl 不存在, 跳过")
        return True, lines
    if not os.path.isfile(cm_path):
        lines.append(f"  ⚠️  cite_map.json 不存在 ({cm_path}), 跳过")
        return True, lines

    with open(bbl_path, encoding="utf-8") as f:
        bbl_keys = BIBITEM_RE.findall(f.read())
    with open(cm_path, encoding="utf-8") as f:
        cm = json.load(f)
    expected_keys = [cm[str(i)] for i in range(1, len(cm) + 1) if str(i) in cm]

    lines.append(f"  bbl 条数: {len(bbl_keys)}, cite_map 条数: {len(expected_keys)}")
    if len(bbl_keys) != len(expected_keys):
        lines.append(
            f"  ❌ 条数不一致 — refs_to_bib 可能漏条目 (D23 类) "
            f"或 \\nocite/\\cite 不完整"
        )
        return False, lines

    mismatches = []
    for i, (e, a) in enumerate(zip(expected_keys, bbl_keys), 1):
        if e != a:
            mismatches.append((i, e, a))
    if mismatches:
        sample = mismatches[:5]
        suffix = f" (+{len(mismatches)-5} more)" if len(mismatches) > 5 else ""
        lines.append(f"  ❌ 顺序错位 {len(mismatches)} 处:")
        for i, e, a in sample:
            lines.append(f"     [{i}] expected={e} actual={a}")
        lines.append(suffix.strip() or "")
        lines.append(
            f"  → 疑似 D24 (\\nocite{{*}} 致字典序) 或 \\nocite 块未在 \\begin{{document}} 之后立即 emit"
        )
        return False, lines

    lines.append(f"  ✅ bbl 顺序与 cite_map 一致 ({len(bbl_keys)} 条)")
    return True, lines


# ============================================================
# Check 6 (Round 7-C): 引用上标字号检测
# ============================================================

CITE_BRACKET_RE = re.compile(r"^\[\d+(?:[,\s]+\d+)*\]$")


def _find_references_start_page(doc) -> int:
    """找参考文献章节起始页号 (1-based). 没找到返回 len+1."""
    for i in range(len(doc)):
        t = doc[i].get_text()
        # "参考文献" 标题独立成段或页眉, 排除 TOC 中的 "参考文献......"
        for line in t.split("\n"):
            s = line.strip()
            if s in ("参考文献", "References", "REFERENCES"):
                return i + 1
    return len(doc) + 1


def check_cite_superscript(workdir: str) -> Tuple[bool, List[str]]:
    """PyMuPDF dict 模式扫 PDF 正文页(参考文献页之前)所有 [N]/[N, M] span,
    字号必须 < body * 0.85 才算上标. 参考文献列表的 [1][2] 序号本身就是行内, 跳过.

    本科 spec L346 明确: 引用标注 = 上标 [n] 12磅. 行内 = ❌ (D27).
    """
    lines = ["[Check 6] 引用上标字号 (Round 7-C)"]
    pdf_path = os.path.join(workdir, "main.pdf")
    if not os.path.isfile(pdf_path):
        lines.append("  ⚠️  main.pdf 不存在, 跳过")
        return True, lines
    try:
        import fitz
    except ImportError:
        lines.append("  ⚠️  PyMuPDF 未安装, 跳过")
        return True, lines

    doc = fitz.open(pdf_path)
    refs_page = _find_references_start_page(doc)
    cite_spans = []
    body_sizes = []

    for page_idx in range(min(refs_page - 1, len(doc))):
        page = doc[page_idx]
        d = page.get_text("dict")
        for block in d.get("blocks", []):
            if "lines" not in block:
                continue
            for line in block["lines"]:
                line_max_size = 0
                for span in line["spans"]:
                    line_max_size = max(line_max_size, span["size"])
                for span in line["spans"]:
                    txt = span["text"].strip()
                    if CITE_BRACKET_RE.match(txt):
                        cite_spans.append((page_idx + 1, span["size"], line_max_size, txt))
                if 8 < line_max_size < 16:
                    body_sizes.append(line_max_size)
    doc.close()

    body_size_estimate = sorted(body_sizes)[len(body_sizes) // 2] if body_sizes else 12.0
    lines.append(f"  正文页范围: 1 ~ {refs_page - 1}, body size 估计: {body_size_estimate:.1f}pt")

    if not cite_spans:
        lines.append("  ⚠️  正文未找到 [N] 形式引用 span — 论文可能无引用或全 \\citess 已用")
        return True, lines

    lines.append(f"  共 {len(cite_spans)} 处 [N] 正文引用")
    bad = [(p, s, lm, t) for (p, s, lm, t) in cite_spans if s > lm * 0.85]
    if bad:
        sample = bad[:5]
        suffix = f" (+{len(bad)-5} more)" if len(bad) > 5 else ""
        lines.append(f"  ❌ {len(bad)} 处 [N] 正文引用非上标 (size 应 < line max * 0.85):")
        for p, s, lm, t in sample:
            lines.append(f"     page {p}: '{t}' size={s:.1f} line_max={lm:.1f}")
        lines.append(suffix.strip() or "")
        lines.append("  → 疑似 D27 (\\cite 默认行内, 应 \\renewcommand 包 \\textsuperscript)")
        return False, lines

    lines.append(f"  ✅ {len(cite_spans)} 处 [N] 正文引用全部上标")
    return True, lines


# ============================================================
# Check 7 (Round 7-C): PDF 残留字样扫描
# ============================================================

PDF_ARTIFACT_PATTERNS = [
    ("CLS reminder",      re.compile(r"has exceeded the maximum limit"), True),
    ("Chinese Abstract",  re.compile(r"Chinese Abstract has"), True),
    ("Acknowledgement",   re.compile(r"Acknowledgement has exceeded"), True),
    ("LaTeX 残留",        re.compile(r"\\textsuperscript\{|\\cite\{|\\ref\{"), True),
    ("?? 未收敛",         re.compile(r"\?\?\??"), True),
]


def check_pdf_artifacts(workdir: str) -> Tuple[bool, List[str]]:
    """扫产物 PDF 全文, 检测 CLS reminder / LaTeX 残留命令字面 / ?? 未收敛.

    任一命中 → ❌ (D28 reminder + 通用 LaTeX 渲染异常).
    """
    lines = ["[Check 7] PDF 残留字样 (Round 7-C)"]
    pdf_path = os.path.join(workdir, "main.pdf")
    if not os.path.isfile(pdf_path):
        lines.append("  ⚠️  main.pdf 不存在, 跳过")
        return True, lines
    try:
        import fitz
    except ImportError:
        lines.append("  ⚠️  PyMuPDF 未安装, 跳过")
        return True, lines

    doc = fitz.open(pdf_path)
    full_text = "\n".join(doc[i].get_text() for i in range(len(doc)))
    doc.close()

    passed = True
    for name, pat, is_hard in PDF_ARTIFACT_PATTERNS:
        matches = pat.findall(full_text)
        if not matches:
            continue
        icon = "❌" if is_hard else "⚠️"
        lines.append(f"  {icon} {name}: {len(matches)} 处命中, 样例: {repr(matches[:3])}")
        if is_hard:
            passed = False

    if passed:
        lines.append("  ✅ 无 CLS reminder / LaTeX 残留 / ?? 字样")
    else:
        lines.append("  → D28 (缺 noreminder 选项) / 编译收敛失败 / 自定义宏未渲染")
    return passed, lines


# ============================================================
# Check 8 (D38, CASE-A): figure-order parity
# ============================================================

def _docx_body_image_order(docx_path: str) -> List[str]:
    """Walk docx body paragraphs in order, return image filename sequence.

    复用 recover_figures.parse_docx + build_figure_records, 失败 → 空列表.
    """
    if not docx_path or not os.path.isfile(docx_path):
        return []
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import recover_figures as rf  # type: ignore
        paras, rid_to_filename = rf.parse_docx(docx_path)
        boundaries, body_end = rf.find_chapter_boundaries(paras)
        records = rf.build_figure_records(paras, rid_to_filename, boundaries,
                                          body_end=body_end, include_wmf=False)
        out: List[str] = []
        for r in records:
            for fname in r["image_filenames"]:
                out.append(fname)
        return out
    except Exception:
        return []


def _pdf_includegraphics_order(workdir: str) -> List[str]:
    """Walk chapter/*.tex in alphabetical (ch01.tex, ch02.tex ...) order, return image filenames."""
    chap_dir = os.path.join(workdir, "chapter")
    out: List[str] = []
    if not os.path.isdir(chap_dir):
        return out
    pat = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{(?:media/)?([^}]+)\}")
    for fn in sorted(os.listdir(chap_dir)):
        if not fn.endswith(".tex"):
            continue
        try:
            with open(os.path.join(chap_dir, fn), encoding="utf-8") as f:
                content = f.read()
        except OSError:
            continue
        for m in pat.finditer(content):
            out.append(os.path.basename(m.group(1)))
    return out


def check_figure_order(workdir: str, docx_path: str) -> Tuple[bool, List[str]]:
    """D38 (CASE-A): docx 体内图序 vs PDF \\includegraphics 序应一致."""
    lines = ["[Check 8] 图序一致性 (D38, CASE-A)"]
    if not docx_path:
        lines.append("  ⚠️  --docx 未提供, 跳过")
        return True, lines

    docx_order = _docx_body_image_order(docx_path)
    pdf_order = _pdf_includegraphics_order(workdir)

    if not docx_order:
        lines.append("  ⚠️  无法解析 docx 图序, 跳过")
        return True, lines
    if not pdf_order:
        lines.append("  ⚠️  chapter/*.tex 无 \\includegraphics, 跳过")
        return True, lines

    docx_set = set(docx_order)
    common = [f for f in pdf_order if f in docx_set]
    docx_pos = {f: i for i, f in enumerate(docx_order)}
    pdf_pos_in_common = {f: i for i, f in enumerate(common)}
    expected_order = sorted(common, key=lambda f: docx_pos[f])
    moved = [f for f in common
             if expected_order.index(f) != pdf_pos_in_common[f]]

    lines.append(f"  docx 体内图序: {len(docx_order)} 张")
    lines.append(f"  PDF chapter 图序: {len(pdf_order)} 张 (共有 {len(common)} 张)")
    if not moved:
        lines.append("  ✅ 图序与 docx 一致")
        return True, lines

    lines.append(f"  ❌ {len(moved)} 张图相对位置与 docx 不一致:")
    for f in moved[:10]:
        lines.append(
            f"     {f}: docx#{docx_pos[f]+1} → pdf#{pdf_pos_in_common[f]+1}"
        )
    if len(moved) > 10:
        lines.append(f"     ... +{len(moved)-10} 张更多")
    lines.append("  → D38 (recover_figures placement) / case-private 误编辑")
    return False, lines


# ============================================================
# Check 9 (D39, CASE-A): figure caption parity (textbox-as-caption)
# ============================================================

def check_figure_caption_parity(workdir: str, extracted_dir: str) -> Tuple[bool, List[str]]:
    """D39 (CASE-A): 验证 textbox caption 全部进入 chapter \\caption{}, 无空 caption,
    编号序列连续无缺号/重复 (chapter 内).

    比对:
      - extracted/textbox_captions.json 期望 captions 数 (按 label 去重)
      - chapter/*.tex 中 \\caption{...} 数 + label \\label{fig:X-Y} 序列
    """
    lines = ["[Check 9] figure caption parity (D39, CASE-A)"]
    chap_dir = os.path.join(workdir, "chapter")
    if not os.path.isdir(chap_dir):
        lines.append("  ⚠️  chapter/ 不存在, 跳过")
        return True, lines

    tx_path = os.path.join(extracted_dir, "textbox_captions.json")
    expected_labels: List[str] = []
    if os.path.isfile(tx_path):
        try:
            with open(tx_path, encoding="utf-8") as f:
                tx = json.load(f)
            expected_labels = [t.get("label", "") for t in tx if t.get("label")]
        except Exception:
            pass

    cap_pat = re.compile(r"\\caption\{([^}]*)\}")
    label_pat = re.compile(r"\\label\{fig:(\d+)[\-\.](\d+)\}")
    empty_caps = 0
    label_seq: List[Tuple[int, int]] = []
    for fn in sorted(os.listdir(chap_dir)):
        if not fn.endswith(".tex"):
            continue
        try:
            with open(os.path.join(chap_dir, fn), encoding="utf-8") as f:
                content = f.read()
        except OSError:
            continue
        for m in cap_pat.finditer(content):
            cap_text = m.group(1).strip()
            if not cap_text:
                empty_caps += 1
        for m in label_pat.finditer(content):
            label_seq.append((int(m.group(1)), int(m.group(2))))

    lines.append(f"  textbox_captions.json: {len(expected_labels)} labels")
    lines.append(f"  chapter \\caption{{}}: {len(label_seq)} (含 \\label) / {empty_caps} 空")
    # CASE-A: separate B-class structural failures (textbox missing / numbering
    # gap) from C-class customer content (caption text empty). Empty captions
    # alone — when numbering is otherwise consistent — are a customer-content
    # gap (docx caption paragraph carries only "图X-Y" with no descriptive
    # name). They belong in client_feedback, not P0 hard-fail.
    structural_fail = False
    if expected_labels and len(label_seq) < len(expected_labels):
        lines.append(
            f"  ❌ chapter 含 caption 数 < textbox 期望: {len(label_seq)} < {len(expected_labels)}"
        )
        structural_fail = True
    by_chapter: Dict[int, List[int]] = {}
    for ch, sub in label_seq:
        by_chapter.setdefault(ch, []).append(sub)
    for ch, subs in sorted(by_chapter.items()):
        sorted_subs = sorted(subs)
        expected = list(range(1, len(sorted_subs) + 1))
        if sorted_subs != expected or len(set(subs)) != len(subs):
            lines.append(f"  ❌ ch{ch:02d} 编号序列异常: {sorted_subs} (期望 {expected})")
            structural_fail = True

    if empty_caps:
        if structural_fail:
            lines.append(f"  ❌ {empty_caps} 个 \\caption{{}} 为空")
        else:
            # Customer content gap: advisory only, do not block delivery.
            lines.append(
                f"  ⚠️  {empty_caps} 个 \\caption{{}} 为空 (C 类客户内容缺失, 退回客户填补图名)"
            )

    if structural_fail:
        lines.append("  → D39 (textbox-as-caption / 编号跳号) / case-private 漏修")
        return False, lines
    if empty_caps:
        lines.append("  → 编号正常, 仅 caption 文字空 → advisory 不阻断 (CASE-A policy)")
        return True, lines
    lines.append("  ✅ caption 全非空 + 编号序列连续无重复")
    return True, lines


# ============================================================
# Check 10 (W3 雏形, CASE-A): paragraph parity (warning, 不阻断)
# ============================================================

def check_paragraph_parity(workdir: str, docx_path: str) -> Tuple[bool, List[str]]:
    """W3 Check 10 (CASE-A): docx body 段落是否在 chapter/*.tex 出现.

    用 source_manifest 抽 docx 段, 对 chapter 全文做 substring search (归一化空白
    + 去 LaTeX 命令). 缺失段落很可能是: pandoc 把"图X-Y 给出了..."误识别为
    caption 而 strip / inline 公式段落正文整段被吞 / 子图标签拆解错位.

    本 Check 默认仅 warning 不 hard fail (因第一版 substring 启发式有误报),
    出口列出 missing 段供视觉抽查.
    """
    lines = ["[Check 10] paragraph parity (W3, CASE-A 凝结)"]
    if not docx_path or not os.path.isfile(docx_path):
        lines.append("  ⚠️  --docx 未提供, 跳过")
        return True, lines
    chap_dir = os.path.join(workdir, "chapter")
    if not os.path.isdir(chap_dir):
        lines.append("  ⚠️  chapter/ 不存在, 跳过")
        return True, lines

    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import source_manifest as sm  # type: ignore
        manifest = sm.build_probe_manifest(docx_path)
    except Exception as e:
        lines.append(f"  ⚠️  source_manifest 异常: {e}")
        return True, lines

    paras = manifest.get("paragraphs", [])

    # 归一化 chapter + main.tex + misc/ 全文 (去 LaTeX 命令 + 压缩空白)
    chapter_full = ""
    candidate_dirs = [chap_dir, os.path.join(workdir, "misc")]
    for d in candidate_dirs:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".tex"):
                try:
                    with open(os.path.join(d, fn), encoding="utf-8") as f:
                        chapter_full += f.read() + "\n"
                except OSError:
                    pass
    main_tex = os.path.join(workdir, "main.tex")
    if os.path.isfile(main_tex):
        try:
            with open(main_tex, encoding="utf-8") as f:
                chapter_full += f.read() + "\n"
        except OSError:
            pass

    def _normalize(s: str) -> str:
        # CASE-A: source_manifest 段文本含 OOXML serialize 后的 XML entity (&quot; / &amp; / &lt; / &gt; / &apos;).
        # chapter .tex 是 pandoc 解码后的字面 (含 Chinese curly quotes 等). parity 比较前先 unescape entity,
        # 否则 32 段政策引用全报 false-positive missing.
        s = html.unescape(s)
        s = re.sub(
            r"\\(cite|label|ref|cref|includegraphics|caption|footnote|allowbreak|"
            r"textsuperscript|origcite|usepackage|tag|begin|end|nocite)\s*"
            r"(?:\[[^\]]*\])?\s*\{[^}]*\}",
            "", s,
        )
        s = re.sub(r"\\[a-zA-Z]+\*?", "", s)
        s = re.sub(r"[\$\{\}\\\[\]_^]", "", s)
        s = re.sub(r"\s+", "", s)
        return s

    chapter_norm = _normalize(chapter_full)

    # W3 Check 10 v2 (Codex 节 3): 高置信 P0 / 低置信 warning 分类
    # 排除 cover/toc/abstract/refs zone + caption 段 (Check 9/13 已覆盖)
    missing_high: List[Dict] = []  # 长正文 + 句子型 + 同 chapter 找不到
    missing_low: List[Dict] = []
    skip_zones = {"cover", "toc", "abstract_zh", "abstract_en", "acknowledgement",
                  "references", "foreign_original", "foreign_translation"}
    cap_pat = re.compile(r"图\s*\d+\s*[-－.]\s*\d+")
    for p in paras:
        text = p.get("text", "").strip()
        if len(text) < 20:
            continue
        if p.get("zone_guess") in skip_zones:
            continue
        if cap_pat.match(text):
            continue  # Check 9/13 覆盖
        # W3 v2: 排除 caption_role lookalike (recover_figures 已保留, 不算 missing)
        if p.get("caption_role") == "caption_lookalike_body":
            continue
        text_norm = _normalize(text)
        probe = text_norm[:30] if len(text_norm) >= 30 else text_norm
        if not probe or probe in chapter_norm:
            continue
        # 高置信: 长正文 (≥40) + 句子型 (含句末标点)
        is_sentence = p.get("sentence_like", False) or len(text) >= 40
        entry = {"para_idx": p.get("docx_para_idx"), "preview": text[:60]}
        if is_sentence and len(text) >= 40:
            missing_high.append(entry)
        else:
            missing_low.append(entry)
    missing = missing_high + missing_low  # 兼容下游

    lines.append(f"  docx 段落 (text>=20, non-skip-zone): {sum(1 for p in paras if len(p.get('text','').strip())>=20 and p.get('zone_guess') not in skip_zones)}")
    lines.append(f"  high-confidence missing (P0 candidate): {len(missing_high)}")
    lines.append(f"  low-confidence missing (advisory): {len(missing_low)}")
    if missing_high:
        lines.append("  ⚠️  high-confidence 长正文段在 chapter 缺失 — 大概率 pandoc 吞段 / strip:")
        for m in missing_high[:5]:
            lines.append(f"     para[{m['para_idx']}] {m['preview']!r}")
        if len(missing_high) > 5:
            lines.append(f"     ... +{len(missing_high)-5} 段更多 (共 {len(missing_high)} 高置信)")
        lines.append("  → W3 Check 10 v2 advisory (W4 视统计可升 P0)")
    if missing_low and not missing_high:
        lines.append("  ⚠️  low-confidence missing (短/math-heavy/可能误报):")
        for m in missing_low[:5]:
            lines.append(f"     para[{m['para_idx']}] {m['preview']!r}")
        if len(missing_low) > 5:
            lines.append(f"     ... +{len(missing_low)-5} 段更多")
    if not missing_high and not missing_low:
        lines.append("  ✅ 所有 body docx 段落均在 chapter 出现")

    # advisory 模式 — 不影响 overall (W4 视统计可升 missing_high == 0 hard gate)
    return True, lines


# ============================================================
# Check 13 (W3 D41, CASE-A): caption truth parity
# ============================================================

def check_caption_truth_parity(workdir: str, docx_path: str) -> Tuple[bool, List[str]]:
    """W3 Check 13 (D41 CASE-A): 源 caption 含 inline math 时, 产物 caption 必须保留.

    Codex 节 3 设计: 用 source_manifest 抽 docx caption 段 (含 oMath),
    比 chapter \\caption{} 字面 — 源含 math token 但产物缺 → P0 红灯.

    判定 (Codex 阈值):
    - 源 has_inline_math=true 但产物 caption 无 `$` 字符 → P0
    - 数量 / label parity 已 Check 9 覆盖, 本 check 专注内容真值
    """
    lines = ["[Check 13] caption truth parity (W3 D41, CASE-A)"]
    if not docx_path or not os.path.isfile(docx_path):
        lines.append("  ⚠️  --docx 未提供, 跳过")
        return True, lines
    chap_dir = os.path.join(workdir, "chapter")
    if not os.path.isdir(chap_dir):
        lines.append("  ⚠️  chapter/ 不存在, 跳过")
        return True, lines

    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import source_manifest as sm  # type: ignore
        manifest = sm.build_probe_manifest(docx_path)
    except Exception as e:
        lines.append(f"  ⚠️  source_manifest 异常: {e}")
        return True, lines

    # 收集 docx caption 段含 oMath 的
    cap_pat = re.compile(r"^图\s*\d+\s*[-－.]\s*\d+")
    docx_math_captions: List[Dict] = []
    for p in manifest.get("paragraphs", []):
        text = p.get("text", "").strip()
        if cap_pat.match(text) and (p.get("has_omath") or "$" in text):
            docx_math_captions.append({
                "para_idx": p.get("docx_para_idx"),
                "text": text,
                "has_omath": p.get("has_omath", False),
            })

    if not docx_math_captions:
        lines.append("  ✅ 源 caption 无 inline math, 跳过 truth check")
        return True, lines

    # 收集 chapter caption 字面
    chap_captions: List[str] = []
    cap_re = re.compile(r"\\caption\{([^}]*)\}")
    for fn in sorted(os.listdir(chap_dir)):
        if not fn.endswith(".tex"):
            continue
        try:
            with open(os.path.join(chap_dir, fn), encoding="utf-8") as f:
                content = f.read()
        except OSError:
            continue
        chap_captions.extend(cap_re.findall(content))

    lines.append(f"  docx 含 math 的 caption: {len(docx_math_captions)}")
    lines.append(f"  chapter \\caption{{}}: {len(chap_captions)}")

    # 简化 P0: 源有 N 个 math caption, 产物 caption 含 $ 的应 ≥ N (token 化精确比较 W4)
    chap_math_caps = [c for c in chap_captions if "$" in c]
    lines.append(f"  chapter caption 含 $ (math): {len(chap_math_caps)}")
    passed = True
    if len(chap_math_caps) < len(docx_math_captions):
        miss = len(docx_math_captions) - len(chap_math_caps)
        lines.append(f"  ❌ {miss} 个源 math caption 在产物缺失 (math 内容被吞):")
        for cap in docx_math_captions[:5]:
            lines.append(f"     docx para[{cap['para_idx']}]: {cap['text'][:60]!r}")
        lines.append("  → D41 (caption_inline_math_drop) — pandoc/recover 路径丢 math")
        passed = False
    else:
        lines.append("  ✅ 源 math caption 数 ≤ 产物含 $ caption 数")
    return passed, lines


# ============================================================
# Check 15 (W5 Wave 2, 2026-05-16): 页面内容 bbox/URL 溢出 (advisory)
# ============================================================
#
# 触发: PaperFit (arXiv:2605.10341) VTO 评估借鉴 + CASE-A leak (audit 全绿但
# 客户视觉抽查发现版心溢出). 检查 PDF 每页 text/image block 是否越过 A4 30mm
# 边距, 命中输出页码+bbox+文本片段. 不阻断, 仅 advisory.
#
# UESTC spec §1.3: A4 (21x29.7cm), 上下左右各 30mm 边距.

# A4 page size in PDF points (1 mm = 2.83465 pt)
A4_WIDTH_PT = 595.276    # 21 cm
A4_HEIGHT_PT = 841.890   # 29.7 cm
MARGIN_30MM_PT = 30 * 2.83465  # ~85 pt
TOLERANCE_PT = 2 * 2.83465  # 2mm 容差, 避免假阳性


def _content_bbox_for_page(page_width: float, page_height: float) -> Tuple[float, float, float, float]:
    """Compute (x_min, y_min, x_max, y_max) of content area = page minus 30mm margin."""
    return (
        MARGIN_30MM_PT - TOLERANCE_PT,
        MARGIN_30MM_PT - TOLERANCE_PT,
        page_width - MARGIN_30MM_PT + TOLERANCE_PT,
        page_height - MARGIN_30MM_PT + TOLERANCE_PT,
    )


def _overflow_kind(bx0: float, by0: float, bx1: float, by1: float,
                   cx0: float, cy0: float, cx1: float, cy1: float) -> str:
    """Return overflow direction(s) as string like 'right' / 'right+bottom' / ''."""
    sides = []
    if bx0 < cx0:
        sides.append("left")
    if bx1 > cx1:
        sides.append("right")
    if by0 < cy0:
        sides.append("top")
    if by1 > cy1:
        sides.append("bottom")
    return "+".join(sides)


def check_page_bbox_overflow(workdir: str) -> Tuple[bool, List[str]]:
    """Check 15 (W5, advisory): scan PDF for text/image blocks crossing 30mm margin.

    Reports page#, bbox, overflow direction, text snippet for each hit.
    Always returns True (advisory only, not in hard gate).
    """
    lines = ["[Check 15] 页面内容 bbox/URL 溢出 (W5 Wave 2, advisory, 不阻断)"]
    pdf_path = os.path.join(workdir, "main.pdf")
    if not os.path.isfile(pdf_path):
        lines.append("  ⚠️  main.pdf 不存在, 跳过")
        return True, lines

    try:
        import fitz  # PyMuPDF
    except ImportError:
        lines.append("  ⚠️  PyMuPDF (fitz) 未安装, 跳过")
        return True, lines

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        lines.append(f"  ⚠️  无法打开 PDF: {exc}")
        return True, lines

    hits = []
    total_pages = len(doc)
    try:
        for page_num, page in enumerate(doc, start=1):
            pw, ph = page.rect.width, page.rect.height
            cx0, cy0, cx1, cy1 = _content_bbox_for_page(pw, ph)
            # Text blocks
            for block in page.get_text("blocks"):
                if len(block) < 7:
                    continue
                bx0, by0, bx1, by1, text, _bno, _btype = block[:7]
                if _btype != 0:  # 0 = text, 1 = image (handled below)
                    continue
                kind = _overflow_kind(bx0, by0, bx1, by1, cx0, cy0, cx1, cy1)
                if kind:
                    snippet = (text or "").strip().replace("\n", " ")[:80]
                    hits.append((page_num, "text", kind, (bx0, by0, bx1, by1), snippet))
            # Image blocks
            for img in page.get_images(full=True):
                xref = img[0]
                try:
                    rects = page.get_image_rects(xref)
                except Exception:
                    rects = []
                for rect in rects:
                    bx0, by0, bx1, by1 = rect.x0, rect.y0, rect.x1, rect.y1
                    kind = _overflow_kind(bx0, by0, bx1, by1, cx0, cy0, cx1, cy1)
                    if kind:
                        hits.append((page_num, "image", kind, (bx0, by0, bx1, by1), f"xref={xref}"))
    finally:
        doc.close()

    if not hits:
        lines.append(f"  ✅ 全部 {total_pages} 页内容均在 30mm 边距内 (容差 2mm)")
        return True, lines

    # Group by overflow direction for readable summary
    by_kind: Dict[str, int] = {}
    for _, _, k, _, _ in hits:
        by_kind[k] = by_kind.get(k, 0) + 1
    lines.append(f"  ⚠️  {len(hits)} block 越过版心 (across {total_pages} 页):")
    for k, c in sorted(by_kind.items(), key=lambda x: -x[1]):
        lines.append(f"      - {k}: {c} block")
    # Show top 10 hits
    lines.append("  Top hits (页/类型/方向/bbox/片段):")
    for h in hits[:10]:
        page_num, btype, kind, (bx0, by0, bx1, by1), snippet = h
        lines.append(
            f"    p{page_num} {btype:5s} {kind:15s} "
            f"({bx0:.0f},{by0:.0f},{bx1:.0f},{by1:.0f})  {snippet!r}"
        )
    if len(hits) > 10:
        lines.append(f"    ... 还有 {len(hits) - 10} 项")
    lines.append("  (advisory: URL 长串 / 表格越界 / 图过宽 等场景, 人工 review)")
    return True, lines


# ============================================================
# Check 14 (W4, CASE-A/015/016 三角): subfigure parity
# ============================================================

def _refs_max_parity_compute(refs_raw: str, bib_text: str, cite_map: dict) -> dict:
    """W4 Check 11 核心算法 (testable, 不依赖文件系统).

    Args:
        refs_raw: references_raw.txt 内容.
        bib_text: ref.bib 内容.
        cite_map: cite_map.json 解析后的 dict.

    Returns:
        dict with keys:
          - n_raw_type_markers: refs_raw 中 [M]/[J]/[D]/[C]/[N]/[R]/[P]/[S]/[Z]/[EB] 类型标记数 (即客户期望条目数)
          - n_bib_entries: ref.bib 中 @<type>{...} entry 数
          - n_cite_map: cite_map 大小
          - cite_map_max: cite_map 最大序号 (1-based)
          - mismatches: list of (kind, lhs_label, rhs_label, lhs_n, rhs_n) — 三方 parity 不一致的对
    """
    type_marker_re = re.compile(r"\[(?:M|J|D|C|N|R|P|S|Z|EB|EB/OL|J/OL|M/OL|DB/OL)\]")
    entry_re = re.compile(r"^@\w+\s*\{", re.MULTILINE)

    n_raw = len(type_marker_re.findall(refs_raw))
    n_bib = len(entry_re.findall(bib_text))
    n_cm = len(cite_map)
    cm_max = max((int(k) for k in cite_map.keys() if str(k).isdigit()), default=0)

    mismatches = []
    if n_raw and n_bib and n_raw != n_bib:
        mismatches.append(("raw_vs_bib", "refs_raw [type] markers", "ref.bib @entries", n_raw, n_bib))
    if n_bib and n_cm and n_bib != n_cm:
        mismatches.append(("bib_vs_cite_map", "ref.bib @entries", "cite_map size", n_bib, n_cm))
    if n_cm and cm_max and n_cm != cm_max:
        mismatches.append(("cite_map_max_vs_size", "cite_map size", "cite_map max idx", n_cm, cm_max))

    return {
        "n_raw_type_markers": n_raw,
        "n_bib_entries": n_bib,
        "n_cite_map": n_cm,
        "cite_map_max": cm_max,
        "mismatches": mismatches,
    }


def check_refs_max_parity(workdir: str, extracted_dir: str) -> Tuple[bool, List[str]]:
    """W4 Check 11: refs 三方数量 parity (references_raw 类型标记 / ref.bib @entry / cite_map).

    比 Check 5 (bbl vs cite_map) 更靠源头: refs_to_bib 漏 parse 某条 (D23 类格式异常)
    会让 cite_map / ref.bib 同步少 1, Check 5 数量自洽看不出, 但 raw [type] markers vs
    ref.bib @entries 能直接发现.

    advisory 起手 (不阻断), 客户原稿空 refs / 标记缺失场景下 trivial pass.
    """
    lines = ["[Check 11] refs max-number parity (W4, CASE-A/019 凝结)"]
    raw_path = os.path.join(extracted_dir, "references_raw.txt")
    bib_path = os.path.join(workdir, "ref.bib")
    cm_path = os.path.join(extracted_dir, "cite_map.json")

    if not os.path.isfile(raw_path):
        lines.append("  ⚠️  references_raw.txt 不存在, 跳过")
        return True, lines
    if not os.path.isfile(bib_path):
        lines.append("  ⚠️  ref.bib 不存在 (可能空 refs profile), 跳过")
        return True, lines
    if not os.path.isfile(cm_path):
        lines.append("  ⚠️  cite_map.json 不存在, 跳过")
        return True, lines

    try:
        with open(raw_path, encoding="utf-8") as f:
            refs_raw = f.read()
        with open(bib_path, encoding="utf-8") as f:
            bib_text = f.read()
        with open(cm_path, encoding="utf-8") as f:
            cite_map = json.load(f)
    except (OSError, ValueError) as e:
        lines.append(f"  ⚠️  读取异常: {e}")
        return True, lines

    result = _refs_max_parity_compute(refs_raw, bib_text, cite_map)

    lines.append(f"  refs_raw [type] markers: {result['n_raw_type_markers']}")
    lines.append(f"  ref.bib @entries:        {result['n_bib_entries']}")
    lines.append(f"  cite_map size / max:     {result['n_cite_map']} / {result['cite_map_max']}")

    if not result["mismatches"]:
        lines.append("  ✅ 三方数量 parity 一致")
        return True, lines

    lines.append(f"  ⚠️  {len(result['mismatches'])} 项 parity 不一致 (advisory):")
    for kind, lhs_label, rhs_label, lhs_n, rhs_n in result["mismatches"]:
        lines.append(f"     [{kind}] {lhs_label}={lhs_n} vs {rhs_label}={rhs_n}")
    lines.append("  → W4 advisory: refs_to_bib 可能漏 parse (检查 unsupported [type]) 或 cite_map 编号不连续")
    return True, lines  # advisory, 不阻断


def _subfigure_parity_from_manifest(manifest: dict, chap_refs: Set[str]) -> dict:
    """W4 Check 14 核心算法 (testable, 不依赖 docx 路径).

    Args:
        manifest: source_manifest dict (含 figures[]).
        chap_refs: set of basenames in chapter \\includegraphics.

    Returns:
        dict with keys:
          - n_src_figs_with_image: 源 figures 含 image 总组数
          - n_multi_image_figs: 多 image (subfigure 组) 数
          - total_src_imgs: 源子图总数 (排除 ALLOWED_UNREFERENCED)
          - missing_in_chap: [(fig_id, basename), ...] 子图被 chapter 漏引用
    """
    figures = manifest.get("figures", []) or []
    multi_image_figs = []
    missing_in_chap = []
    total_src_imgs = 0
    n_src_figs_with_image = 0
    for fig in figures:
        names = fig.get("image_filenames") or []
        bases = [os.path.basename(n) for n in names if n]
        bases = [b for b in bases if b not in ALLOWED_UNREFERENCED]
        if not bases:
            continue
        n_src_figs_with_image += 1
        total_src_imgs += len(bases)
        if len(bases) >= 2:
            multi_image_figs.append({"id": fig.get("id"), "images": bases})
            for b in bases:
                if b not in chap_refs:
                    missing_in_chap.append((fig.get("id"), b))
    return {
        "n_src_figs_with_image": n_src_figs_with_image,
        "n_multi_image_figs": len(multi_image_figs),
        "total_src_imgs": total_src_imgs,
        "missing_in_chap": missing_in_chap,
    }


def check_subfigure_parity(workdir: str, docx_path: str) -> Tuple[bool, List[str]]:
    """W4 Check 14: docx figures 含多 image (subfigure 组) 应在 chapter 全部 \\includegraphics 引用.

    背景: CASE-A/015/016 三角触发. 客户原稿 docx 一个 paragraph 含 N 张 inline image (作子图),
    pandoc 或 recover_figures 只抓第一张, 后续 N-1 张丢失. 用户视觉抽查发现"子图 (a)(b)(c) 拆解只剩 (a)".

    advisory 起手 (不阻断), 等数据确认再升 P0 hard. ALLOWED_UNREFERENCED (校徽等) 不计.
    核心算法在 `_subfigure_parity_from_manifest`, 单元测试覆盖.
    """
    lines = ["[Check 14] subfigure parity (W4 三角, CASE-A/015/016)"]
    if not docx_path or not os.path.isfile(docx_path):
        lines.append("  ⚠️  --docx 未提供, 跳过")
        return True, lines
    chap_dir = os.path.join(workdir, "chapter")
    if not os.path.isdir(chap_dir):
        lines.append("  ⚠️  chapter/ 不存在, 跳过")
        return True, lines

    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import source_manifest as sm  # type: ignore
        manifest = sm.build_probe_manifest(docx_path)
    except Exception as e:
        lines.append(f"  ⚠️  source_manifest 异常: {e}")
        return True, lines

    chap_refs = collect_includegraphics_refs(workdir)
    result = _subfigure_parity_from_manifest(manifest, chap_refs)

    lines.append(f"  source figures (含 image): {result['n_src_figs_with_image']} 组, 总子图: {result['total_src_imgs']}")
    lines.append(f"  其中多 image (subfigure 组): {result['n_multi_image_figs']}")
    lines.append(f"  chapter \\includegraphics 引用: {len(chap_refs)} 张")

    if result["n_multi_image_figs"] == 0:
        lines.append("  ✅ 源无子图组, 跳过")
        return True, lines

    missing = result["missing_in_chap"]
    if not missing:
        lines.append("  ✅ 所有 subfigure 子图都在 chapter 引用")
        return True, lines

    lines.append(f"  ⚠️  {len(missing)} 张 subfigure 子图未被 chapter \\includegraphics 引用 (大概率被 pandoc/recover_figures 吞):")
    for fig_id, base in missing[:8]:
        lines.append(f"     fig {fig_id}: {base!r}")
    if len(missing) > 8:
        lines.append(f"     ... +{len(missing)-8} 张更多")
    lines.append("  → W4 advisory (D21 case_private, recover_figures 子图拆解 W4 主体待做)")
    return True, lines  # advisory, 不阻断


# ============================================================
# Check 12 (W3, CASE-A/016): equation layout sentinel
# ============================================================

def check_equation_layout(workdir: str) -> Tuple[bool, List[str]]:
    """W3 Check 12: 检测 chapter 中 inline `$math$ + (X-Y)` 残留.

    case14 + case16 反复触发: 客户 docx 用伪公式 (inline `$...$` + 半/全角编号)
    替代 \\begin{equation}, 产物左对齐不居中 + 编号无右端 tag, 视觉违 spec.
    应转为 \\begin{equation} ... \\tag{X-Y}.
    """
    lines = ["[Check 12] equation layout sentinel (W3, CASE-A/016)"]
    chap_dir = os.path.join(workdir, "chapter")
    if not os.path.isdir(chap_dir):
        lines.append("  ⚠️  chapter/ 不存在, 跳过")
        return True, lines

    # 半角 (X-Y) 或 全角 （X-Y）, 整行只有 $math$ + 编号
    pat = re.compile(
        r"^[\s 　]*\$[^\$\n]+\$[\s 　]*[（(]\d+[-－.]\d+[）)][\s 　]*$",
        re.MULTILINE,
    )
    hits: List[Tuple[str, str]] = []
    for fn in sorted(os.listdir(chap_dir)):
        if not fn.endswith(".tex"):
            continue
        try:
            with open(os.path.join(chap_dir, fn), encoding="utf-8") as f:
                content = f.read()
        except OSError:
            continue
        for m in pat.finditer(content):
            sample = m.group(0).strip()
            hits.append((fn, sample[:80]))

    if not hits:
        lines.append("  ✅ 无 inline `$math$ (X-Y)` 残留")
        return True, lines

    lines.append(f"  ❌ {len(hits)} 处 inline 公式残留 (应转 \\begin{{equation}}\\tag):")
    for fn, sample in hits[:8]:
        lines.append(f"     {fn}: {sample!r}")
    if len(hits) > 8:
        lines.append(f"     ... +{len(hits)-8} 处更多")
    lines.append("  → candidate inline_math_to_equation (case14/15/16 反复命中, 待升 shared)")
    return False, lines


# ============================================================
# Main
# ============================================================

def _infer_extracted_dir(workdir: str) -> str:
    """workdir=`.../output_<id>/DissertationUESTC/` → extracted=`.../output_<id>/extracted/`"""
    parent = os.path.dirname(os.path.abspath(workdir))
    return os.path.join(parent, "extracted")


def run_product_audit(workdir: str, docx_path: str = "", extracted_dir: str = "") -> Tuple[bool, str]:
    """跑全部 7 项 check, 返回 (overall_passed, full_report_str).

    overall_passed = Check1 ∧ Check2 ∧ Check4 ∧ Check5 ∧ Check6 ∧ Check7 (Check3 仅 warn 不参与)
    """
    if not extracted_dir:
        extracted_dir = _infer_extracted_dir(workdir)

    sections = []
    sections.append("=" * 60)
    sections.append("product_audit.py — 产物审计 (Step 6c)")
    sections.append("=" * 60)

    p1, lines1 = check_media_integrity(workdir, docx_path)
    sections.extend(lines1); sections.append("")

    p2, lines2 = check_latex_log(workdir)
    sections.extend(lines2); sections.append("")

    _, lines3 = check_placeholders(workdir)
    sections.extend(lines3); sections.append("")

    p4, lines4 = check_abstract_parity(workdir, extracted_dir)
    sections.extend(lines4); sections.append("")

    p5, lines5 = check_bbl_order(workdir, extracted_dir)
    sections.extend(lines5); sections.append("")

    p6, lines6 = check_cite_superscript(workdir)
    sections.extend(lines6); sections.append("")

    p7, lines7 = check_pdf_artifacts(workdir)
    sections.extend(lines7); sections.append("")

    p8, lines8 = check_figure_order(workdir, docx_path)
    sections.extend(lines8); sections.append("")

    p9, lines9 = check_figure_caption_parity(workdir, extracted_dir)
    sections.extend(lines9); sections.append("")

    _, lines10 = check_paragraph_parity(workdir, docx_path)
    sections.extend(lines10); sections.append("")

    p12, lines12 = check_equation_layout(workdir)
    sections.extend(lines12); sections.append("")

    p13, lines13 = check_caption_truth_parity(workdir, docx_path)
    sections.extend(lines13); sections.append("")

    # Check 11 (W4, advisory) — refs 三方数量 parity, 早于 bbl 的源头检查
    _, lines11 = check_refs_max_parity(workdir, extracted_dir)
    sections.extend(lines11); sections.append("")

    # Check 14 (W4 三角, advisory) — 不进 overall hard gate, 仅 warn
    _, lines14 = check_subfigure_parity(workdir, docx_path)
    sections.extend(lines14); sections.append("")

    # Check 15 (W5 Wave 2, advisory) — 版心溢出 (PaperFit 借鉴)
    _, lines15 = check_page_bbox_overflow(workdir)
    sections.extend(lines15); sections.append("")

    overall = p1 and p2 and p4 and p5 and p6 and p7 and p8 and p9 and p12 and p13
    sections.append("-" * 60)
    if overall:
        sections.append("✅ 产物审计通过 (Check 1+2+4-9+12+13 全绿, Check 3+10+11+14+15 仅 warn)")
    else:
        red = []
        for name, ok in [("1", p1), ("2", p2), ("4", p4), ("5", p5),
                         ("6", p6), ("7", p7), ("8", p8), ("9", p9),
                         ("12", p12), ("13", p13)]:
            if not ok:
                red.append(name)
        sections.append(f"⛔ 产物审计未通过 — Check {','.join(red)} 红灯, 交付已阻断")
        sections.append("   使用 --skip-product-audit 跳过 (不推荐)")
    sections.append("=" * 60)

    return overall, "\n".join(sections)


def main():
    ap = argparse.ArgumentParser(description="产物审计器 (Step 6c)")
    ap.add_argument("--workdir", required=True, help="DissertationUESTC 目录")
    ap.add_argument("--docx", default="", help="原始 docx 路径 (可选, 用于 sanity 对照)")
    ap.add_argument("--extracted", default="", help="extracted dir (默认从 workdir 父目录推测)")
    args = ap.parse_args()

    if not os.path.isdir(args.workdir):
        print(f"❌ workdir 不存在: {args.workdir}", file=sys.stderr)
        sys.exit(1)

    overall, report = run_product_audit(args.workdir, args.docx, args.extracted)
    print(report)
    sys.exit(0 if overall else 1)


if __name__ == "__main__":
    main()
