"""recover_figures.py — Word docx → LaTeX figure block recovery

Walks word/document.xml in-order to map every <w:drawing> to:
  (chapter_index, image_filename, caption_text_or_None)

Then injects \\begin{figure}[H]...\\end{figure} blocks into the corresponding
chapters/*.tex files at the location of the body text that references "图X.Y".

Pipeline integration:
    python recover_figures.py \\
        --docx <input.docx> \\
        --extracted <output_dir>/extracted \\
        --chapters <output_dir>/DissertationUESTC/chapter \\
        --media-dir <output_dir>/DissertationUESTC/media

Returns nonzero exit code on critical failures; warnings for unmatched figures.

Why this exists: pandoc's docx reader emits all images as inline `Image` AST nodes
(zero `Figure` blocks), so `pandoc_ast_extract.handle_figure_block()` never
fires. This recovery walker bypasses pandoc and reads the OOXML directly.
"""
import argparse
import json
import os
import re
import shutil
import sys
import zipfile
from collections import defaultdict
from typing import Optional

# ---------------------------------------------------------------------------
# OOXML namespaces (kept as plain strings so we can use simple regex)
# ---------------------------------------------------------------------------
NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

CAPTION_PAT = re.compile(r"^\s*图\s*(\d+)\s*[.\-－]\s*(\d+)\s*[　\s]*(.*)$")
REF_PAT_TMPL = r"图\s*{ch}\s*[.\-－]\s*{n}"


_OMATH_T_PAT = re.compile(r"<m:t[^>]*>([^<]*)</m:t>")
_TEXT_OR_OMATH_PAT = re.compile(
    r"<w:t[^>]*>([^<]*)</w:t>|<m:oMath\b[^>]*>(.*?)</m:oMath>",
    re.DOTALL,
)


def _text_of_paragraph(p_xml: str) -> str:
    """W3 D41: 按 XML 顺序混合 <w:t> 文本 + <m:oMath> 公式 (粗糙 LaTeX 化).

    pandoc 不解析 <m:oMath>, recover_figures 之前只抓 <w:t> 致 caption 含数学的
    docx (CASE-A fig 3-4 `|Δτ_m|`) 公式部分丢失. 简化策略: 抓 oMath
    内 <m:t> 文字 join, 包 $...$ (子上标等结构丢失, 但视觉上保留可读性, 优于完全空).
    """
    out: List[str] = []
    for m in _TEXT_OR_OMATH_PAT.finditer(p_xml):
        if m.group(1) is not None:
            out.append(m.group(1))
        else:
            omath_xml = m.group(2) or ""
            m_texts = _OMATH_T_PAT.findall(omath_xml)
            if m_texts:
                out.append("$" + "".join(m_texts) + "$")
    return "".join(out)


def _drawing_rids(p_xml: str) -> list:
    return re.findall(r'<a:blip[^>]+r:embed="(rId\d+)"', p_xml)


# CASE-A: customer-typed caption labels sometimes have whitespace inside
# the number run, e.g. "图4-1 0" / "图4-1 2 (a)" / "图4 - 9". CAPTION_PAT's
# `(\d+)` then captures only the first digit and the remainder leaks into
# the title — chapter 10/11/12 get parsed as 4-1 with description "0", which
# build_figure_records then dedupes against the real 图4-1. Normalize digit
# whitespace at parse time so every downstream caption/ref regex sees clean
# numbers.
_CAPTION_DIGIT_NORM = re.compile(r"图\s*(\d[\s\d]*[.\-－][\s\d]*\d)")


def _normalize_caption_digits(text: str) -> str:
    return _CAPTION_DIGIT_NORM.sub(
        lambda m: "图" + re.sub(r"\s+", "", m.group(1)), text)


