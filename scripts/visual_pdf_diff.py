"""Visual PDF diff wrapper (Phase 1.5).

Compare a current PDF against a baseline PDF page-by-page and emit a structured
``visual_diff_report.json``. Designed to drop into the v5 self-heal loop later
(Step 7 of run_v2.py once it stabilises) but usable standalone today.

Backend: PyMuPDF (already a project dep). Rasterises each page at ``--dpi``
into RGB ndarray, computes per-pixel L1 distance, normalises by pixel count,
and reports pages whose fraction-changed exceeds ``--threshold``.

Why not diff-pdf-visually directly: that package shells out to ``pdftocairo``
and ImageMagick ``compare``, neither of which is on Windows by default nor
in the project's pinned ``ghcr.io/xu-cheng/texlive-full:20240101`` Docker
image. Adopting it would expand transitive system deps beyond the user's
"one new pip dep max" constraint. PyMuPDF + numpy delivers the same outputs
with zero new deps. ``diff-pdf-visually`` itself is **not** a runtime
prerequisite — it is **not** in any requirements file. The JSON ``tool``
field documents which backend ran so the wrapper can be transparently
swapped later.

Graceful degradation: every failure path writes a report with
``exit_status != "ok"`` and exits 0, so a caller (eventually run_v2.py) can
always read a report and decide whether to block.

Usage::

    python scripts/visual_pdf_diff.py \\
        --current path/to/main.pdf \\
        --baseline-pdf path/to/round_N-1_main.pdf \\
        --output-dir work/output_<id>/visual_diff/

Exit code is always 0 unless --strict is set, in which case any non-ok status
exits 1 (caller-opt-in, default off).

TODO (post-MVP, agreed Day 3): when ``page_count_mismatch`` triggers, instead
of stopping, compare the overlapping pages (``min(cur_n, base_n)``) under a
new ``compare_common_pages`` mode and report the mismatch as warning + still
emit per-page diffs for the common range. Tracked for Phase 1.5+ work.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

SCHEMA_VERSION = "0.1"


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _empty_report(current, baseline, output_dir):
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "tool": {"name": "visual_pdf_diff", "version": "0.1", "backend": None},
        "tool_version": "0.1",  # top-level alias of tool.version (added Day 3 fix)
        "exit_status": None,
        "exit_reason": None,
        "current_pdf": str(current) if current else None,
        "baseline_pdf": str(baseline) if baseline else None,
        "output_dir": str(output_dir) if output_dir else None,
        "page_count": {"current": None, "baseline": None},
        "page_count_mismatch": False,    # Day 4: stable across all exit paths
        "compared_pages": 0,
        "extra_pages_baseline": [],
        "extra_pages_target": [],
        "changed_pages": [],
        "per_page": [],
        "diff_artifacts": {"dir": None, "files": []},
        "thresholds": {},
        "elapsed_seconds": None,
    }


def _write_report(report, output_dir):
    if output_dir is None:
        return
    output_dir = Path(output_dir)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "visual_diff_report.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[visual_pdf_diff] WARN: could not write report: {e}", file=sys.stderr)


def _diff_pdfs(current_path, baseline_path, output_dir, dpi, threshold):
    """Real backend. Raises on internal errors; caller wraps.

    Day 4 update: ``page_count_mismatch`` is no longer fatal. When current
    and baseline page counts differ, we still compare ``min(cur_n, base_n)``
    overlapping pages and surface the mismatch via top-level boolean
    ``page_count_mismatch`` plus ``compared_pages``, ``extra_pages_baseline``,
    ``extra_pages_target``. ``exit_status`` stays ``ok`` as long as at least
    one page could be compared; otherwise ``no_common_pages``.
    """
    import fitz  # PyMuPDF
    import numpy as np

    cur_doc = fitz.open(str(current_path))
    base_doc = fitz.open(str(baseline_path))
    cur_n = len(cur_doc)
    base_n = len(base_doc)

    artifact_dir = Path(output_dir) / "diff_pages"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    page_count_mismatch = (cur_n != base_n)
    common_n = min(cur_n, base_n)

    # extras: 1-based page numbers that exist in only one side.
    extra_pages_baseline = list(range(common_n + 1, base_n + 1))   # baseline > common
    extra_pages_target = list(range(common_n + 1, cur_n + 1))      # current  > common

    if common_n == 0:
        cur_doc.close(); base_doc.close()
        return {
            "exit_status": "no_common_pages",
            "exit_reason": f"current has {cur_n} pages, baseline has {base_n}; nothing to compare",
            "page_count": {"current": cur_n, "baseline": base_n},
            "page_count_mismatch": page_count_mismatch,
            "compared_pages": 0,
            "extra_pages_baseline": extra_pages_baseline,
            "extra_pages_target": extra_pages_target,
            "changed_pages": [],
            "per_page": [],
            "artifact_files": [],
        }

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    changed_pages = []
    per_page = []
    artifact_files = []

    for idx in range(common_n):
        cur_pix = cur_doc[idx].get_pixmap(matrix=matrix, alpha=False)
        base_pix = base_doc[idx].get_pixmap(matrix=matrix, alpha=False)

        # Page sizes can differ (rare with same template); resample by smallest extents.
        cur_arr = np.frombuffer(cur_pix.samples, dtype=np.uint8).reshape(cur_pix.height, cur_pix.width, 3)
        base_arr = np.frombuffer(base_pix.samples, dtype=np.uint8).reshape(base_pix.height, base_pix.width, 3)

        if cur_arr.shape != base_arr.shape:
            h = min(cur_arr.shape[0], base_arr.shape[0])
            w = min(cur_arr.shape[1], base_arr.shape[1])
            a = cur_arr[:h, :w]
            b = base_arr[:h, :w]
            shape_mismatch = True
        else:
            a = cur_arr
            b = base_arr
            shape_mismatch = False

        # Per-pixel L1 across RGB; tolerate JPEG-style noise via small per-pixel deadband.
        delta = np.abs(a.astype(np.int16) - b.astype(np.int16)).sum(axis=2)
        differing_mask = delta > 30  # ~12% per channel; filters faint anti-alias noise
        differing = int(differing_mask.sum())
        total = int(differing_mask.size)
        fraction = differing / total if total else 0.0

        is_changed = fraction > threshold

        page_entry = {
            "page_1based": idx + 1,
            "fraction_changed": round(fraction, 6),
            "differing_pixels": differing,
            "total_pixels": total,
            "shape_mismatch": shape_mismatch,
            "is_changed": is_changed,
        }
        per_page.append(page_entry)

        if is_changed:
            changed_pages.append(idx + 1)
            # Render diff overlay: red where pixels differ, grayscale of current elsewhere.
            try:
                gray = a.mean(axis=2).astype(np.uint8)
                overlay = np.stack([gray, gray, gray], axis=2)
                overlay[differing_mask] = [255, 0, 0]
                # Save as PNG via PyMuPDF (avoids Pillow dep)
                h, w, _ = overlay.shape
                pix = fitz.Pixmap(fitz.csRGB, w, h, overlay.tobytes(), False)
                fname = f"diff_page_{idx + 1:03d}.png"
                pix.save(str(artifact_dir / fname))
                artifact_files.append(fname)
            except Exception as e:
                # Diff PNG write is best-effort, do not fail the run.
                print(f"[visual_pdf_diff] WARN: diff PNG save failed for page {idx+1}: {e}",
                      file=sys.stderr)

    cur_doc.close()
    base_doc.close()

    exit_reason = None
    if page_count_mismatch:
        exit_reason = (f"page_count_mismatch: current={cur_n} baseline={base_n}, "
                       f"compared {common_n} common page(s)")

    return {
        "exit_status": "ok",   # ok even with page_count_mismatch as long as common>0
        "exit_reason": exit_reason,
        "page_count": {"current": cur_n, "baseline": base_n},
        "page_count_mismatch": page_count_mismatch,
        "compared_pages": common_n,
        "extra_pages_baseline": extra_pages_baseline,
        "extra_pages_target": extra_pages_target,
        "changed_pages": changed_pages,
        "per_page": per_page,
        "artifact_files": artifact_files,
    }


def run(current, baseline, output_dir, dpi=100, threshold=0.005):
    """Library entry. Always returns a report dict; never raises.

    Day 5 default change: ``threshold`` 0.001 → 0.005 per
    ``docs/v5_drift_calibration_2026-05-07.md`` §4.1 (filters anti-alias
    border noise that A/B identity controls demonstrate is genuinely zero
    at full strength).
    """
    started = time.time()
    report = _empty_report(current, baseline, output_dir)
    report["thresholds"] = {"dpi": dpi, "fraction_changed_threshold": threshold,
                            "per_pixel_l1_deadband": 30}

    if not current or not Path(current).is_file():
        report["exit_status"] = "current_missing"
        report["exit_reason"] = f"current PDF not found: {current}"
        report["elapsed_seconds"] = round(time.time() - started, 3)
        _write_report(report, output_dir)
        return report

    if not baseline or not Path(baseline).is_file():
        report["exit_status"] = "baseline_missing"
        report["exit_reason"] = f"baseline PDF not found: {baseline}"
        report["elapsed_seconds"] = round(time.time() - started, 3)
        _write_report(report, output_dir)
        return report

    # Backend probe
    try:
        import fitz  # noqa: F401
        import numpy as np  # noqa: F401
        report["tool"]["backend"] = "pymupdf+numpy"
        try:
            import fitz as _f
            report["tool"]["pymupdf_version"] = getattr(_f, "__version__", None)
        except Exception:
            pass
    except ImportError as e:
        report["exit_status"] = "tool_missing"
        report["exit_reason"] = f"PyMuPDF/numpy not importable: {e}"
        report["elapsed_seconds"] = round(time.time() - started, 3)
        _write_report(report, output_dir)
        return report

    try:
        result = _diff_pdfs(current, baseline, output_dir, dpi, threshold)
    except Exception as e:
        report["exit_status"] = "tool_failed"
        report["exit_reason"] = f"{type(e).__name__}: {e}"
        report["traceback"] = traceback.format_exc()
        report["elapsed_seconds"] = round(time.time() - started, 3)
        _write_report(report, output_dir)
        return report

    report["exit_status"] = result["exit_status"]
    report["exit_reason"] = result["exit_reason"]
    report["page_count"] = result["page_count"]
    report["page_count_mismatch"] = result.get("page_count_mismatch", False)
    report["compared_pages"] = result.get("compared_pages", 0)
    report["extra_pages_baseline"] = result.get("extra_pages_baseline", [])
    report["extra_pages_target"] = result.get("extra_pages_target", [])
    report["changed_pages"] = result["changed_pages"]
    report["per_page"] = result["per_page"]
    artifact_dir = str((Path(output_dir) / "diff_pages").resolve())
    report["diff_artifacts"] = {
        "dir": artifact_dir if result["artifact_files"] else None,
        "files": result["artifact_files"],
    }
    report["elapsed_seconds"] = round(time.time() - started, 3)

    _write_report(report, output_dir)
    return report


# ---------------------------------------------------------------------------
# Phase 0 issue adapter (Day 3): emit pdf_baseline_drift_high issue instances.
# These are still DRAFT instances — pdf_baseline_drift_high does NOT yet have
# a contract under references/issue_contracts/, so they will fail strict
# validation on purpose. The adapter exists to demonstrate the closed loop
# (audit-side producer → schema-side validator) and lets us iterate on the
# instance shape before promoting the contract.
# ---------------------------------------------------------------------------

def _issue_id(case_label, page):
    """Stable-ish id within a single audit run."""
    return f"PDF-DRIFT-{case_label}-{page:03d}"


def _emit_drift_issues(report, drift_p0_threshold=0.05, drift_p1_threshold=0.005,
                      case_label="UNK"):
    """Convert per_page entries into issue instance dicts.

    severity rule (initial, will be calibrated Day 4+):
      fraction_changed >= drift_p0_threshold  → P0 / pdf_baseline_drift_high
      drift_p1_threshold <= ... < drift_p0    → P1 / pdf_baseline_drift_high
      below drift_p1                          → not emitted

    risk_class = B (drift between two builds reflects formatting churn,
    not customer-content edits — a B-class repairer can address it).
    repairability = trial (a global rebuild is the only fix; manual review
    still required because drift may also reflect intentional client edits).
    """
    if report.get("exit_status") != "ok":
        return []

    audit_run_id = report.get("generated_at")
    base_pdf = report.get("baseline_pdf")
    cur_pdf = report.get("current_pdf")
    artifact_dir = (report.get("diff_artifacts") or {}).get("dir")

    out = []
    for entry in report.get("per_page") or []:
        frac = entry.get("fraction_changed", 0.0)
        page = entry.get("page_1based")
        if frac >= drift_p0_threshold:
            severity = "P0"
        elif frac >= drift_p1_threshold:
            severity = "P1"
        else:
            continue
        diff_png = None
        if artifact_dir:
            diff_png = str(Path(artifact_dir) / f"diff_page_{page:03d}.png")
        instance = {
            "schema_version": "0.1",
            "issue_id": _issue_id(case_label, page),
            "issue_code": "pdf_baseline_drift_high",
            "case_id": case_label,
            "audit_run_id": audit_run_id,
            "severity": severity,
            "confidence": 0.85,
            "risk_class": "B",
            "repairability": "trial",
            "source": {"audit": "visual_pdf_diff", "check": "fraction_changed"},
            "location": {
                "pdf_page": page,
                "resolution_method": "synctex",   # caller may overwrite later
                "tex_file": None,
                "tex_line": None,
            },
            "evidence": {
                "fraction_changed": frac,
                "differing_pixels": entry.get("differing_pixels"),
                "total_pixels": entry.get("total_pixels"),
                "drift_p0_threshold": drift_p0_threshold,
                "drift_p1_threshold": drift_p1_threshold,
                "current_pdf": cur_pdf,
                "baseline_pdf": base_pdf,
                "diff_artifact": diff_png,
            },
            "suggested_repair": None,    # no Phase 0 repairer available
            "_draft": True,              # marker: contract not yet promoted
        }
        out.append(instance)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="Visual PDF diff (Phase 1.5 wrapper)")
    parser.add_argument("--current", required=True, help="Current (just-built) PDF")
    parser.add_argument("--baseline-pdf", required=True, help="Baseline PDF (e.g. round N-1 final)")
    parser.add_argument("--output-dir", required=True,
                        help="Where to write visual_diff_report.json + diff_pages/")
    parser.add_argument("--dpi", type=int, default=100,
                        help="Rasterisation DPI (default 100). Higher = slower + more sensitive.")
    parser.add_argument("--threshold", type=float, default=0.005,
                        help="Fraction-of-changed-pixels threshold to flag a page "
                             "(default 0.005 = 0.5%%, calibrated Day 4)")
    parser.add_argument("--strict", action="store_true",
                        help="Exit 1 on any non-ok status (default: always exit 0 to stay non-blocking)")
    parser.add_argument("--emit-issues", metavar="PATH",
                        help="If set, also write a JSON array of pdf_baseline_drift_high issue "
                             "instances to PATH (Phase 0 draft schema, not yet contract-validated).")
    parser.add_argument("--drift-p0", type=float, default=0.10,
                        help="fraction_changed ≥ this → P0 issue "
                             "(default 0.10 = 10%%, calibrated Day 4)")
    parser.add_argument("--drift-p1", type=float, default=0.01,
                        help="fraction_changed ≥ this (and < --drift-p0) → P1 issue "
                             "(default 0.01 = 1%%, calibrated Day 4)")
    parser.add_argument("--case-label", default="UNK",
                        help="Tag injected into issue_id and case_id fields (e.g. CASE-A)")
    args = parser.parse_args(argv)

    report = run(args.current, args.baseline_pdf, args.output_dir,
                 dpi=args.dpi, threshold=args.threshold)

    issues_written = 0
    if args.emit_issues:
        try:
            issues = _emit_drift_issues(
                report,
                drift_p0_threshold=args.drift_p0,
                drift_p1_threshold=args.drift_p1,
                case_label=args.case_label,
            )
            Path(args.emit_issues).parent.mkdir(parents=True, exist_ok=True)
            Path(args.emit_issues).write_text(
                json.dumps(issues, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            issues_written = len(issues)
        except Exception as e:
            print(f"[visual_pdf_diff] WARN: --emit-issues failed: {e}", file=sys.stderr)

    denom = report.get("compared_pages") or report["page_count"].get("current") or "?"
    mismatch_tag = " mismatch" if report.get("page_count_mismatch") else ""
    print(f"[visual_pdf_diff] status={report['exit_status']}{mismatch_tag} "
          f"changed_pages={len(report['changed_pages'])}/{denom} "
          f"elapsed={report['elapsed_seconds']}s "
          f"report={Path(args.output_dir) / 'visual_diff_report.json'}")
    if args.emit_issues:
        print(f"[visual_pdf_diff] issues_emitted={issues_written} "
              f"file={args.emit_issues}")
    if report["exit_status"] != "ok" and report.get("exit_reason"):
        print(f"[visual_pdf_diff] reason: {report['exit_reason']}", file=sys.stderr)

    if args.strict and report["exit_status"] != "ok":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
