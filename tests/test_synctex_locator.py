"""Unit tests for synctex_locator parser.

The Docker-shelling locate() path is exercised end-to-end by Day 1's
acid-test script and Day 5's CASE-A sandbox run; here we focus on the
pure-Python parsing logic which is the bit that's likely to drift on
synctex output format changes.
"""

from __future__ import annotations
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import synctex_locator as stx  # noqa: E402


# Sample stdout copied verbatim from a Day 1 spike CASE-A ch04 run
SAMPLE_OUTPUT = """\
This is SyncTeX command line utility, version 1.5
SyncTeX result begin
Output:/thesis/main.pdf
Page:46
x:244.04
y:258.13
h:88.0
v:710.5
W:434.0
H:14.0
before:
offset:0
middle:
after:
Output:/thesis/main.pdf
Input:/thesis/./chapter/ch04.tex
Line:323
Column:-1
Offset:0
Context:    \\caption{...}
SyncTeX result end
"""


def test_parse_extracts_record():
    records = stx.SyncTeXLocator.parse_synctex_output(SAMPLE_OUTPUT)
    assert len(records) >= 1
    rec = records[0]
    assert rec.tex_file == "chapter/ch04.tex"
    assert rec.tex_line == 323
    assert rec.column == -1


def test_parse_strips_thesis_mount_prefix():
    out = """\
Output:/thesis/main.pdf
Input:/thesis/./misc/abstract_zh.tex
Line:7
Column:0
"""
    rec = stx.SyncTeXLocator.parse_synctex_output(out)[0]
    assert rec.tex_file == "misc/abstract_zh.tex"
    assert rec.tex_line == 7


def test_parse_handles_multiple_records():
    out = """\
Output:/thesis/main.pdf
Input:/thesis/./chapter/ch04.tex
Line:100
Column:-1
Output:/thesis/main.pdf
Input:/thesis/./chapter/ch04.tex
Line:120
Column:-1
"""
    records = stx.SyncTeXLocator.parse_synctex_output(out)
    assert len(records) == 2
    assert records[0].tex_line == 100
    assert records[1].tex_line == 120


def test_parse_empty_returns_empty_list():
    assert stx.SyncTeXLocator.parse_synctex_output("") == []
    assert stx.SyncTeXLocator.parse_synctex_output("This is SyncTeX 1.5\n") == []


def test_record_to_location_dict_shape():
    rec = stx.SyncTeXRecord(tex_file="chapter/ch04.tex", tex_line=323, column=-1,
                             raw_input="/thesis/./chapter/ch04.tex")
    loc = rec.to_location_dict()
    assert loc["tex_file"] == "chapter/ch04.tex"
    assert loc["tex_line"] == 323
    assert loc["column"] == -1
    assert loc["resolution_method"] == "synctex"


def test_locator_unavailable_when_no_synctex_gz(tmp_path):
    # workdir exists but has no main.synctex.gz
    loc = stx.SyncTeXLocator(tmp_path)
    assert loc.available is False
    assert "main.synctex.gz" in (loc.unavailable_reason or "")
    # locate() should return None gracefully without invoking Docker
    assert loc.locate(1, 100, 100) is None


def test_locator_init_rejects_missing_workdir():
    with pytest.raises(FileNotFoundError):
        stx.SyncTeXLocator("/nonexistent/path/that/should/not/be/here")