def parse_docx(docx_path: str):
    """Return (paragraphs, rid_to_filename).

    paragraphs: list of dicts {idx, text, rids}
    rid_to_filename: rId -> "imageN.ext" (basename only)
    """
    with zipfile.ZipFile(docx_path) as z:
        doc = z.read("word/document.xml").decode("utf-8", errors="replace")
        rels = z.read("word/_rels/document.xml.rels").decode("utf-8", errors="replace")

    rid_to_target = dict(re.findall(
        r'<Relationship Id="(rId\d+)"[^>]+Target="([^"]+)"', rels))
    rid_to_filename = {rid: os.path.basename(t) for rid, t in rid_to_target.items()
                       if "/media/" in t or t.startswith("media/")}

    paras = []
    for i, raw in enumerate(re.split(r"(?=<w:p[ >])", doc)[1:]):
        paras.append({
            "idx": i,
            "text": _normalize_caption_digits(_text_of_paragraph(raw)),
            "rids": _drawing_rids(raw),
        })
    return paras, rid_to_filename


def load_outline_anchors(outline_path: str) -> Optional[list]:
    """Parse outline.json and extract authoritative chapter anchors.

    Returns sorted [(chapter_num, docx_para_idx), ...] or None if outline
    lacks docx_para_idx fields (i.e. produced by an old extractor that
    didn't carry para anchors). Caller should fall back to regex detection.
    """
    try:
        with open(outline_path, "r", encoding="utf-8") as f:
            outline = json.load(f)
    except Exception:
        return None
    anchors = []
    for ch in outline.get("chapters", []):
        docx_idx = ch.get("docx_para_idx")
        if docx_idx is None:
            return None
        m = re.match(r"ch(\d+)\.tex", ch.get("filename", ""))
        if not m:
            return None
        anchors.append((int(m.group(1)), int(docx_idx)))
    return sorted(anchors, key=lambda x: x[1]) if anchors else None


def find_chapter_boundaries(paras: list) -> tuple:
    """Return (boundaries, body_end_idx).

    boundaries: list of (chapter_num, first_para_idx) for body chapters
    body_end_idx: paragraph index where body content ends (start of 致谢/参考文献/etc),
                  or None if not detected.

    TOC entries are rejected by requiring the chapter title NOT end with digits
    (TOC lines like "第二章 定位算法基础理论2" — trailing page number).
    """
    boundaries = []
    cn_num_to_int = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                     "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    chapter_pat = re.compile(r"^第([一二三四五六七八九十]+)章[\s 　]+(\S.*?)$")
    post_body_pat = re.compile(
        r"^(致[\s 　]*谢|参考文献|外文资料原文|外文资料译文|攻读[^\s]*成果|附录\s*[A-Z]?)\s*\d*\s*$")

    seen = set()
    post_candidates = []
    for p in paras:
        text = p["text"].strip()
        m = chapter_pat.match(text)
        if m:
            num = cn_num_to_int.get(m.group(1))
            if num is None or num in seen:
                continue
            tail = m.group(2).strip()
            # Reject TOC entries: title ending with a page number (digits at end)
            if re.search(r"\d+\s*$", tail):
                continue
            # Reject TOC entries: title containing tabs / repeated whitespace runs (TOC layout)
            if re.search(r"[\t]{2,}|[ ]{4,}", text):
                continue
            seen.add(num)
            boundaries.append((num, p["idx"]))
            continue

        if post_body_pat.match(text):
            post_candidates.append(p["idx"])

    boundaries = sorted(boundaries, key=lambda x: x[1])
    last_chap_idx = boundaries[-1][1] if boundaries else 0
    # Only post-body markers AFTER the last chapter qualify as body_end
    body_end = next((i for i in post_candidates if i > last_chap_idx), None)
    return boundaries, body_end


def chapter_for_para(para_idx: int, boundaries: list,
                     body_end: Optional[int] = None) -> Optional[int]:
    if body_end is not None and para_idx >= body_end:
        return None
    chap = None
    for num, idx in boundaries:
        if para_idx >= idx:
            chap = num
        else:
            break
    return chap


