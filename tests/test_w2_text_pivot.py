"""tests/test_w2_text_pivot.py — W2 text_pivot.pivot_replace 测试."""
from __future__ import annotations
import os
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(THIS, "..", "scripts"))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from utils.text_pivot import pivot_replace  # noqa: E402


def test_pivot_replace_cascade_safe():
    """4-2..4-8 → 4-1..4-7 不该 cascade overwrite."""
    text = "表4-2 表4-3 表4-4 表4-5 表4-6 表4-7 表4-8"
    mapping = {f"表4-{n}": f"表4-{n-1}" for n in range(2, 9)}
    new_text, report = pivot_replace(text, mapping)
    assert new_text == "表4-1 表4-2 表4-3 表4-4 表4-5 表4-6 表4-7"
    assert report["phase_a_subs"] == 7
    assert report["phase_b_subs"] == 7
    assert report["unreplaced_keys"] == []
    assert report["collisions"] == []


def test_pivot_replace_unreplaced_keys():
    """source key 不在 text 中 → 列入 unreplaced_keys."""
    text = "abc xyz"
    mapping = {"abc": "ABC", "missing": "MISSING"}
    new_text, report = pivot_replace(text, mapping)
    assert new_text == "ABC xyz"
    assert "missing" in report["unreplaced_keys"]


def test_pivot_replace_collision_detected():
    """target 含 placeholder → collision detect, 拒绝替换."""
    text = "abc"
    mapping = {"abc": "__PIVOT__abc__PIVOT__"}
    new_text, report = pivot_replace(text, mapping)
    assert new_text == text  # 未替换
    assert report["collisions"]


def test_pivot_replace_empty_mapping():
    text = "abc"
    new_text, report = pivot_replace(text, {})
    assert new_text == text
    assert report["phase_a_subs"] == 0
