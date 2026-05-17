"""Unit test for product_audit Check 15 (bbox overflow advisory, W5 Wave 2).

Builds a minimal PDF in-memory with one in-bounds text block and one out-of-bounds
text block, then verifies check_page_bbox_overflow detects exactly one overflow.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

THIS = Path(__file__).resolve().parent
SKILL_ROOT = THIS.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


def _build_minimal_pdf(out_path: Path, with_overflow: bool) -> None:
    """Build an A4 PDF.

    If with_overflow=True, add a text block whose x1 exceeds (page_width - 30mm).
    """
    doc = fitz.open()
    page = doc.new_page(width=595.276, height=841.890)  # A4
    # Safe text block well inside margin
    page.insert_textbox(
        fitz.Rect(100, 100, 400, 130),
        "Inside margin sample text.",
        fontsize=10,
    )
    if with_overflow:
        # Right edge intentionally past (595 - 85 + 6 = 516); use x1=560
        page.insert_textbox(
            fitz.Rect(50, 700, 560, 730),
            "Overflow text block that crosses right margin significantly.",
            fontsize=10,
        )
    doc.save(str(out_path))
    doc.close()


@pytest.mark.skipif(fitz is None, reason="PyMuPDF not available")
def test_check15_detects_overflow(tmp_path: Path) -> None:
    from product_audit import check_page_bbox_overflow

    workdir = tmp_path / "DissertationUESTC"
    workdir.mkdir()
    pdf_path = workdir / "main.pdf"
    _build_minimal_pdf(pdf_path, with_overflow=True)

    ok, lines = check_page_bbox_overflow(str(workdir))
    assert ok, "Check 15 is advisory; must always return True"
    joined = "\n".join(lines)
    assert "block 越过版心" in joined, f"expected overflow report, got: {joined}"
    assert "right" in joined.lower(), f"expected 'right' overflow direction, got: {joined}"


@pytest.mark.skipif(fitz is None, reason="PyMuPDF not available")
def test_check15_pass_when_in_bounds(tmp_path: Path) -> None:
    from product_audit import check_page_bbox_overflow

    workdir = tmp_path / "DissertationUESTC"
    workdir.mkdir()
    pdf_path = workdir / "main.pdf"
    _build_minimal_pdf(pdf_path, with_overflow=False)

    ok, lines = check_page_bbox_overflow(str(workdir))
    assert ok
    joined = "\n".join(lines)
    assert "全部 1 页内容均在 30mm 边距内" in joined, f"expected pass, got: {joined}"


def test_check15_skips_when_no_pdf(tmp_path: Path) -> None:
    from product_audit import check_page_bbox_overflow

    workdir = tmp_path / "DissertationUESTC"
    workdir.mkdir()
    # no main.pdf
    ok, lines = check_page_bbox_overflow(str(workdir))
    assert ok
    assert "main.pdf 不存在" in "\n".join(lines)