def build_figure_records(paras: list, rid_to_filename: dict, boundaries: list,
                         body_end: Optional[int] = None,
                         include_wmf: bool = False) -> list:
    """Walk paragraphs and pair each <w:drawing> with the next caption-looking para.

    Returns: list of dicts:
        {drawing_para, image_filenames, caption_para, caption_text,
         caption_chapter, caption_subnum, chapter}
    """
    records = []
    last_drawing = None
    for p in paras:
        cap_match = CAPTION_PAT.match(p["text"].strip())

        if p["rids"]:
            # Drawing in this paragraph (with or without caption text in same para).
            files = []
            for rid in p["rids"]:
                f = rid_to_filename.get(rid)
                if not f:
                    continue
                ext = f.rsplit(".", 1)[-1].lower()
                if ext == "wmf" and not include_wmf:
                    continue
                files.append(f)
            if files:
                rec = {
                    "drawing_para": p["idx"],
                    "image_filenames": files,
                    "caption_para": None,
                    "caption_text": None,
                    "caption_chapter": None,
                    "caption_subnum": None,
                    "chapter": chapter_for_para(p["idx"], boundaries, body_end),
                }
                records.append(rec)
                if cap_match:
                    # CASE-A: same-paragraph drawing+caption belong together.
                    # Old code paired the caption to last_drawing (the *previous*
                    # drawing), causing cover images / orphan drawings to steal
                    # the next chapter's first caption and shift the entire
                    # figure sequence by one. Pair caption to THIS drawing.
                    rec["caption_para"] = p["idx"]
                    rec["caption_text"] = cap_match.group(3).strip()
                    rec["caption_chapter"] = int(cap_match.group(1))
                    rec["caption_subnum"] = int(cap_match.group(2))
                    last_drawing = None
                else:
                    last_drawing = rec
        elif cap_match and last_drawing is not None:
            # Caption-only paragraph: attach to the most recent unpaired drawing.
            last_drawing["caption_para"] = p["idx"]
            last_drawing["caption_text"] = cap_match.group(3).strip()
            last_drawing["caption_chapter"] = int(cap_match.group(1))
            last_drawing["caption_subnum"] = int(cap_match.group(2))
            last_drawing = None
    return _merge_subfigure_records(records)


def _merge_subfigure_records(records: list) -> list:
    """CASE-A: docx 图4-12 (a)(b)(c) lays out as 3 separate paragraphs each
    with one image + caption '图4-12 (X)'. CAPTION_PAT captures (chapter=4,
    sub=12) three times, but inject_into_chapter's by_label dict can only hold
    one record per (ch, sub) key, dropping (b)/(c) silently. Merge same-key
    records: concatenate image_filenames so render_figure_block emits a
    multi-image side-by-side block (already supported)."""
    by_key = {}
    out = []
    for r in records:
        key = (r.get("caption_chapter"), r.get("caption_subnum"))
        if key[0] is not None and key[1] is not None and key in by_key:
            host = by_key[key]
            for fname in r["image_filenames"]:
                if fname not in host["image_filenames"]:
                    host["image_filenames"].append(fname)
            # CASE-A round 3: customer fills sub-caption per record
            # ("(a) 戒指误检图（反光）", "(b) 戒指误检图（包装）", ...). Old code
            # kept only host's first caption — (b)(c) text dropped, lun51 sees
            # only "(a)" labeled. Merge sub-captions into host with "; " join.
            sub_cap = (r.get("caption_text") or "").strip()
            host_cap = (host.get("caption_text") or "").strip()
            if sub_cap and sub_cap not in host_cap:
                host["caption_text"] = (
                    f"{host_cap}; {sub_cap}" if host_cap else sub_cap
                )
            continue
        by_key[key] = r
        out.append(r)
    return out


