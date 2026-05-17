"""Visual geometry audit (Phase 1 MVP).

Reads a built ``main.pdf`` (and its sibling ``chapter/*.tex``, ``main.synctex.gz``)
under a ``DissertationUESTC/`` workspace and emits structured issue instances
covering the first batch of Phase 0 contracts:

  - large_vertical_gap
  - image_caption_split_page
  - orphan_heading_at_page_bottom

Each emitted instance:

  - conforms to ``references/issue_contracts/<issue_code>.yaml``
  - carries ``location.pdf_page``, ``location.pdf_bbox``, ``location.pdf_center_xy``
  - is enriched with ``location.tex_file`` + ``location.tex_line`` via SyncTeX
    when ``main.synctex.gz`` is available
  - is validated against its contract before being written

This is **read-only** with respect to the workspace. Day 5 explicitly does
NOT touch run_v2.py / product_audit.py / SKILL / CLAUDE / templates / vendor.

CLI::

    python scripts/visual_geometry_audit.py \\
        --workdir <work/output_caseXXX/DissertationUESTC> \\
        --output  <work/output_caseXXX/audit_issues_visual_geometry.json> \\
        [--case-label CASE-A] \\
        [--gap-threshold-pt 70] \\
        [--no-synctex]      # skip SyncTeX, useful for fast smoke runs
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Local imports (stdlib + project deps)
_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
import audit_issue_schema as ais   # noqa: E402
import synctex_locator as stx       # noqa: E402

import fitz  # PyMuPDF (already a project dep)


# ---------------------------------------------------------------------------
# Heuristics & magic numbers (documented; tunable from CLI later if needed)
# ---------------------------------------------------------------------------

A4_WIDTH_PT = 595.28
A4_HEIGHT_PT = 841.89

# UESTC §2.6: 30mm margins → ~85 pt usable text area on A4.
USABLE_TOP_PT = 85.0
USABLE_BOTTOM_PT = A4_HEIGHT_PT - 85.0  # ~ 757 pt

# Body text typical font size at UESTC: 小四 = 12pt. Headings ≥ 14pt.
BODY_FONT_SIZE_PT = 12.0
HEADING_MIN_FONT_PT = 13.0

# Chapter / section heading regexes.
_CHAPTER_RE = re.compile(r"^\s*第\s*[一二三四五六七八九十百千0-9]+\s*章\s+\S")
_SECTION_RE = re.compile(r"^\s*\d+(\.\d+){0,3}\s+\S")
_CAPTION_RE = re.compile(r"^\s*(图|表|Figure|Table|Fig\.?|Tab\.?)\s*[\d一-鿿\.\-]+")

# TOC entry detector: dot-leader pattern (5+ dots) is a strong "this is a
# table-of-contents line, not real heading" signal.
_TOC_DOT_LEADER_RE = re.compile(r"\.{5,}")

# Day 10A: math-operator filter. Block 0.27 = 10 × 0.5228 = 5.23 / 0.04 = 2.00 /
# 12792 + 17072 ≈2133 px,... and similar formula residue from being mistaken
# for section headings. Keeps the operator set conservative — only obvious math
# (=, ×, ÷, ≈, ≠, ≤, ≥, ±). Excludes +/-/*/ which can appear in legitimate
# titles like "1-1 子标题" or "C++/Java 入门".
_MATH_OP_RE = re.compile(r"[=×÷≈≠≤≥±]")

# Day 10A: real-title guard. After the section number, the remainder must
# contain at least one CJK ideograph or Latin letter — prevents bare numeric
# strings like "1.2.3" from registering as headings.
_SECTION_NUMBER_PREFIX_RE = re.compile(r"^\s*\d+(?:\.\d+){0,3}\s+(.*)$")
_TITLE_CHAR_RE = re.compile(r"[一-鿿㐀-䶿a-zA-Z]")


def _is_math_residue(text: str) -> bool:
    """True if the candidate text contains an obvious math operator."""
    return bool(_MATH_OP_RE.search(text))


def _has_real_title_text_after_section_number(text: str) -> bool:
    """For section-number-prefixed candidates, the remainder must contain
    actual title text (CJK ideograph or Latin letter)."""
    m = _SECTION_NUMBER_PREFIX_RE.match(text)
    if not m:
        return False
    return bool(_TITLE_CHAR_RE.search(m.group(1).strip()))


# Day 11A: body-text guard — reject candidates that look like body sentences
# rather than headings, even if they begin with a digit pattern that would
# otherwise match _SECTION_RE.
#
# Rules:
#   1. ML / experiment keywords (epoch / loss / accuracy / IoU / px / ms / ...)
#      are extremely rare in real Chinese thesis section titles but pervasive
#      in body sentences describing experiments.
#   2. CJK period (。) and percent signs (% / ％) in headings are essentially
#      never seen — body text uses them constantly.
#   3. CJK comma (，) followed by 6+ more characters indicates a sentence
#      continuation, not a heading enumeration.
#   4. Length cap of 50 chars: real CJK headings are concise; the longest
#      tested positive heading is `5.3.4.1 协商系统` (9 chars). Body text that
#      slipped past the math/section-real-title guards is typically a long
#      experimental observation sentence.
#
# This is purely additive over Day 5/6/10 guards — it cannot turn a previously-
# rejected candidate into a heading; it only rejects more candidates.
_BODY_KEYWORD_RE = re.compile(
    r"\b(epoch|loss|accuracy|precision|recall|dice|iou|px|ms|fps)\b",
    re.IGNORECASE,
)
_BODY_PUNCTUATION_RE = re.compile(r"[%％。]|，.{6,}")
_HEADING_MAX_CHARS = 50


def _looks_like_body_text(text: str) -> bool:
    """Heuristic body-text detector. Returns True iff candidate is unlikely
    to be a heading."""
    stripped = text.strip()
    if len(stripped) > _HEADING_MAX_CHARS:
        return True
    if _BODY_KEYWORD_RE.search(stripped):
        return True
    if _BODY_PUNCTUATION_RE.search(stripped):
        return True
    return False


# ---------------------------------------------------------------------------
# Page model extraction
# ---------------------------------------------------------------------------


def _classify_page_role(page_num: int, text_blocks: List[Dict[str, Any]]) -> str:
    """Heuristic page-role classifier (Day 6).

    Currently only distinguishes ``cover`` (page 1 / 封面) from ``body``.
    ``frontmatter`` (Roman-numeral abstract / TOC pages) is a future
    refinement — Day 5's dot-leader filter already neutralised most TOC
    false positives so it's not blocking.

    Cover heuristic:
      - page_num == 1, AND
      - no text block looks like a body paragraph (≥ 3 lines AND body-sized font)

    Reason this is conservative: a real thesis's body never starts on
    page 1 — page 1 is always the title page across UESTC bachelor /
    master / marxism profiles. "Page 1 with no body-shaped blocks" is
    therefore a robust cover signature.
    """
    if page_num != 1:
        return "body"
    body_paragraphs = sum(
        1 for b in text_blocks
        if b.get("n_lines", 0) >= 3
        and b.get("max_font_size", 0) <= HEADING_MIN_FONT_PT
    )
    return "cover" if body_paragraphs == 0 else "body"


def extract_page_model(pdf_path: Path) -> List[Dict[str, Any]]:
    """Return a list-of-dicts page model, one entry per page (1-based num).

    Each page entry:
      {
        "page_num": 1,
        "page_role": "cover" | "body",   # Day 6: filters cover-page FPs
        "width": 595.28, "height": 841.89,
        "text_blocks": [
            {"bbox": (x0,y0,x1,y1), "text": "...",
             "n_lines": int, "max_font_size": float,
             "is_chapter": bool, "is_section": bool,
             "is_caption_text": bool, "is_likely_heading": bool},
            ...
        ],
        "images": [
            {"bbox": (x0,y0,x1,y1), "xref": int}, ...
        ],
      }
    """
    doc = fitz.open(str(pdf_path))
    pages: List[Dict[str, Any]] = []
    for idx in range(len(doc)):
        page = doc[idx]
        text_blocks = []
        images = []

        raw = page.get_text("dict")
        for block in raw.get("blocks", []):
            btype = block.get("type", 0)
            if btype == 0:
                # Text block
                lines = block.get("lines") or []
                spans_text = []
                max_size = 0.0
                for line in lines:
                    for span in line.get("spans", []):
                        if span.get("text"):
                            spans_text.append(span["text"])
                        sz = span.get("size") or 0
                        if sz > max_size:
                            max_size = sz
                text = "".join(spans_text).strip()
                if not text:
                    continue
                bbox = tuple(block.get("bbox") or (0, 0, 0, 0))
                is_toc_entry = bool(_TOC_DOT_LEADER_RE.search(text))
                is_math = _is_math_residue(text)
                # Day 11A: body-text guard rejects long body sentences that
                # happen to lead with a digit ("40 个epoch 后..." style).
                is_body = _looks_like_body_text(text)
                # Day 10A: chapter/section need to NOT be math residue. Section
                # additionally needs real title text after the number prefix
                # (rejects formula residue like "0.27 = 10 × 0.5228 = 5.23"
                # and bare numeric strings like "1.2.3").
                is_chapter = (bool(_CHAPTER_RE.match(text))
                              and not is_toc_entry
                              and not is_math
                              and not is_body)
                is_section = (bool(_SECTION_RE.match(text))
                              and not is_toc_entry
                              and not is_math
                              and not is_body
                              and _has_real_title_text_after_section_number(text))
                is_caption = bool(_CAPTION_RE.match(text)) and not is_toc_entry
                # Font-only heading guess: also reject math residue + body text
                # so display-equation residue and digit-leading body sentences
                # don't sneak in via large font.
                is_heading = (
                    is_chapter or is_section
                    or (max_size >= HEADING_MIN_FONT_PT and len(lines) <= 2
                        and not is_toc_entry
                        and not is_math
                        and not is_body)
                )
                text_blocks.append({
                    "bbox": bbox,
                    "text": text,
                    "n_lines": len(lines),
                    "max_font_size": round(max_size, 2),
                    "is_chapter": is_chapter,
                    "is_section": is_section,
                    "is_caption_text": is_caption,
                    "is_likely_heading": is_heading,
                })
            elif btype == 1:
                # Image block
                bbox = tuple(block.get("bbox") or (0, 0, 0, 0))
                images.append({"bbox": bbox, "xref": block.get("number")})

        page_num = idx + 1
        pages.append({
            "page_num": page_num,
            "page_role": _classify_page_role(page_num, text_blocks),
            "width": page.rect.width,
            "height": page.rect.height,
            "text_blocks": text_blocks,
            "images": images,
        })
    doc.close()
    return pages


# ---------------------------------------------------------------------------
# Detectors (pure functions, testable without Docker / PDF)
# ---------------------------------------------------------------------------


def _bbox_center(bbox: Tuple[float, float, float, float]) -> Tuple[float, float]:
    x0, y0, x1, y1 = bbox
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def _in_usable_text_area(bbox, page) -> bool:
    """Skip header / footer / margin blocks."""
    _, y0, _, y1 = bbox
    return USABLE_TOP_PT <= y0 and y1 <= USABLE_BOTTOM_PT + 30  # mild slack


# Day 13A: equation-environment gap classifier.
# Two PDF-rendering shapes from Day 12 case 11/16 wrong-fix candidates:
#   1. "Bare tag" — next_block is exactly "(N.M)" / "(N-M)". Seen in case 11
#      all 7 wrong-fix candidates (PyMuPDF segments tag into its own block).
#   2. "Formula line + trailing tag" — next_block is the entire LaTeX-emitted
#      math line ending in (N.M). Seen in case 16 gap-1,2:
#        "Hd(fq, θ0) = e−j2πfqTs(L−1)/2(3-8)"
#        "C = [aST(f1, θ0), ...] ∈CML×Q(3-9)"
# Both share the diagnostic-only verdict; the regex below covers both.
# Conservative: anchored to end-of-string so prose like "see (3.6) below" does
# NOT classify (the trailing tag must be the very last token).
_EQUATION_TAG_TAIL_RE = re.compile(r"\(\s*\d+\s*[.\-]\s*\d+[a-zA-Z]?\s*\)\s*$")


def _classify_gap_subtype(prev_text: str, prev_is_image: bool,
                          next_text: str, next_is_image: bool) -> str:
    """Return ``"equation_gap"`` or ``"float_gap"``.

    Gap is classified as equation-environment padding iff the block AFTER
    the gap ends in a numeric equation tag like ``(3.6)`` / ``(3-8)``,
    whether the block is a bare tag or a full formula line with trailing
    tag. Otherwise falls back to ``float_gap``.
    """
    if next_is_image or prev_is_image:
        return "float_gap"
    if next_text and _EQUATION_TAG_TAIL_RE.search(next_text.strip()):
        return "equation_gap"
    return "float_gap"


def detect_large_vertical_gap(pages: List[Dict[str, Any]],
                              gap_threshold_pt: float = 70.0) -> List[Dict[str, Any]]:
    """Detect gap > threshold between consecutive content blocks on a page.

    "Content" includes both text blocks AND image blocks: an image occupies
    vertical space that should not be counted as gap, otherwise tables-then-
    figures-then-caption layouts trigger 200+pt false positives equal to the
    image's own height.

    Returns list of detection dicts (NOT yet full issue instances; the audit
    composes those after attaching SyncTeX locations).
    """
    out: List[Dict[str, Any]] = []
    for page in pages:
        # Day 6: skip cover pages — UESTC 封面是有意空白布局,大间隙是设计而非缺陷
        if page.get("page_role") == "cover":
            continue
        # Combine text + image blocks, sorted by y0; only those in usable
        # text area. Images get a sentinel "is_image" flag for evidence.
        text_in = [
            {**b, "is_image": False}
            for b in page["text_blocks"]
            if _in_usable_text_area(b["bbox"], page)
        ]
        img_in = [
            {"bbox": b["bbox"], "text": "", "is_image": True}
            for b in page["images"]
            if _in_usable_text_area(b["bbox"], page)
        ]
        content = sorted(text_in + img_in, key=lambda b: b["bbox"][1])

        for i in range(len(content) - 1):
            prev, curr = content[i], content[i + 1]
            gap = curr["bbox"][1] - prev["bbox"][3]
            if gap > gap_threshold_pt:
                # Center the SyncTeX query on the content block AFTER the
                # gap (where the source line continues). If that block is an
                # image, we still query its center: SyncTeX maps it to the
                # \includegraphics line.
                cx, cy = _bbox_center(curr["bbox"])
                prev_text = prev["text"] if not prev.get("is_image") else ""
                next_text = curr["text"] if not curr.get("is_image") else ""
                subtype = _classify_gap_subtype(
                    prev_text, prev.get("is_image", False),
                    next_text, curr.get("is_image", False),
                )
                out.append({
                    "issue_code": "large_vertical_gap",
                    "page_num": page["page_num"],
                    "synctex_query": (page["page_num"], cx, cy),
                    "pdf_bbox": [prev["bbox"][0], prev["bbox"][3],
                                 curr["bbox"][2], curr["bbox"][1]],
                    "pdf_center_xy": [cx, cy],
                    "evidence": {
                        "gap_pt": round(gap, 2),
                        "threshold_pt": gap_threshold_pt,
                        "prev_block_text": (prev["text"][:80] if not prev.get("is_image")
                                            else "[image]"),
                        "next_block_text": (curr["text"][:80] if not curr.get("is_image")
                                            else "[image]"),
                        "subtype": subtype,
                    },
                })
    return out


def detect_image_caption_split_page(pages: List[Dict[str, Any]],
                                    nearby_pt: float = 60.0) -> List[Dict[str, Any]]:
    """Detect image + caption rendered on different pages.

    Heuristic:
      For each image, find the nearest caption-text block on the same page
      (text starts with 图/表/Figure). If not found on same page, look on
      page+1; if found there → emit split-page issue.
    """
    out: List[Dict[str, Any]] = []
    for i, page in enumerate(pages):
        next_page = pages[i + 1] if i + 1 < len(pages) else None
        for img in page["images"]:
            ix0, iy0, ix1, iy1 = img["bbox"]
            ic = _bbox_center(img["bbox"])

            # Same-page caption candidates: caption-like text below the image
            same_page_candidates = [
                b for b in page["text_blocks"]
                if b["is_caption_text"]
                and b["bbox"][1] >= iy1 - 5   # below image (with mild slack)
                and b["bbox"][1] - iy1 < nearby_pt
            ]
            if same_page_candidates:
                continue   # captioned on same page → no split

            # Look on next page for caption
            if not next_page:
                continue
            next_caps = [b for b in next_page["text_blocks"] if b["is_caption_text"]]
            if not next_caps:
                continue
            # Pick the topmost caption on next page (likely the orphaned one)
            next_caps.sort(key=lambda b: b["bbox"][1])
            cap = next_caps[0]

            out.append({
                "issue_code": "image_caption_split_page",
                "page_num": page["page_num"],
                "synctex_query": (page["page_num"], ic[0], ic[1]),
                "pdf_bbox": list(img["bbox"]),
                "pdf_center_xy": list(ic),
                "evidence": {
                    "image_page": page["page_num"],
                    "caption_page": next_page["page_num"],
                    "caption_text": cap["text"][:120],
                    "image_filename": f"image_xref_{img.get('xref')}",
                },
            })
    return out


def detect_orphan_heading_at_page_bottom(pages: List[Dict[str, Any]],
                                         body_line_height_pt: float = 22.0,
                                         min_body_lines: int = 2
                                         ) -> List[Dict[str, Any]]:
    """Heading at page bottom with too few body lines following.

    UESTC §2.4 附加规则 (1): "各级标题不得置于页面最后一行"。
    Practical interpretation: at least ``min_body_lines`` lines of body
    must fit between the heading bottom and the usable-area bottom — i.e.
    the *geometric* test "is there room for body below the heading on this
    page" rather than "did body actually appear" (the latter false-positives
    on TOC pages where a section entry has no following body by design).
    """
    out: List[Dict[str, Any]] = []
    for page in pages:
        # Day 6: skip cover pages — every block on cover looks heading-like by design
        if page.get("page_role") == "cover":
            continue
        for block in page["text_blocks"]:
            if not block["is_likely_heading"]:
                continue
            if not _in_usable_text_area(block["bbox"], page):
                continue

            heading_y = block["bbox"][3]   # bottom of heading
            remaining = USABLE_BOTTOM_PT - heading_y
            body_lines_estimate = int(remaining // body_line_height_pt)

            # Count actual body blocks below this heading on same page
            body_below = sum(
                1 for b in page["text_blocks"]
                if (not b["is_likely_heading"])
                and b["bbox"][1] > heading_y
                and _in_usable_text_area(b["bbox"], page)
            )

            # Geometric test only: enough vertical room for body below?
            if body_lines_estimate < min_body_lines:
                cx, cy = _bbox_center(block["bbox"])
                # heading_level: chapter=1, section=2-4 by dotted depth
                if block["is_chapter"]:
                    level = 1
                elif block["is_section"]:
                    # count dots to estimate depth
                    head = block["text"].split()[0] if block["text"] else ""
                    level = 1 + head.count(".") + 1   # "1.2" → level 2
                    level = min(level, 4)
                else:
                    level = 2 if block["max_font_size"] >= 14 else 3

                out.append({
                    "issue_code": "orphan_heading_at_page_bottom",
                    "page_num": page["page_num"],
                    "synctex_query": (page["page_num"], cx, cy),
                    "pdf_bbox": list(block["bbox"]),
                    "pdf_center_xy": [cx, cy],
                    "evidence": {
                        "heading_text": block["text"][:120],
                        "heading_level": level,
                        "body_lines_following": body_below,
                        "page_bottom_y": USABLE_BOTTOM_PT,
                        "heading_y": round(heading_y, 2),
                    },
                })
    return out


# ---------------------------------------------------------------------------
# Issue composition (detection → validated instance)
# ---------------------------------------------------------------------------


def _compose_instance(detection: Dict[str, Any], contract: ais.Contract,
                      stx_record: Optional[stx.SyncTeXRecord],
                      issue_id: str, case_label: str,
                      run_id: str) -> Dict[str, Any]:
    location = {
        "pdf_page": detection["page_num"],
        "pdf_bbox": detection["pdf_bbox"],
        "pdf_center_xy": detection["pdf_center_xy"],
    }
    if stx_record is not None:
        location.update({
            "tex_file": stx_record.tex_file,
            "tex_line": stx_record.tex_line,
            "column": stx_record.column,
            "resolution_method": "synctex",
        })
    else:
        location.update({
            "tex_file": None,
            "tex_line": None,
            "resolution_method": "synctex_unavailable",
        })

    # First allowed_repairer becomes the suggested one (if any)
    suggested = None
    if contract.allowed_repairers:
        suggested = {
            "repairer": contract.allowed_repairers[0],
            "strategy": None,
            "plan_hash": None,
        }

    # Day 13A: equation_gap subtype downgrades repairability to "diagnostic"
    # and clears suggested_repair. The contract default for large_vertical_gap
    # is "deterministic" + float_policy_repair, but equation-environment gaps
    # are LaTeX display-math padding, NOT figure floats — applying
    # \FloatBarrier / placement_change there would be a wrong fix.
    repairability = contract.repairability
    if detection.get("evidence", {}).get("subtype") == "equation_gap":
        repairability = "diagnostic"
        suggested = None

    return {
        "schema_version": ais.SCHEMA_VERSION,
        "issue_id": issue_id,
        "issue_code": detection["issue_code"],
        "case_id": case_label,
        "audit_run_id": run_id,
        "severity": contract.severity,
        "confidence": contract.raw.get("default_confidence", 0.9),
        "risk_class": contract.risk_class,
        "repairability": repairability,
        "source": {"audit": "visual_geometry_audit", "check": detection["issue_code"]},
        "location": location,
        "evidence": detection["evidence"],
        "suggested_repair": suggested,
    }


def run_audit(workdir: Path, *, gap_threshold_pt: float = 70.0,
              case_label: str = "UNK", use_synctex: bool = True
              ) -> Dict[str, Any]:
    """Run all detectors + SyncTeX enrichment + schema validation.

    Returns a report dict including the full ``issues`` array. Caller writes
    JSON. Never raises on individual issues; problematic ones get logged
    into ``invalid_issues`` instead of dropped silently.
    """
    started = time.time()
    pdf_path = workdir / "main.pdf"
    if not pdf_path.is_file():
        return {
            "schema_version": ais.SCHEMA_VERSION,
            "exit_status": "pdf_missing",
            "exit_reason": f"main.pdf not found in {workdir}",
            "workdir": str(workdir),
            "issues": [], "invalid_issues": [],
            "elapsed_seconds": round(time.time() - started, 3),
        }

    pages = extract_page_model(pdf_path)

    detections: List[Dict[str, Any]] = []
    detections.extend(detect_large_vertical_gap(pages, gap_threshold_pt))
    detections.extend(detect_image_caption_split_page(pages))
    detections.extend(detect_orphan_heading_at_page_bottom(pages))

    # Load contracts (filter to the 3 we cover)
    contracts = ais.load_all_contracts()
    relevant_codes = {"large_vertical_gap", "image_caption_split_page",
                      "orphan_heading_at_page_bottom"}
    relevant_contracts = {k: v for k, v in contracts.items() if k in relevant_codes}

    # SyncTeX enrichment
    locator: Optional[stx.SyncTeXLocator] = None
    synctex_state = "disabled"
    if use_synctex:
        try:
            locator = stx.SyncTeXLocator(workdir)
            synctex_state = "available" if locator.available else (
                f"unavailable: {locator.unavailable_reason}")
        except Exception as e:
            synctex_state = f"init_failed: {e}"
            locator = None

    run_id = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    issues: List[Dict[str, Any]] = []
    invalid_issues: List[Dict[str, Any]] = []
    counters: Dict[str, int] = {}

    for det in detections:
        code = det["issue_code"]
        contract = relevant_contracts.get(code)
        if contract is None:
            # Should not happen for the 3 we wrote, but be defensive
            invalid_issues.append({"detection": det, "reason": "no_contract_loaded"})
            continue
        counters[code] = counters.get(code, 0) + 1
        issue_id = f"VIS-{code.upper()[:8]}-{counters[code]:04d}"

        rec = None
        if locator is not None and locator.available:
            try:
                rec = locator.locate(*det["synctex_query"])
            except Exception as e:
                # Per-call failure: treat as unavailable for this issue
                rec = None

        instance = _compose_instance(det, contract, rec, issue_id, case_label, run_id)
        errors = ais.validate_instance(instance, contract)
        if errors:
            invalid_issues.append({
                "issue_id": issue_id,
                "issue_code": code,
                "errors": [str(e) for e in errors],
                "instance": instance,
            })
        else:
            issues.append(instance)

    return {
        "schema_version": ais.SCHEMA_VERSION,
        "exit_status": "ok",
        "exit_reason": None,
        "workdir": str(workdir),
        "case_id": case_label,
        "audit_run_id": run_id,
        "synctex_state": synctex_state,
        "page_count": len(pages),
        "detection_counts": counters,
        "issues": issues,
        "invalid_issues": invalid_issues,
        "validation_pass_rate": (
            len(issues) / (len(issues) + len(invalid_issues))
            if (issues or invalid_issues) else 1.0
        ),
        "thresholds": {"gap_threshold_pt": gap_threshold_pt},
        "elapsed_seconds": round(time.time() - started, 3),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Visual geometry audit (Phase 1 MVP)")
    parser.add_argument("--workdir", required=True,
                        help="Path to a built DissertationUESTC/ workspace "
                             "containing main.pdf (and main.synctex.gz for line locating)")
    parser.add_argument("--output", required=True,
                        help="Path to write audit_issues_visual_geometry.json")
    parser.add_argument("--case-label", default="UNK")
    parser.add_argument("--gap-threshold-pt", type=float, default=70.0,
                        help="Threshold for large_vertical_gap detector (default 70pt; codex 二回应 §3.4)")
    parser.add_argument("--no-synctex", action="store_true",
                        help="Skip SyncTeX enrichment (faster, but tex_file/tex_line will be null)")
    args = parser.parse_args(argv)

    workdir = Path(args.workdir)
    if not workdir.is_dir():
        print(f"[visual_geometry_audit] ERROR: workdir not a directory: {workdir}", file=sys.stderr)
        return 1

    report = run_audit(workdir,
                       gap_threshold_pt=args.gap_threshold_pt,
                       case_label=args.case_label,
                       use_synctex=not args.no_synctex)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[visual_geometry_audit] status={report['exit_status']} "
          f"pages={report.get('page_count', '?')} "
          f"issues={len(report.get('issues') or [])} "
          f"invalid={len(report.get('invalid_issues') or [])} "
          f"synctex={report.get('synctex_state', '?')} "
          f"elapsed={report['elapsed_seconds']}s "
          f"out={out_path}")
    if report.get("detection_counts"):
        for code, n in sorted(report["detection_counts"].items()):
            print(f"  - {code}: {n}")

    return 0 if report["exit_status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
