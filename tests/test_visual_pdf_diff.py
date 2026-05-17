"""Tests for visual_pdf_diff wrapper (Phase 1.5).

Day 4 focus: compare_common_pages JSON contract.

These tests use tiny synthetic PDFs (created via PyMuPDF) so the suite
stays fast and self-contained — no dependency on case workspaces.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import visual_pdf_diff as vpd  # noqa: E402


def _write_simple_pdf(path, n_pages, label="A"):
    """Create a minimal PDF with N labelled pages using PyMuPDF."""
    import fitz
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page(width=595, height=842)  # A4
        page.insert_text((72, 72), f"{label} page {i+1}", fontsize=24)
    doc.save(str(path))
    doc.close()


@pytest.fixture
def tmp_pdfs(tmp_path):
    """Provide three small PDFs: same-content, more-pages, fewer-pages."""
    a = tmp_path / "a.pdf"; _write_simple_pdf(a, 3, "A")
    a_clone = tmp_path / "a_clone.pdf"; _write_simple_pdf(a_clone, 3, "A")
    a_extended = tmp_path / "a_extended.pdf"; _write_simple_pdf(a_extended, 5, "A")
    a_short = tmp_path / "a_short.pdf"; _write_simple_pdf(a_short, 1, "A")
    return tmp_path, a, a_clone, a_extended, a_short


# ---------------------------------------------------------------------------
# Schema stability
# ---------------------------------------------------------------------------


def test_empty_report_has_compare_common_pages_keys():
    """Schema must include the new Day 4 keys at all exit paths."""
    report = vpd._empty_report("a.pdf", "b.pdf", "/tmp/out")
    for key in ("page_count_mismatch", "compared_pages",
                "extra_pages_baseline", "extra_pages_target"):
        assert key in report, f"missing top-level key {key!r}"


def test_top_level_tool_version_alias_present():
    """Day 3 fix #2: top-level tool_version mirrors tool.version."""
    report = vpd._empty_report("a.pdf", "b.pdf", "/tmp/out")
    assert report.get("tool_version") == report["tool"]["version"]


# ---------------------------------------------------------------------------
# compare_common_pages happy paths
# ---------------------------------------------------------------------------


def test_same_pdf_zero_drift(tmp_pdfs):
    tmp_path, a, a_clone, *_ = tmp_pdfs
    out = tmp_path / "out_identity"
    report = vpd.run(a, a_clone, out, dpi=72, threshold=0.001)
    assert report["exit_status"] == "ok"
    assert report["page_count_mismatch"] is False
    assert report["compared_pages"] == 3
    assert report["extra_pages_baseline"] == []
    assert report["extra_pages_target"] == []
    assert report["changed_pages"] == []
    assert all(p["fraction_changed"] == 0.0 for p in report["per_page"])


def test_current_has_extra_pages(tmp_pdfs):
    """current=5pp, baseline=3pp → extra_pages_target=[4,5], compared=3."""
    tmp_path, a, _, a_extended, _ = tmp_pdfs
    out = tmp_path / "out_target_extra"
    report = vpd.run(a_extended, a, out, dpi=72, threshold=0.001)
    assert report["exit_status"] == "ok"
    assert report["page_count_mismatch"] is True
    assert report["compared_pages"] == 3
    assert report["page_count"] == {"current": 5, "baseline": 3}
    assert report["extra_pages_baseline"] == []
    assert report["extra_pages_target"] == [4, 5]
    assert report["exit_reason"] is not None  # mismatch reason recorded


def test_baseline_has_extra_pages(tmp_pdfs):
    """current=3pp, baseline=5pp → extra_pages_baseline=[4,5], compared=3."""
    tmp_path, a, _, a_extended, _ = tmp_pdfs
    out = tmp_path / "out_baseline_extra"
    report = vpd.run(a, a_extended, out, dpi=72, threshold=0.001)
    assert report["exit_status"] == "ok"
    assert report["page_count_mismatch"] is True
    assert report["compared_pages"] == 3
    assert report["page_count"] == {"current": 3, "baseline": 5}
    assert report["extra_pages_baseline"] == [4, 5]
    assert report["extra_pages_target"] == []


def test_one_page_vs_three(tmp_pdfs):
    """current=1pp, baseline=3pp → compared=1, extra_pages_baseline=[2,3]."""
    tmp_path, _, _, _, a_short = tmp_pdfs
    out = tmp_path / "out_short"
    report = vpd.run(a_short, tmp_pdfs[1], out, dpi=72, threshold=0.001)  # baseline = 'a'
    assert report["exit_status"] == "ok"
    assert report["compared_pages"] == 1
    assert report["extra_pages_baseline"] == [2, 3]


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


def test_missing_baseline_returns_baseline_missing(tmp_path):
    out = tmp_path / "out_missing"
    a = tmp_path / "current.pdf"; _write_simple_pdf(a, 1)
    report = vpd.run(a, tmp_path / "does_not_exist.pdf", out)
    assert report["exit_status"] == "baseline_missing"
    # New keys still present (default values from _empty_report)
    assert report["page_count_mismatch"] is False
    assert report["compared_pages"] == 0


def test_missing_current_returns_current_missing(tmp_path):
    out = tmp_path / "out_missing"
    b = tmp_path / "baseline.pdf"; _write_simple_pdf(b, 1)
    report = vpd.run(tmp_path / "does_not_exist.pdf", b, out)
    assert report["exit_status"] == "current_missing"


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


def test_emit_drift_issues_includes_compared_pages_context(tmp_pdfs):
    """Adapter should reflect drift even when page_count_mismatch."""
    tmp_path, a, _, a_extended, _ = tmp_pdfs
    out = tmp_path / "out_adapter"
    report = vpd.run(a_extended, a, out, dpi=72, threshold=0.001)
    issues = vpd._emit_drift_issues(report, drift_p0_threshold=0.05,
                                    drift_p1_threshold=0.005,
                                    case_label="TESTCASE")
    # All emitted instances should reference real compared pages, not extras
    for inst in issues:
        page = inst["location"]["pdf_page"]
        assert 1 <= page <= report["compared_pages"], (
            f"issue references page {page} but only {report['compared_pages']} "
            f"common pages were compared")
        assert inst["_draft"] is True
        assert inst["issue_code"] == "pdf_baseline_drift_high"