def merge_textbox_captions(records: list, textbox_caps_path: str) -> int:
    """D39: 给缺 caption_text 的 record 用 extracted/textbox_captions.json 补 caption.

    前提: pandoc_ast_extract 的 collect_textbox_captions 已生成 json. 每条目
    带 label "图X-Y" + caption 字面. 按 chapter 分桶后, 用 docx 中 textbox 顺序
    依次填给该 chapter 内缺 caption 的 record.

    返回: 成功补 caption 的 record 数.
    """
    if not os.path.exists(textbox_caps_path):
        return 0
    try:
        with open(textbox_caps_path, "r", encoding="utf-8") as f:
            tx_caps = json.load(f)
    except Exception:
        return 0
    if not tx_caps:
        return 0

    label_pat = re.compile(r"^图(\d+)-(\d+)$")
    by_label = {}
    for tc in tx_caps:
        m = label_pat.match(tc.get("label", ""))
        if not m:
            continue
        by_label[(int(m.group(1)), int(m.group(2)))] = tc.get("caption", "")

    if not by_label:
        return 0

    by_chapter_queue = defaultdict(list)
    for (ch, sub), cap in sorted(by_label.items()):
        by_chapter_queue[ch].append((sub, cap))

    filled = 0
    for rec in records:
        if rec.get("caption_text"):
            continue
        ch = rec.get("chapter")
        if ch is None or not by_chapter_queue[ch]:
            continue
        sub, full_cap = by_chapter_queue[ch].pop(0)
        cap_match = re.match(r"^图\s*\d+\s*[-－.]\s*\d+\s*(.*)$", full_cap)
        cap_title = cap_match.group(1).strip() if cap_match else full_cap
        rec["caption_text"] = cap_title
        rec["caption_chapter"] = ch
        rec["caption_subnum"] = sub
        filled += 1
    return filled


def render_figure_block(image_filenames: list, caption: str, label: str,
                        width: float = 0.7) -> str:
    if len(image_filenames) == 1:
        body = (f"\\includegraphics[width={width}\\textwidth]"
                f"{{media/{image_filenames[0]}}}")
    else:
        # Side-by-side via subfloat (requires \\usepackage{subcaption})
        per = max(0.3, min(0.9 / len(image_filenames), 0.45))
        parts = [f"\\includegraphics[width={per}\\textwidth]{{media/{f}}}"
                 for f in image_filenames]
        body = "\\hfill\n        ".join(parts)
    cap_safe = caption.replace("{", "\\{").replace("}", "\\}")
    return (
        "\\begin{figure}[H]\n"
        "    \\centering\n"
        f"    {body}\n"
        f"    \\caption{{{cap_safe}}}\n"
        f"    \\label{{fig:{label}}}\n"
        "\\end{figure}\n"
    )


