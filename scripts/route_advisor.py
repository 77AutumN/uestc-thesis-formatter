"""route_advisor.py — Wave 2 Item 3, 2026-05-16.

Recommend a delivery route (`docx_direct` vs `latex_v2`) based on 4 conditions
from `reference/defects/proposed/CANDIDATE_docx_direct_route_roi_2026-05-08.md`.

The recommendation is **advisory only**: intake_report displays it as a hint,
no automatic pipeline switching. User retains final say.

Conditions (CASE-A captured these as docx_direct's high-ROI prerequisites):

1. Custom template already wires basic header/footer (STYLEREF / PAGE field).
   Otherwise docx_direct needs from-scratch header/footer XML — work ≥ 5x.
2. Customer used built-in Heading 1/2/3 styles (not custom names like "1-1级").
   Otherwise docx_direct needs register_heading_style + relabel_pstyle surgery.
3. Customer source not damaged (media r:embed intact, formulas not all WMF).
   Otherwise neither route can recover.
4. Customer only delivers .docx (no PDF rendering required).
   Cannot be auto-detected; requires user signal.

Conditions 1-3 are inspected from the .docx zip. Condition 4 is exposed as an
explicit "deliverable mode" parameter (defaults to "unknown" → safe fallback to
`latex_v2`).
"""
from __future__ import annotations

import re
import zipfile
from typing import Dict


# Built-in Heading style names that pandoc handles correctly without surgery.
_BUILTIN_HEADING_STYLE_PATTERNS = [
    re.compile(r'w:val=["\']Heading[12345]["\']'),
    re.compile(r'w:val=["\']heading[12345]["\']'),
    re.compile(r'w:val=["\']Heading\s*[12345]["\']'),  # tolerant of space
]


def _read_zip_text(zf: zipfile.ZipFile, name: str) -> str:
    try:
        return zf.read(name).decode("utf-8", errors="replace")
    except KeyError:
        return ""


def _check_header_footer(zf: zipfile.ZipFile) -> tuple[bool, list[str]]:
    """Condition 1: header/footer XML parts exist + use STYLEREF or PAGE field."""
    names = zf.namelist()
    header_parts = [n for n in names if n.startswith("word/header") and n.endswith(".xml")]
    footer_parts = [n for n in names if n.startswith("word/footer") and n.endswith(".xml")]
    if not header_parts and not footer_parts:
        return False, ["no header*.xml / footer*.xml in docx zip"]
    evidence = [f"header parts: {len(header_parts)}, footer parts: {len(footer_parts)}"]
    has_styleref_or_page = False
    for n in header_parts + footer_parts:
        xml = _read_zip_text(zf, n)
        if "STYLEREF" in xml or "PAGE" in xml:
            has_styleref_or_page = True
            evidence.append(f"{n}: STYLEREF or PAGE field detected")
            break
    if not has_styleref_or_page:
        evidence.append("header/footer present but no STYLEREF or PAGE field")
    return has_styleref_or_page, evidence


def _check_builtin_headings(zf: zipfile.ZipFile) -> tuple[bool, list[str]]:
    """Condition 2: document.xml uses w:pStyle w:val="Heading 1/2/3..."."""
    doc_xml = _read_zip_text(zf, "word/document.xml")
    if not doc_xml:
        return False, ["word/document.xml empty or missing"]
    hits = 0
    for pat in _BUILTIN_HEADING_STYLE_PATTERNS:
        hits += len(pat.findall(doc_xml))
    if hits >= 1:
        return True, [f"built-in Heading style usage count: {hits}"]
    # If common custom names appear, signal them
    custom_hits = []
    for cn in ['"1-1级"', "'1-1级'", '"标题 1"', '"标题1"', '"H1Custom"']:
        if cn in doc_xml:
            custom_hits.append(cn)
    if custom_hits:
        return False, [f"no built-in Heading; custom names detected: {custom_hits}"]
    return False, ["no built-in Heading 1/2/3 style usage detected"]


