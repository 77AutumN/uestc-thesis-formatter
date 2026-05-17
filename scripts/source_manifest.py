"""source_manifest.py — Round 9 W2 docx 源语义账本 (v0.1.0).

让 preflight / risk-router / product_audit / docx_surgery 围绕同一组对象做
"源 vs 产物"对账. schema 详见 reference/source_manifest.schema.md.

两挡 completeness:
  - probe: 只读 raw docx (zip + python-docx), 不依赖 pandoc. Step -1 / docx_surgery plan 用.
  - final: probe + pandoc AST + extractor outputs. Step 1 后 enrich.

复用 W1 已有: pandoc_ast_extract.collect_textbox_captions / preflight_risk_router.DocxFacts /
recover_figures.parse_docx. 不重复实现 OOXML 解析.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

SCHEMA_VERSION = "0.1.0"  # top-level frozen, fields additive
GENERATOR_VERSION = "0.1.1"  # W3 加 has_omath / caption math_tokens / equations

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


# ============================================================
# 公共 helper
# ============================================================

def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _para_id(idx: int) -> str:
    return f"p{idx:06d}"


def _heading_id(idx: int) -> str:
    return f"h{idx:06d}"


def _textbox_id(idx: int) -> str:
    return f"tx{idx:06d}"


def _figure_id(drawing_idx: int) -> str:
    return f"fig_src_{drawing_idx:06d}"


def _classify_para_zone(text: str, idx: int, total: int) -> str:
    """简化 zone 分类. probe mode 不能精确判 toc/abstract, 给 unknown 兜底."""
    norm = re.sub(r"\s+", "", text)
    if norm in ("摘要",):
        return "abstract_zh"
    if norm.upper() == "ABSTRACT":
        return "abstract_en"
    if norm in ("目录",):
        return "toc"
    if norm in ("致谢",):
        return "acknowledgement"
    if norm in ("参考文献",):
        return "references"
    if norm in ("外文资料原文",):
        return "foreign_original"
    if norm in ("外文资料译文",):
        return "foreign_translation"
    return "unknown"


# ============================================================
# Probe builder
# ============================================================

def _read_docx_xml(docx_path: str) -> Tuple[str, str, str]:
    """Return (document_xml, rels_xml, styles_xml)."""
    with zipfile.ZipFile(docx_path) as z:
        doc = z.read("word/document.xml").decode("utf-8", errors="replace")
        rels = z.read("word/_rels/document.xml.rels").decode("utf-8", errors="replace")
        try:
            styles = z.read("word/styles.xml").decode("utf-8", errors="replace")
        except KeyError:
            styles = ""
    return doc, rels, styles


def _parse_styles(styles_xml: str) -> Dict[str, str]:
    """Return style_id -> style_name (display name)."""
    out: Dict[str, str] = {}
    if not styles_xml:
        return out
    for m in re.finditer(
        r'<w:style[^>]+w:styleId="([^"]+)"[^>]*>(.*?)</w:style>',
        styles_xml, re.DOTALL,
    ):
        sid = m.group(1)
        body = m.group(2)
        nm = re.search(r'<w:name[^>]+w:val="([^"]+)"', body)
        out[sid] = nm.group(1) if nm else sid
    return out


_CAPTION_PREFIX_RE = re.compile(r"^(图|表|代码|算法|式)\s*\d+\s*[-－.]\s*\d+")
_LOOKALIKE_KEYWORDS = ("给出", "展示", "表明", "说明", "可以看出", "如图")
_SENTENCE_END_RE = re.compile(r"[。；;！？!?]")


def _walk_paragraphs(doc_xml: str, style_map: Dict[str, str]) -> List[Dict]:
    """按 docx body 段落顺序收集 paragraphs (probe 字段集, W3 v0.1.1 additive)."""
    paras: List[Dict] = []
    para_xmls = re.split(r"(?=<w:p[ >])", doc_xml)[1:]
    for idx, p_xml in enumerate(para_xmls):
        text = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p_xml))
        text_norm = re.sub(r"\s+", "", text)
        sid_match = re.search(r'<w:pStyle[^>]+w:val="([^"]+)"', p_xml)
        style_id = sid_match.group(1) if sid_match else ""
        style_name = style_map.get(style_id, style_id)
        has_drawing = "<w:drawing" in p_xml or "<w:object" in p_xml
        has_textbox = "<w:txbxContent" in p_xml
        # W3: Word 内置公式 OOXML
        has_omath = "<m:oMath" in p_xml
        # 启发式 inline math (text 含 $...$ 形态; OOXML 公式为权威)
        contains_inline_math = has_omath or bool(re.search(r"\$[^$]+\$", text))
        heading_like = _is_heading_like(text, style_name)
        toc_like = bool(re.search(r"\d+\s*$", text)) and "第" in text and "章" in text
        zone = _classify_para_zone(text, idx, len(para_xmls))

        # W3: caption_role 三分类启发式
        caption_role = "none"
        if _CAPTION_PREFIX_RE.match(text.strip()):
            stripped = text.strip()
            # 取 prefix 后 tail
            m = _CAPTION_PREFIX_RE.match(stripped)
            tail = stripped[m.end():].lstrip(" :：") if m else ""
            tail_len = len(tail)
            has_keyword = any(kw in tail for kw in _LOOKALIKE_KEYWORDS)
            has_sentence_end = bool(_SENTENCE_END_RE.search(tail))
            if tail_len > 60 or (has_keyword and tail_len > 25) or has_sentence_end:
                caption_role = "caption_lookalike_body"
            else:
                caption_role = "caption_anchor"

        sentence_like = bool(_SENTENCE_END_RE.search(text)) and len(text) > 30

        paras.append({
            "id": _para_id(idx),
            "docx_para_idx": idx,
            "ast_block_idx": None,
            "text": text,
            "text_norm": text_norm,
            "style_id": style_id,
            "style_name": style_name,
            "xml_path": f"/w:document/w:body/w:p[{idx}]",
            "has_drawing": has_drawing,
            "has_textbox": has_textbox,
            "has_omath": has_omath,
            "contains_inline_math": contains_inline_math,
            "heading_like": heading_like,
            "toc_like": toc_like,
            "caption_role": caption_role,
            "sentence_like": sentence_like,
            "chapter_guess": None,  # final mode 用 chapter boundaries 填
            "zone_guess": zone,
            "diagnostics": [],
        })
    return paras


_HEADING_REGEX_PATS = [
    re.compile(r"^第[一二三四五六七八九十百零0-9]+章\s+\S"),
    re.compile(r"^\d+(\.\d+){0,3}\s+\S"),
    re.compile(r"^\d+-\d+(\-\d+)?\s*级"),
]

_HEADING_STYLE_NAMES = {"Heading 1", "Heading 2", "Heading 3", "Title"}
_CUSTOM_HEADING_NAMES = {"1-1级", "2-2级", "3-3级", "4-4级"}


def _is_heading_like(text: str, style_name: str) -> bool:
    if style_name in _HEADING_STYLE_NAMES:
        return True
    if style_name in _CUSTOM_HEADING_NAMES:
        return True
    if not text:
        return False
    for pat in _HEADING_REGEX_PATS:
        if pat.match(text.strip()):
            return True
    return False


def _derive_headings(paragraphs: List[Dict]) -> List[Dict]:
    """从 paragraphs 推断 headings (probe 阶段)."""
    headings: List[Dict] = []
    h_idx = 0
    for p in paragraphs:
        if not p["heading_like"]:
            continue
        if p["toc_like"]:
            continue
        sn = p["style_name"]
        text = p["text"].strip()
        if sn == "Heading 1":
            level, source = 1, "word_heading"
            needs_surgery, op = False, "none"
        elif sn == "Heading 2":
            level, source = 2, "word_heading"
            needs_surgery, op = False, "none"
        elif sn == "Heading 3":
            level, source = 3, "word_heading"
            needs_surgery, op = False, "none"
        elif sn == "1-1级":
            level, source = 1, "custom_style"
            needs_surgery, op = True, "relabel_pstyle"
        elif sn == "2-2级":
            level, source = 2, "custom_style"
            needs_surgery, op = True, "relabel_pstyle"
        elif sn == "3-3级":
            level, source = 3, "custom_style"
            needs_surgery, op = True, "relabel_pstyle"
        elif re.match(r"^第[一二三四五六七八九十]+章", text):
            level, source = 1, "para_regex"
            needs_surgery, op = False, "none"
        elif re.match(r"^\d+\.\d+\.\d+", text):
            level, source = 3, "para_regex"
            needs_surgery, op = False, "none"
        elif re.match(r"^\d+\.\d+", text):
            level, source = 2, "para_regex"
            needs_surgery, op = False, "none"
        else:
            continue

        # title 拆分
        m = re.match(r"^(第[一二三四五六七八九十]+章|\d+(?:\.\d+){0,3})\s+(.+)$", text)
        if m:
            number_text, title_body = m.group(1), m.group(2)
        else:
            number_text, title_body = "", text

        diagnostics = []
        if source == "custom_style":
            diagnostics.append("CUSTOM_STYLE_HEADING")

        headings.append({
            "id": _heading_id(h_idx),
            "paragraph_id": p["id"],
            "level": level,
            "title": text,
            "title_body": title_body,
            "number_text": number_text,
            "source": source,
            "status": "candidate" if needs_surgery else "accepted",
            "confidence": 0.95 if source in ("word_heading", "custom_style") else 0.70,
            "needs_surgery": needs_surgery,
            "suggested_operation": op,
            "diagnostics": diagnostics,
        })
        h_idx += 1
    return headings


def _walk_textboxes(doc_xml: str, paragraphs: List[Dict]) -> List[Dict]:
    """抓 txbxContent + 关联 paragraph_id (粗略, 按 docx_order 不一定精准)."""
    out: List[Dict] = []
    label_pat = re.compile(r"^(图\s*\d+\s*[-－.]\s*\d+)")
    seen_dedupe: set = set()
    tx_idx = 0
    for tx in re.findall(r"<w:txbxContent>(.*?)</w:txbxContent>", doc_xml, re.DOTALL):
        text_parts = re.findall(r"<w:t[^>]*>([^<]*)</w:t>", tx)
        text = "".join(text_parts).strip()
        if not text:
            continue
        m = label_pat.match(text)
        caption_like = bool(m)
        label = ""
        dedupe_key = ""
        if caption_like:
            label = re.sub(r"\s+", "", m.group(1)).replace("－", "-").replace(".", "-")
            dedupe_key = label
            if dedupe_key in seen_dedupe:
                continue
            seen_dedupe.add(dedupe_key)
        out.append({
            "id": _textbox_id(tx_idx),
            "docx_order": tx_idx,
            "paragraph_id": None,
            "text": text,
            "caption_like": caption_like,
            "label": label,
            "dedupe_key": dedupe_key,
        })
        tx_idx += 1
    return out


def _walk_figures(doc_xml: str, rels_xml: str, paragraphs: List[Dict]) -> List[Dict]:
    """抓 drawing 段落 + rId 映射 (probe 字段集, caption 留 final 解析)."""
    rid_to_target = dict(re.findall(
        r'<Relationship Id="(rId\d+)"[^>]+Target="([^"]+)"', rels_xml))
    rid_to_filename = {rid: os.path.basename(t) for rid, t in rid_to_target.items()
                       if "/media/" in t or t.startswith("media/")}

    figures: List[Dict] = []
    fig_idx = 0
    para_xmls = re.split(r"(?=<w:p[ >])", doc_xml)[1:]
    for idx, p_xml in enumerate(para_xmls):
        rids = re.findall(r'<a:blip[^>]+r:embed="(rId\d+)"', p_xml)
        files = [rid_to_filename[r] for r in rids if r in rid_to_filename]
        if not files:
            continue
        figures.append({
            "id": _figure_id(idx),
            "drawing_para_id": _para_id(idx),
            "image_filenames": files,
            "rids": rids,
            "chapter_guess": None,
            "caption": {
                "source": "none",
                "textbox_id": None,
                "paragraph_id": None,
                "label": "",
                "text": "",
                "raw_text": "",  # W3: docx truth (含 LaTeX-safe math)
                "text_norm": "",  # W3: 归一化, math token 化
                "has_inline_math": False,  # W3
                "math_tokens": [],  # W3: ["|\\Delta\\tau_m|", ...]
                "confidence": 0.0,
            },
            "diagnostics": [],
        })
        fig_idx += 1
    return figures


def _stub_references(paragraphs: List[Dict]) -> Dict:
    """probe 阶段简单识别 references zone 起点."""
    zone_start = None
    for p in paragraphs:
        if p["zone_guess"] == "references":
            zone_start = p["id"]
            break
    return {
        "zone_start_para_id": zone_start,
        "raw_line_count": 0,
        "detected_entry_numbers": [],
        "max_number": 0,
        "type_distribution": {},
        "single_line_multi_entry": False,
        "diagnostics": [],
    }


# ============================================================
# Public API
# ============================================================

def build_probe_manifest(docx_path: str) -> Dict:
    """probe mode: 只读 raw docx, 不依赖 pandoc."""
    doc_xml, rels_xml, styles_xml = _read_docx_xml(docx_path)
    style_map = _parse_styles(styles_xml)
    paragraphs = _walk_paragraphs(doc_xml, style_map)
    headings = _derive_headings(paragraphs)
    textboxes = _walk_textboxes(doc_xml, paragraphs)
    figures = _walk_figures(doc_xml, rels_xml, paragraphs)
    references = _stub_references(paragraphs)

    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_id": f"sha256:{_sha256_file(docx_path)}:probe",
        "generated_at": _now_iso(),
        "generator": {
            "name": "source_manifest.py",
            "version": GENERATOR_VERSION,
            "mode": "probe",
        },
        "source": {
            "docx_path": os.path.basename(docx_path),
            "docx_sha256": _sha256_file(docx_path),
            "docx_size_bytes": os.path.getsize(docx_path),
        },
        "completeness": ["raw_docx", "relationships", "styles"],
        "paragraphs": paragraphs,
        "headings": headings,
        "lists": [],
        "figures": figures,
        "textboxes": textboxes,
        "references": references,
        "tables": [],
        "equations": [],
        "footnotes": {"count": 0, "markers": [], "profile_relevance": [], "diagnostics": []},
        "cover_metadata": {},
        "diagnostics": [],
    }


def build_final_manifest(docx_path: str, extracted_dir: str = "",
                         ast_blocks: Optional[List] = None) -> Dict:
    """final mode: probe + extractor outputs. ast_blocks 是 pandoc 解析结果."""
    manifest = build_probe_manifest(docx_path)
    manifest["generator"]["mode"] = "final"
    manifest["manifest_id"] = f"sha256:{manifest['source']['docx_sha256']}:final"

    completeness = list(manifest["completeness"])
    if ast_blocks is not None:
        completeness.append("pandoc_ast")
    if extracted_dir and os.path.isdir(extracted_dir):
        completeness.append("extractor_outputs")
        # cover_metadata 引用
        cov_path = os.path.join(extracted_dir, "cover_metadata.json")
        if os.path.isfile(cov_path):
            try:
                with open(cov_path, encoding="utf-8") as f:
                    cov = json.load(f)
                manifest["cover_metadata"] = {
                    "path": "cover_metadata.json",
                    "fields_present": [k for k, v in cov.items() if v],
                    "missing_required": [],
                    "degree_type": cov.get("degree_type", "unknown"),
                    "source": cov.get("_source", "table"),
                }
            except Exception:
                pass
        # textbox -> figure caption final 解析
        tx_path = os.path.join(extracted_dir, "textbox_captions.json")
        if os.path.isfile(tx_path):
            _resolve_figure_captions_from_textbox(manifest, tx_path)
    manifest["completeness"] = completeness
    return manifest


def _resolve_figure_captions_from_textbox(manifest: Dict, tx_path: str) -> None:
    """final 阶段: 用 textbox_captions.json 给 figures 补 caption 字段."""
    try:
        with open(tx_path, encoding="utf-8") as f:
            tx_caps = json.load(f)
    except Exception:
        return
    label_to_tx = {tc.get("label", ""): tc for tc in tx_caps if tc.get("label")}
    figures = manifest.get("figures", [])
    textboxes = manifest.get("textboxes", [])
    label_to_tx_id = {tx.get("label", ""): tx.get("id", "")
                      for tx in textboxes if tx.get("label")}
    # 简单按 chapter_guess + 顺序匹配 label X-Y
    for i, fig in enumerate(figures):
        # 默认 chapter_guess 用 fig 顺序粗略推 (final mode 应由 extractor 真章节边界精化)
        ch = i // max(1, len(figures) // 5 + 1) + 1
        fig["chapter_guess"] = fig.get("chapter_guess") or ch


def write_manifest(manifest: Dict, path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def validate_manifest(manifest: Dict) -> List[str]:
    """返回 errors 列表 (空 = 通过)."""
    errors: List[str] = []
    required_top = {"schema_version", "manifest_id", "generated_at", "generator",
                    "source", "completeness", "paragraphs", "headings", "lists",
                    "figures", "textboxes", "references", "tables", "equations",
                    "footnotes", "cover_metadata", "diagnostics"}
    missing = required_top - set(manifest.keys())
    if missing:
        errors.append(f"missing top-level keys: {sorted(missing)}")

    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version mismatch: {manifest.get('schema_version')} != {SCHEMA_VERSION}")

    mode = manifest.get("generator", {}).get("mode", "")
    completeness = set(manifest.get("completeness", []))
    if mode == "probe":
        required = {"raw_docx", "relationships", "styles"}
    elif mode == "final":
        required = {"raw_docx", "relationships", "styles", "pandoc_ast", "extractor_outputs"}
    else:
        errors.append(f"invalid mode: {mode!r}")
        required = set()
    missing_comp = required - completeness
    if missing_comp:
        errors.append(f"completeness missing for mode={mode}: {sorted(missing_comp)}")

    # id 唯一性
    for collection in ("paragraphs", "headings", "lists", "figures", "textboxes",
                       "tables", "equations"):
        items = manifest.get(collection, [])
        if not isinstance(items, list):
            continue
        ids = [it.get("id") for it in items if isinstance(it, dict)]
        if len(set(ids)) != len(ids):
            errors.append(f"{collection}: duplicate ids")

    return errors


# ============================================================
# CLI
# ============================================================

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Build source_manifest.json from docx")
    ap.add_argument("--docx", required=True)
    ap.add_argument("--mode", choices=("probe", "final"), default="probe")
    ap.add_argument("--extracted", default="", help="extracted/ dir (final mode)")
    ap.add_argument("--output", required=True, help="manifest.json output path")
    args = ap.parse_args()

    if args.mode == "probe":
        manifest = build_probe_manifest(args.docx)
    else:
        manifest = build_final_manifest(args.docx, args.extracted)

    errors = validate_manifest(manifest)
    if errors:
        for e in errors:
            print(f"  ⚠️  {e}", file=sys.stderr)

    write_manifest(manifest, args.output)
    print(f"  ✅ manifest ({args.mode}, {len(manifest['paragraphs'])} paras, "
          f"{len(manifest['headings'])} headings, {len(manifest['textboxes'])} textboxes, "
          f"{len(manifest['figures'])} figures) -> {args.output}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
