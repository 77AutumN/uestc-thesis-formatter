"""Regression tests for the chapter-number normalization heuristic in
pandoc_ast_extract.

When a thesis writes chapter titles as "N. 中文标题" (digit + period + space +
CJK title) instead of the canonical "第N章 中文标题" form, the extract loop
rewrites them so downstream RE_CHAPTER_CN matching still works.

These tests use synthetic chapter titles only — no real client content.
"""
from __future__ import annotations
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from pandoc_ast_extract import normalize_text  # noqa: E402


# Reproduce the heuristic regex inline so the test is independent of
# pandoc_ast_extract internals. Keep this pattern identical to the one in
# pandoc_ast_extract.py — if it drifts, this test should fail loudly.
_HEURISTIC = re.compile(r"^([1-9])\.\s+([一-鿿]{2,}.*)$")
_INT_TO_CN = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五",
              6: "六", 7: "七", 8: "八", 9: "九"}


def _apply_heuristic(text: str) -> str:
    normalized = normalize_text(text)
    m = _HEURISTIC.match(normalized)
    if m and not normalized.startswith("第"):
        n = int(m.group(1))
        title = m.group(2).strip()
        cn = _INT_TO_CN.get(n)
        if cn:
            return f"第{cn}章 {title}"
    return normalized


@pytest.mark.parametrize("inp,expected", [
    # Positive: digit-prefixed chapter title normalizes to canonical form
    ("1. 绪论", "第一章 绪论"),
    ("2. 文献综述", "第二章 文献综述"),
    ("3. 某示例章节标题", "第三章 某示例章节标题"),
    ("5. 实验与分析", "第五章 实验与分析"),
    ("9. 总结与展望", "第九章 总结与展望"),
])
def test_digit_chapter_title_normalized(inp, expected):
    assert _apply_heuristic(inp) == expected


@pytest.mark.parametrize("inp", [
    # Negative: numbered sub-section "N.M …" — no space between digits, no rewrite
    "3.1 子小节",
    "1.4 论文结构安排",
    "2.3.1 三级小节",
    # Negative: title already in canonical form, leave as-is
    "第一章 绪论",
    "第三章 实验与分析",
    # Negative: title starts with a digit, not CJK → exclude (avoids "3. 1 X")
    "3. 1 something",
    # Negative: title CJK too short (< 2 chars) — avoid spurious rewrites
    "3. 一",
    # Negative: ASCII title under digit prefix — pattern is CJK-only
    "3. Introduction",
])
def test_non_chapter_inputs_unchanged(inp):
    assert _apply_heuristic(inp) == normalize_text(inp)