def _check_no_corruption(zf: zipfile.ZipFile) -> tuple[bool, list[str]]:
    """Condition 3: media files exist for r:embed refs + not all WMF."""
    names = zf.namelist()
    media_files = [n for n in names if n.startswith("word/media/")]
    if not media_files:
        # No media at all is fine for text-only thesis
        doc_xml = _read_zip_text(zf, "word/document.xml")
        if "r:embed=" in doc_xml or "r:link=" in doc_xml:
            return False, ["document references r:embed/r:link but no word/media/ files"]
        return True, ["no media files (text-only thesis), no corruption signal"]
    # All WMF check
    wmf_files = [n for n in media_files if n.lower().endswith((".wmf", ".emf"))]
    if media_files and len(wmf_files) == len(media_files):
        return False, [f"all {len(media_files)} media files are WMF/EMF — formula recovery likely needed"]
    evidence = [f"media files: {len(media_files)} (WMF/EMF: {len(wmf_files)})"]
    # r:embed ref count vs media file count (rough check)
    doc_xml = _read_zip_text(zf, "word/document.xml")
    embed_refs = len(re.findall(r'r:embed="rId\d+"', doc_xml))
    if embed_refs > 0:
        evidence.append(f"r:embed refs: {embed_refs}")
    return True, evidence


def detect_route_eligibility(docx_path: str, deliverable_mode: str = "unknown") -> Dict:
    """Inspect a .docx and return recommendation for delivery route.

    Args:
        docx_path: path to source .docx
        deliverable_mode: one of {"docx_only", "pdf_required", "unknown"}.
                          "unknown" defaults to safe fallback (latex_v2).

    Returns dict with per-condition booleans + evidence + final recommendation.
    """
    result: Dict = {
        "docx_path": docx_path,
        "deliverable_mode": deliverable_mode,
        "condition_1_header_footer": {"met": False, "evidence": []},
        "condition_2_builtin_headings": {"met": False, "evidence": []},
        "condition_3_no_corruption": {"met": False, "evidence": []},
        "condition_4_docx_only_delivery": {
            "met": deliverable_mode == "docx_only",
            "evidence": [f"deliverable_mode={deliverable_mode}"],
        },
        "eligible_for_docx_direct": False,
        "recommended_route": "latex_v2",
        "rationale": "",
    }
    try:
        zf = zipfile.ZipFile(docx_path)
    except (FileNotFoundError, zipfile.BadZipFile) as exc:
        result["rationale"] = f"cannot open docx as zip: {exc}"
        return result
    try:
        c1, e1 = _check_header_footer(zf)
        c2, e2 = _check_builtin_headings(zf)
        c3, e3 = _check_no_corruption(zf)
    finally:
        zf.close()
    result["condition_1_header_footer"] = {"met": c1, "evidence": e1}
    result["condition_2_builtin_headings"] = {"met": c2, "evidence": e2}
    result["condition_3_no_corruption"] = {"met": c3, "evidence": e3}
    structural_ok = c1 and c2 and c3
    result["eligible_for_docx_direct"] = structural_ok
    if structural_ok and deliverable_mode == "docx_only":
        result["recommended_route"] = "docx_direct"
        result["rationale"] = "All 4 conditions met (structure + docx-only delivery)"
    elif structural_ok and deliverable_mode == "unknown":
        result["recommended_route"] = "latex_v2"
        result["rationale"] = (
            "Structural conditions 1-3 met but deliverable_mode unknown — "
            "default to latex_v2; pass --deliverable docx-only to recommend docx_direct"
        )
    elif structural_ok and deliverable_mode == "pdf_required":
        result["recommended_route"] = "latex_v2"
        result["rationale"] = (
            "Structural conditions 1-3 met but PDF delivery required — "
            "latex_v2 gives more precise visual control"
        )
    else:
        failed = []
        if not c1:
            failed.append("1 (header/footer)")
        if not c2:
            failed.append("2 (built-in headings)")
        if not c3:
            failed.append("3 (no corruption)")
        result["recommended_route"] = "latex_v2"
        result["rationale"] = f"docx_direct unsuitable — failed conditions: {', '.join(failed)}"
    return result


def main() -> int:
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(description="Recommend delivery route (docx_direct vs latex_v2)")
    ap.add_argument("docx", help="input .docx path")
    ap.add_argument(
        "--deliverable",
        default="unknown",
        choices=["docx_only", "pdf_required", "unknown"],
        help="customer's intended delivery format (default: unknown)",
    )
    ap.add_argument("--json", action="store_true", help="output as JSON")
    args = ap.parse_args()

    result = detect_route_eligibility(args.docx, args.deliverable)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Recommended route: {result['recommended_route']}")
        print(f"Rationale: {result['rationale']}")
        for i in range(1, 5):
            key = [
                "condition_1_header_footer",
                "condition_2_builtin_headings",
                "condition_3_no_corruption",
                "condition_4_docx_only_delivery",
            ][i - 1]
            c = result[key]
            mark = "✅" if c["met"] else "❌"
            print(f"  {mark} Condition {i}: {key.split('_', 2)[2]}")
            for ev in c["evidence"]:
                print(f"      - {ev}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