def inject_into_chapter(chapter_path: str, records_for_chapter: list,
                        report: dict) -> int:
    """Inject figure blocks into the .tex file at their *body* positions.

    D38 (CASE-A): 旧策略 strip 所有 caption-only 行 + 用 inline ref 重定位 →
    丢失位置信息. 当原稿无 inline ref 时, 图按 record 顺序往下追加, 但已 matched
    的 record 反而插到错位 (image10/11 跑到 image2 前) 致 PDF 图序乱.

    新策略: caption-only 段落本身就是图的"位置锚"; 在原位用 figure block 替换,
    完整保留 docx 体内顺序. 仅 caption-only 行不存在的 record 才走 fallback
    (inline ref → append at end), 且按 caption_subnum 排序保证 order.

    Returns: number of figures injected.
    """
    with open(chapter_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # W3 D42: caption-only line classifier 三分类
    # 旧 cap_only_re 只要看见 "图X-Y" 开头就当 caption-only anchor 全 strip,
    # 致 case16 "图3-4 给出了..." 解说正文段被误删. 拆 LABEL_RE + classify.
    LABEL_RE = re.compile(r"^\s*图\s*(\d+)\s*[.\-－]\s*(\d+)\s*(?P<tail>.*)$")
    LOOKALIKE_KEYWORDS = ("给出", "展示", "表明", "说明", "可以看出", "如图")
    SENTENCE_END_RE = re.compile(r"[。；;！？!?]")

    def classify_figure_line(tail: str) -> str:
        """Return: caption_anchor | caption_lookalike_body."""
        tail = tail.strip()
        if len(tail) > 60:
            return "caption_lookalike_body"
        if any(kw in tail for kw in LOOKALIKE_KEYWORDS) and len(tail) > 25:
            return "caption_lookalike_body"
        if SENTENCE_END_RE.search(tail):
            return "caption_lookalike_body"
        return "caption_anchor"

    # CASE-A fix (2026-05-08): dedup against AST-emitted figures.
    # AST Figure block path 已 emit \begin{figure}\includegraphics{media/imageN.png}\end{figure}
    # 时, recover_figures 不应再为同 image 的 record emit 第二次. 旧版 fallback inline-ref
    # 路径不识别 chapter 已有 image, 致 image23.png 被 emit 2 次 (audit Check 9 [1,1,2,2,...]).
    # 扫 chapter 已有 \includegraphics 文件名, 凡 record image_filenames ∈ 已有集合 → skip.
    existing_text = "".join(lines)
    existing_includes = set(
        re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{(?:media/)?([^}]+)\}", existing_text)
    )

    by_label = {}
    for rec in records_for_chapter:
        ch = rec["caption_chapter"]
        sub = rec["caption_subnum"]
        if ch is None or sub is None:
            report["warnings"].append(
                f"  {os.path.basename(chapter_path)}: drawing@para{rec['drawing_para']}"
                f" has no caption — skipped")
            continue
        # dedup: record image filename(s) 已在 chapter 内出现 → AST 已 emit, 跳过
        rec_files = set(rec.get("image_filenames", []) or [])
        if rec_files and rec_files.issubset(existing_includes):
            report["matched"].append(
                f"  {os.path.basename(chapter_path)}: 图{ch}-{sub} skipped — "
                f"image(s) {sorted(rec_files)} already in chapter (AST-emitted)"
            )
            continue
        by_label[(ch, sub)] = rec

    injected = 0
    in_place = 0
    out_lines = []
    placed_keys = set()
    # CASE-A lun51 #3/#5: \subsection 后紧接 figure 缺过渡文字. caption-only
    # 锚位置常紧跟 \subsection (因为 docx 段顺序: 标题 → "图X-Y" caption → 过
    # 渡文字 → 列表). 直接 replace 锚 → figure 紧跟标题. 改成: 检测前一非空
    # 行是 \chapter/\section/\subsection/\subsubsection 时, defer figure 到下
    # 一个非空非标题 body 段之后.
    HEADING_RE = re.compile(r"^\s*\\(?:chapter|section|subsection|subsubsection)\b")
    pending_figure_after_heading = None  # str or None

    def _last_nonblank_is_heading() -> bool:
        for prev in reversed(out_lines):
            t = prev.strip()
            if not t:
                continue
            return bool(HEADING_RE.match(t))
        return False

    for line in lines:
        if pending_figure_after_heading is not None and line.strip():
            t = line.lstrip()
            # Wait until a non-heading, non-figure-internal body line appears,
            # emit that body line, then drop the deferred figure block right after.
            if (not HEADING_RE.match(t)
                and not t.startswith("\\begin{figure")
                and not t.startswith("\\end{figure")
                and "\\caption" not in t
                and "\\includegraphics" not in t
                and "\\label{fig:" not in t):
                out_lines.append(line)
                out_lines.append("\n" + pending_figure_after_heading)
                pending_figure_after_heading = None
                continue

        s = line.strip()
        m = LABEL_RE.match(s)
        if (m
            and "\\caption" not in line
            and "\\includegraphics" not in line
            and "\\label" not in line):
            ch = int(m.group(1))
            sub = int(m.group(2))
            tail = m.group("tail")
            role = classify_figure_line(tail)
            rec = by_label.get((ch, sub))

            if role == "caption_lookalike_body":
                # W3 D42: 长解说段 / 含触发关键字 / 含句末标点 — 必须保留, 永不 strip
                report["matched"].append(
                    f"  {os.path.basename(chapter_path)}: kept caption-lookalike body "
                    f"'图{ch}-{sub} {tail[:40]}...'")
                out_lines.append(line)
                continue

            # caption_anchor: 短 caption, 与 record 关联则替换为 figure block
            if rec is not None and (ch, sub) not in placed_keys:
                label = f"{ch}.{sub}"
                block = render_figure_block(
                    rec["image_filenames"], rec["caption_text"], label)
                placed_keys.add((ch, sub))
                injected += 1
                in_place += 1
                if _last_nonblank_is_heading():
                    # CASE-A: defer to after next body paragraph
                    pending_figure_after_heading = block
                    report["matched"].append(
                        f"  {os.path.basename(chapter_path)}: 图{label} ← deferred "
                        f"(after-heading body anchor)")
                else:
                    out_lines.append("\n" + block)
                    report["matched"].append(
                        f"  {os.path.basename(chapter_path)}: 图{label} ← in-place "
                        f"(replaced caption-only line)")
                continue
            # caption_duplicate (已放置过) — strip 安全 (Codex 节 1.2 允许)
            if (ch, sub) in placed_keys:
                report["matched"].append(
                    f"  {os.path.basename(chapter_path)}: stripped duplicate caption "
                    f"'图{ch}-{sub}'")
                continue
            # 无 matching record — 保守保留行 (W3 D42: 不再无条件 strip)
            report["matched"].append(
                f"  {os.path.basename(chapter_path)}: kept unmatched short caption "
                f"'图{ch}-{sub}' (no record)")
            out_lines.append(line)
            continue
        out_lines.append(line)

    # Fallback for records that had no caption-only anchor in the .tex —
    # try inline reference first, then append at end (sorted by subnum to keep order).
    leftover = sorted(
        ((k, by_label[k]) for k in by_label if k not in placed_keys),
        key=lambda item: (item[0][0], item[0][1]),
    )
    # CASE-A fix #2 (2026-05-08): 计算 in-table 区段, inline-ref 不落在表格内.
    # 旧版 ref_re 只排除 \includegraphics/\label, 但 \caption{图X-Y} 出现在 longtable
    # 开头时 (e.g. \begin{longtable}\caption{图4-3 ...}) 会被误判为 body inline ref,
    # 导致 \begin{figure} 块插到 \begin{longtable} 内部 → 非法嵌套 + xelatex 渲染
    # \toprule 中断为粗黑横线 (case_anon ch04 4.2.3 pp.34-38 "诡异下划线" 根源).
    table_env_re = re.compile(r"^\s*\\begin\{(longtable|table|tabular)")
    table_end_re = re.compile(r"^\s*\\end\{(longtable|table|tabular)")
    in_table_lines = [False] * len(out_lines)
    depth = 0
    for i, line in enumerate(out_lines):
        if table_env_re.match(line):
            depth += 1
        in_table_lines[i] = depth > 0
        if table_end_re.match(line):
            depth = max(0, depth - 1)

    for (ch, sub), rec in leftover:
        ref_re = re.compile(REF_PAT_TMPL.format(ch=ch, n=sub))
        target_line = None
        for i, line in enumerate(out_lines):
            if (ref_re.search(line)
                and "\\includegraphics" not in line
                and "\\label" not in line
                and "\\caption" not in line  # CASE-A: caption 行非 body ref
                and not in_table_lines[i]):  # CASE-A: 表格内禁止插入
                target_line = i
                break
        label = f"{ch}.{sub}"
        block = render_figure_block(
            rec["image_filenames"], rec["caption_text"], label)
        if target_line is not None:
            out_lines.insert(target_line + 1, "\n" + block)
            # 维护 in_table_lines 长度一致 (插入位置在 table 外, 状态 False)
            in_table_lines.insert(target_line + 1, False)
            report["matched"].append(
                f"  {os.path.basename(chapter_path)}: 图{label} → after inline ref "
                f"(line {target_line+1})")
        else:
            out_lines.append("\n" + block)
            in_table_lines.append(False)
            report["unreferenced"].append(
                f"  {os.path.basename(chapter_path)}: 图{label} — no anchor, "
                f"appended at end (subnum-ordered)")
        injected += 1
        placed_keys.add((ch, sub))

    if in_place:
        report["matched"].append(
            f"  {os.path.basename(chapter_path)}: {in_place}/{len(by_label)} "
            f"figures placed in-place at caption anchors")

    if injected:
        with open(chapter_path, "w", encoding="utf-8") as f:
            f.writelines(out_lines)
    return injected


