"""tests/test_format_punctuation.py — CASE-A round 4 lun51 fix.

CJK 段落英文半角标点归一化器测试. 五个 lun51 实战触发的提醒在该规则下应消除,
同时 math/Western/decimal/cite 上下文不被误伤.
"""
import os
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.normpath(os.path.join(THIS, ".."))
HOOK_DIR = os.path.join(SKILL_DIR, "scripts", "hooks")
if HOOK_DIR not in sys.path:
    sys.path.insert(0, HOOK_DIR)

from format_punctuation import normalize_cjk_punct as N  # noqa: E402


# ============================================================
# 实战触发: lun51 #61 / #68 / #115 / #128 / #140
# ============================================================

def test_case_anon_61_citation_then_cjk():
    """']' 后半角逗号 + CJK → 全角."""
    assert N("示例引用[15],示例下文") == "示例引用[15]，示例下文"


def test_case_anon_68_math_then_cjk():
    """math 内 ',' 不动, math 后 ',' 转全角."""
    src = r"对于位置参数\(\theta=[x,y]\),示例下文"
    out = N(src)
    assert "[x,y]" in out  # math 内逗号原样
    assert "\\),示" not in out  # math 外逗号已转
    assert "\\)，示" in out


def test_case_anon_128_cjk_period_cjk():
    """CJK 间半角句号 → 全角."""
    assert N("示例上文.示例下文：") == "示例上文。示例下文："


def test_case_anon_115_cross_consecutive_punct():
    """'X，.Y' (full-width comma + half-width period 连续) → 'X，Y'."""
    assert N("示例段，.示例段").startswith("示例段，") and "." not in N("示例段，.示例段")


def test_case_anon_140_cjk_period_then_cjk():
    """CJK 间半角句号 (case-private 实战 shape)."""
    assert N("根据示例方法.以下分析") == "根据示例方法。以下分析"


# ============================================================
# Negative: math / Western / decimal / cite 不动
# ============================================================

def test_math_inline_dollar_untouched():
    """$x, y, z$ 内逗号是数学语法, 不动."""
    assert N("当 $x, y, z$ 满足") == "当 $x, y, z$ 满足"


def test_math_paren_brackets_untouched():
    r"""\(\theta = [x,y]\) 内逗号原样."""
    src = r"设 \(\theta = [x,y]\) 然后"
    assert N(src) == src


def test_decimal_untouched():
    """1.5 / 3.14 不变 (lookbehind 是数字, 不在 CJK 集)."""
    assert N("取值 1.5 时") == "取值 1.5 时"
    assert N("π ≈ 3.14159") == "π ≈ 3.14159"


def test_western_author_untouched():
    """'Smith, J.' 西文人名引用 (lookbehind 'Smith' Latin, lookahead ' ' 空格) 不动."""
    assert N("Smith, J. 提出方法") == "Smith, J. 提出方法"


def test_cite_command_untouched():
    r"""\cite{a,b} 内 ',' (lookbehind 'a' Latin, lookahead 'b' Latin) 不动."""
    assert N(r"根据[15]\cite{a,b}有") == r"根据[15]\cite{a,b}有"


def test_decimal_then_cjk_still_fires_after_decimal():
    """边界: '1.5时,继续' — 1.5 内 '.' 不动, '时,继' 半角逗号转全角."""
    out = N("取值1.5时,继续")
    assert "1.5" in out  # 小数原样
    assert "时，继" in out  # CJK 间半角已转


# ============================================================
# Idempotency / dedupe
# ============================================================

def test_idempotent_already_fullwidth():
    """已是全角的不应被破坏."""
    src = "已经全角，无需修改。是这样"
    assert N(src) == src


def test_dedupe_consecutive_full_comma():
    """'，，' → '，' (extractor 兜底输出可能产生)."""
    assert N("中文，，分隔") == "中文，分隔"


def test_dedupe_cross_punct():
    """'。，' → '，' / '，。' → '，' (优先首个)."""
    assert N("结论。，但是") == "结论，但是"
    assert N("条件，。然后") == "条件，然后"


# ============================================================
# 边界: 空字符串 / 纯空白 / 纯西文
# ============================================================

def test_empty_input():
    assert N("") == ""


def test_pure_western():
    src = "This is, a test. With Latin only."
    assert N(src) == src
