"""tests/test_format_punctuation_bib.py — fix_bib_allowbreak split('\\n') bug.

Pre-fix the function used the literal 2-char string '\\n' as separator,
making the per-`\\item` allowbreak injection a silent no-op for any bib
file written with real newlines (i.e. all of them).
"""
import os
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.normpath(os.path.join(THIS, ".."))
HOOK_DIR = os.path.join(SKILL_DIR, "scripts", "hooks")
if HOOK_DIR not in sys.path:
    sys.path.insert(0, HOOK_DIR)

from format_punctuation import format_punctuation  # noqa: E402


def _setup_bib(tmp_path, content: str) -> str:
    """Write content to <tmp_path>/bibliography_categorized.tex; return path."""
    bib_path = os.path.join(str(tmp_path), "bibliography_categorized.tex")
    with open(bib_path, "w", encoding="utf-8") as f:
        f.write(content)
    return bib_path


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_bib_allowbreak_injects_on_each_item_line(tmp_path):
    """Multi-line bib with several `\\item` entries: each `\\item` line should
    get `\\allowbreak` after every comma and colon."""
    src = (
        "\\begin{itemize}\n"
        "\\item 张三, 李四. 测试文献: 一例[J]. 期刊, 2024.\n"
        "\\item 王五. 另一篇: 续集[J]. 期刊, 2025.\n"
        "\\end{itemize}\n"
    )
    bib = _setup_bib(tmp_path, src)
    format_punctuation(str(tmp_path), {"quote_style": "mixed"})
    out = _read(bib)
    item_lines = [ln for ln in out.split("\n") if ln.strip().startswith("\\item")]
    assert len(item_lines) == 2, item_lines
    for ln in item_lines:
        assert ",\\allowbreak " in ln, f"missing comma allowbreak: {ln!r}"
        assert ":\\allowbreak " in ln, f"missing colon allowbreak: {ln!r}"


def test_bib_non_item_lines_untouched(tmp_path):
    """Lines not starting with `\\item` keep commas/colons untouched."""
    src = (
        "% comment line, has, comma\n"
        "\\begin{itemize}\n"
        "\\item 张三, 李四. 文献[J]. 期刊, 2024.\n"
        "header line: not an item\n"
        "\\end{itemize}\n"
    )
    bib = _setup_bib(tmp_path, src)
    format_punctuation(str(tmp_path), {"quote_style": "mixed"})
    out = _read(bib)
    assert "% comment line, has, comma" in out  # untouched
    assert "header line: not an item" in out    # untouched
    item_line = next(ln for ln in out.split("\n") if ln.strip().startswith("\\item"))
    assert ",\\allowbreak " in item_line


def test_bib_no_items_no_change_to_bodies(tmp_path):
    """File with no `\\item` lines: structure preserved (no splitting glitch)."""
    src = "plain bib body, no items here.\nsecond line: also nothing.\n"
    bib = _setup_bib(tmp_path, src)
    format_punctuation(str(tmp_path), {"quote_style": "mixed"})
    out = _read(bib)
    assert out == src


def test_bib_quote_pairing_applied_inside_items(tmp_path):
    """fix_quotes runs before fix_bib_allowbreak: paired ASCII quotes inside
    an item should become curly, AND the item should still get allowbreak."""
    src = (
        "\\begin{itemize}\n"
        '\\item Author. "Some Title": notes, more[J]. Journal, 2024.\n'
        "\\end{itemize}\n"
    )
    bib = _setup_bib(tmp_path, src)
    format_punctuation(str(tmp_path), {"quote_style": "fullwidth_chinese"})
    out = _read(bib)
    assert "“Some Title”" in out
    item_line = next(ln for ln in out.split("\n") if ln.strip().startswith("\\item"))
    assert ",\\allowbreak " in item_line
    assert ":\\allowbreak " in item_line
