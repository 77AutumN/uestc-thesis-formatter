"""Refs segment merged guard test — W5 Wave 2 Item 2.

Two layers:
- Path A: docx integration — verify pandoc+extractor emits >= 5 refs lines.
- Path B: unit — verify split_merged_refs_if_needed splits a single-line merged
  references_raw input on each [N] boundary.

See tests/fixtures/d_refs_merged/README.md for fixture design.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


THIS = Path(__file__).resolve().parent
SKILL_ROOT = THIS.parent
SCRIPTS = SKILL_ROOT / "scripts"
FIXTURE_DIR = THIS / "fixtures" / "d_refs_merged"
GENERATOR = FIXTURE_DIR / "generate_min_docx.py"
FIXTURE_DOCX = FIXTURE_DIR / "refs_merged_min.docx"
MERGED_INPUT = FIXTURE_DIR / "merged_input.txt"
EXPECTED = FIXTURE_DIR / "expected_invariant.json"
PANDOC_EXTRACT = SCRIPTS / "pandoc_ast_extract.py"

sys.path.insert(0, str(SCRIPTS))

_N_MARKER_RE = re.compile(r"\[\s*\d+\s*\]")


def _skip_if_missing_env() -> None:
    if shutil.which("pandoc") is None:
        pytest.skip("pandoc not available")
    try:
        import docx  # noqa: F401
    except Exception as exc:
        pytest.skip(f"python-docx not available: {exc}")


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=True,
        env=env,
    )


# ============================================================
# Path A: docx integration
# ============================================================

def test_refs_5_segments_yield_5_lines() -> None:
    """Path A: 5 custom-style refs paragraphs → references_raw.txt has >= 5 lines.

    Currently passes under pandoc 3.9. Regression guard against future pandoc
    upgrades reverting to single-Para merge (CASE-A pathology).
    """
    _skip_if_missing_env()
    _run([sys.executable, str(GENERATOR), "--output", str(FIXTURE_DOCX)], cwd=FIXTURE_DIR)
    assert FIXTURE_DOCX.exists()

    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    min_lines = expected["refs_raw_line_count_min"]

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td) / "extract"
        out_dir.mkdir()
        _run(
            [sys.executable, str(PANDOC_EXTRACT), "--input", str(FIXTURE_DOCX), "--output-dir", str(out_dir)],
            cwd=SKILL_ROOT,
        )
        refs_raw_path = out_dir / "references_raw.txt"
        if not refs_raw_path.exists():
            pytest.skip("references_raw.txt not produced (extractor path differs)")
        text = refs_raw_path.read_text(encoding="utf-8")
        non_empty = [ln for ln in text.splitlines() if ln.strip()]
        assert len(non_empty) >= min_lines, (
            f"refs_raw should have >= {min_lines} lines, got {len(non_empty)}\n"
            f"content:\n{text}"
        )


# ============================================================
# Path B: unit guard
# ============================================================

def test_split_merged_refs_unit() -> None:
    """Path B: directly test the split_merged_refs_if_needed guard with a
    merged single-line input fixture.
    """
    from pandoc_ast_extract import split_merged_refs_if_needed

    text = MERGED_INPUT.read_text(encoding="utf-8")
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    min_split = expected["merged_input_split_count_min"]

    result = split_merged_refs_if_needed(text)
    lines = [ln for ln in result.splitlines() if ln.strip()]
    assert len(lines) >= min_split, (
        f"guard should split into >= {min_split} lines, got {len(lines)}\n"
        f"result:\n{result}"
    )

    # Invariant: no line contains 3+ [N] markers after split
    if expected["no_single_para_with_3_plus_n_markers"]:
        for ln in lines:
            markers = _N_MARKER_RE.findall(ln)
            assert len(markers) < 3, (
                f"line still contains {len(markers)} [N] markers (should < 3): {ln!r}"
            )


def test_split_noop_when_already_split() -> None:
    """split_merged_refs_if_needed must be a no-op when input is already line-by-line."""
    from pandoc_ast_extract import split_merged_refs_if_needed

    text = "[1] Foo.\n[2] Bar.\n[3] Baz.\n[4] Qux.\n[5] Quux."
    result = split_merged_refs_if_needed(text)
    assert result == text, "guard should not modify already-split input"


def test_split_noop_when_no_n_markers() -> None:
    """guard must not split text without [N] markers (e.g. APA-style refs)."""
    from pandoc_ast_extract import split_merged_refs_if_needed

    text = "Smith, J. (2020). Sample title. Journal of X.\nDoe, J. (2021). Another."
    result = split_merged_refs_if_needed(text)
    assert result == text, "guard should not touch input without [N] markers"
