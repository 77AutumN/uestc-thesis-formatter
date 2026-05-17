"""Docx-level pilot for D40.

This test keeps the scope to a minimal docx fixture and only checks
stable text / regex invariants. No pixel diff, no full visual audit.
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
FIXTURE_DIR = THIS / "fixtures" / "d40_mutant"
GENERATOR = FIXTURE_DIR / "generate_d40_min_docx.py"
FIXTURE_DOCX = FIXTURE_DIR / "d40_min.docx"
EXPECTED = FIXTURE_DIR / "expected_invariant.json"
PANDOC_EXTRACT = SCRIPTS / "pandoc_ast_extract.py"


def _skip_if_missing_env() -> None:
    if shutil.which("pandoc") is None:
        pytest.skip("pandoc not available")
    try:
        import docx  # noqa: F401
    except Exception as exc:  # pragma: no cover - environment dependent
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


def _collect_tex_text(tex_root: Path) -> str:
    tex_files = sorted(tex_root.rglob("*.tex"))
    assert tex_files, f"no .tex files found under {tex_root}"
    return "\n".join(p.read_text(encoding="utf-8") for p in tex_files)


def test_d40_docx_mutant_pilot() -> None:
    _skip_if_missing_env()

    _run([sys.executable, str(GENERATOR), "--output", str(FIXTURE_DOCX)], cwd=FIXTURE_DIR)
    assert FIXTURE_DOCX.exists(), "fixture generator did not create d40_min.docx"

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td) / "d40_extract"
        out_dir.mkdir(parents=True, exist_ok=True)

        _run([sys.executable, str(PANDOC_EXTRACT), "--input", str(FIXTURE_DOCX), "--output-dir", str(out_dir)], cwd=SKILL_ROOT)

        tex_text = _collect_tex_text(out_dir)
        expected = json.loads(EXPECTED.read_text(encoding="utf-8"))

        equation_count = len(re.findall(r"\\begin\{equation\}", tex_text))
        assert equation_count >= expected["equation_count_min"]

        for pat in expected["tag_pattern_matches"]:
            assert re.search(pat, tex_text), f"missing tag pattern: {pat}"

        assert expected["no_literal_paren_marker"] is True
        assert "(1-2)" not in tex_text

        assert expected["control_text_must_survive"] in tex_text
