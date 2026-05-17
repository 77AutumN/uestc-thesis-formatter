"""tests/test_text_filters.py — shared text filter unit tests.

Covers the pairing fix on fix_quotes (previously every ASCII `"` mapped to
opening `“` because the second .replace looked for `"` again, finding none).
"""
import os
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.normpath(os.path.join(THIS, ".."))
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from utils.text_filters import fix_quotes  # noqa: E402


# ============================================================
# Off-path: no-op when style != fullwidth_chinese
# ============================================================

def test_off_path_returns_input_unchanged():
    src = '"hello" with `` and \'\''
    assert fix_quotes(src, "mixed") == src
    assert fix_quotes(src, "") == src


def test_empty_input():
    assert fix_quotes("", "fullwidth_chinese") == ""


# ============================================================
# LaTeX-style backtick/apostrophe pairs map literally (open/close
# already encoded by source position, no re-pairing needed)
# ============================================================

def test_backtick_pair_to_open_curly():
    assert fix_quotes("``hello``", "fullwidth_chinese") == "“hello“"


def test_apostrophe_pair_to_close_curly():
    assert fix_quotes("''world''", "fullwidth_chinese") == "”world”"


def test_latex_paired_open_close():
    assert fix_quotes("``hello''", "fullwidth_chinese") == "“hello”"


# ============================================================
# ASCII straight quote pairing — the bug fix
# ============================================================

def test_single_pair_english():
    """An English clause with one paired pair → open + close."""
    assert fix_quotes('say "hi" friend', "fullwidth_chinese") == "say “hi” friend"


def test_single_pair_chinese():
    """Chinese sentence with paired ASCII straight quotes."""
    src = '他说"你好"然后离开'
    expected = '他说“你好”然后离开'
    assert fix_quotes(src, "fullwidth_chinese") == expected


def test_two_pairs_alternate():
    """Two pairs → 4 quotes → open/close/open/close."""
    src = '"a" and "b"'
    assert fix_quotes(src, "fullwidth_chinese") == "“a” and “b”"


def test_three_pairs_alternate():
    src = '"x" "y" "z"'
    assert fix_quotes(src, "fullwidth_chinese") == "“x” “y” “z”"


def test_mixed_cn_en_paired():
    """Mixed CJK/Latin with paired straight quotes."""
    src = '中文 "English term" 又一段 "another"'
    expected = '中文 “English term” 又一段 “another”'
    assert fix_quotes(src, "fullwidth_chinese") == expected


# ============================================================
# Conservative behavior on odd-count (unmatched) ASCII quotes
# ============================================================

def test_odd_count_leaves_dangler_as_ascii():
    """One unmatched quote → leave it ASCII rather than guess direction."""
    src = 'opens "here without close'
    out = fix_quotes(src, "fullwidth_chinese")
    assert out == 'opens "here without close'  # entirely unchanged: 1 quote, unmatched


def test_three_quotes_first_pair_then_dangler():
    """3 ASCII quotes: first two pair (open+close), third left raw."""
    src = '"a" then "dangler'
    out = fix_quotes(src, "fullwidth_chinese")
    assert out == '“a” then "dangler'


def test_five_quotes_two_pairs_then_dangler():
    src = '"a" "b" "c'
    out = fix_quotes(src, "fullwidth_chinese")
    assert out == '“a” “b” "c'


# ============================================================
# Mixed LaTeX-style + ASCII coexist
# ============================================================

def test_latex_and_ascii_coexist():
    """LaTeX `` '' map literally; ASCII still pairs independently."""
    src = '``foo\'\' and "bar"'
    out = fix_quotes(src, "fullwidth_chinese")
    assert out == "“foo” and “bar”"


def test_no_quotes_unchanged():
    src = "纯文本 no quotes here"
    assert fix_quotes(src, "fullwidth_chinese") == src