def copy_media(extracted_media_root: str, dest_media_dir: str,
               filenames: set) -> int:
    """Copy needed image files from extracted/media/media/ to template_dir/media/."""
    os.makedirs(dest_media_dir, exist_ok=True)
    copied = 0
    for root, _, files in os.walk(extracted_media_root):
        for f in files:
            if f in filenames:
                src = os.path.join(root, f)
                dst = os.path.join(dest_media_dir, f)
                if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(src):
                    shutil.copy2(src, dst)
                    copied += 1
    return copied


def main():
    ap = argparse.ArgumentParser(description="Recover Word figures into LaTeX chapter files")
    ap.add_argument("--docx", required=True)
    ap.add_argument("--extracted", required=True, help="extracted/ dir from pandoc_ast_extract")
    ap.add_argument("--chapters", required=True, help="DissertationUESTC/chapter/ dir")
    ap.add_argument("--media-dir", required=True, help="DissertationUESTC/media/ dir")
    ap.add_argument("--include-wmf", action="store_true",
                    help="Also include .wmf images (default: skip; usually equation renderings)")
    ap.add_argument("--report", default=None, help="Optional path to write JSON report")
    ap.add_argument("--outline", default=None,
                    help="Optional outline.json from pandoc_ast_extract; if its chapters carry "
                         "docx_para_idx, use those as authoritative chapter anchors instead of "
                         "regex-based detection (avoids cluster-suppression mismatch — CASE-A)")
    args = ap.parse_args()

    print(f"📖 Reading docx: {args.docx}")
    paras, rid_to_filename = parse_docx(args.docx)
    print(f"   {len(paras)} paragraphs, {len(rid_to_filename)} image rels")

    # Body-end (致谢/参考文献边界) always from regex — it scans post_body markers
    # which outline.json doesn't carry. Chapter anchors may be overridden below.
    regex_boundaries, body_end = find_chapter_boundaries(paras)
    boundaries = regex_boundaries
    anchor_source = "regex"
    if args.outline:
        outline_anchors = load_outline_anchors(args.outline)
        if outline_anchors:
            boundaries = outline_anchors
            anchor_source = "outline.json"

    print(f"📌 Detected {len(boundaries)} body chapter boundaries [{anchor_source}]:")
    for num, idx in boundaries:
        print(f"     ch{num} @ para[{idx}]")
    if body_end is not None:
        print(f"     [body ends at para[{body_end}] — post-body sections start]")

    records = build_figure_records(paras, rid_to_filename, boundaries,
                                   body_end=body_end,
                                   include_wmf=args.include_wmf)
    print(f"🖼️  {len(records)} figure records (drawing+optional caption)")

    # D39: 给缺 caption 的 record 用 textbox_captions.json 补 (CASE-A)
    textbox_caps_path = os.path.join(args.extracted, "textbox_captions.json")
    filled = merge_textbox_captions(records, textbox_caps_path)
    if filled:
        print(f"  📦 textbox caption fill: {filled} record(s) (D39)")

    by_chapter = defaultdict(list)
    for r in records:
        ch = r["caption_chapter"] or r["chapter"]
        if ch is not None:
            by_chapter[ch].append(r)

    needed = set()
    for r in records:
        for f in r["image_filenames"]:
            needed.add(f)
    extracted_media_root = os.path.join(args.extracted, "media")
    copied = copy_media(extracted_media_root, args.media_dir, needed)
    print(f"📁 Copied {copied} image files to {args.media_dir}")

    report = {"matched": [], "unreferenced": [], "warnings": []}
    total_injected = 0
    for ch_num, recs in sorted(by_chapter.items()):
        path = os.path.join(args.chapters, f"ch{ch_num:02d}.tex")
        if not os.path.exists(path):
            report["warnings"].append(f"  ch{ch_num:02d}.tex not found at {path}")
            continue
        n = inject_into_chapter(path, recs, report)
        total_injected += n
        print(f"  ✓ ch{ch_num:02d}.tex: injected {n} figure(s)")

    print()
    print("=" * 60)
    print(f"Result: {total_injected} figure blocks injected, "
          f"{len(report['warnings'])} warnings")
    if report["unreferenced"]:
        print(f"Unreferenced (appended at chapter end): {len(report['unreferenced'])}")
        for u in report["unreferenced"][:10]:
            print(u)
    if report["warnings"]:
        print(f"Warnings:")
        for w in report["warnings"][:10]:
            print(w)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump({
                "total_injected": total_injected,
                "matched": report["matched"],
                "unreferenced": report["unreferenced"],
                "warnings": report["warnings"],
            }, f, ensure_ascii=False, indent=2)
        print(f"📝 Report: {args.report}")

    return 0 if total_injected > 0 or not records else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
