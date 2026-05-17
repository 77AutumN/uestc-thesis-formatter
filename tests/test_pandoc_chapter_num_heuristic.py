"""Regression tests for the chapter-number normalization heuristic in
pandoc_ast_extract.find_chapters.

When a thesis writes chapter titles as "N. 中文标题" (digit + period + space +
CJK title) instead of the canonical "第N章 中文标题" form, the extract loop
rewrites them so downstream RE_CHAPTER_CN matching still works.

These tests use synthetic chapter titles only — no real client content.

Two layers:
  1. Inline-regex sanity (`_apply_heuristic`) — fast, isolated, but does NOT
     guarantee the production path uses the same regex.
  2. Integration via `find_chapters(blocks)` — exercises the live production
     path. Catches drift if the inline regex and the one in
     pandoc_ast_extract.py diverge.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from pandoc_ast_extract import normalize_text, find_chapters  # noqa: E402


# ---------------------------------------------------------------------------
# Layer 1: inline-regex unit tests (fast, isolated)
# ---------------------------------------------------------------------------

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
    ("1. 绪论", "第一章 绪论"),
    ("2. 文献综述", "第二章 文献综述"),
    ("3. 某示例章节标题", "第三章 某示例章节标题"),
    ("5. 实验与分析", "第五章 实验与分析"),
    ("9. 总结与展望", "第九章 总结与展望"),
])
def test_digit_chapter_title_normalized(inp, expected):
    assert _apply_heuristic(inp) == expected


@pytest.mark.parametrize("inp", [
    "3.1 子小节",
    "1.4 论文结构安排",
    "2.3.1 三级小节",
    "第一章 绪论",
    "第三章 实验与分析",
    "3. 1 something",
    "3. 一",
    "3. Introduction",
])
def test_non_chapter_inputs_unchanged(inp):
    assert _apply_heuristic(inp) == normalize_text(inp)


# ---------------------------------------------------------------------------
# Layer 2: integration tests via find_chapters() — drift guard
#
# These confirm the heuristic actually fires inside the production extraction
# loop, not just in the inline copy above.
# ---------------------------------------------------------------------------

def _para(text: str) -> dict:
    """Build a synthetic Pandoc Para block with a single Str inline."""
    return {"t": "Para", "c": [{"t": "Str", "c": text}]}


def _header_l1(text: str) -> dict:
    """Build a synthetic Pandoc Header level-1 block."""
    return {"t": "Header", "c": [1, ["", [], []], [{"t": "Str", "c": text}]]}


def test_find_chapters_picks_up_digit_prefixed_titles():
    """find_chapters() must rewrite "N. CJK..." Para blocks and recognize them
    as chapters (the codepath the HOTFIX used to enable)."""
    blocks = [
        _header_l1("摘要"),                  # not a chapter
        _para("3. 某示例章节标题"),          # ← digit-prefixed; heuristic should fire
        _para("3.1 第一小节"),               # sub-section, NOT a chapter
        _para("3.2 第二小节"),               # sub-section, NOT a chapter
        _para("4. 示例方法"),                # ← digit-prefixed chapter 4
        _para("4.1 数据采集"),               # sub-section
    ]
    chapters = find_chapters(blocks)
    titles = [c["latex_title"] for c in chapters]
    assert "某示例章节标题" in titles, f"chapter 3 not picked up: {titles}"
    assert "示例方法" in titles, f"chapter 4 not picked up: {titles}"
    # No spurious "第3.1章" / "第3.2章" picked up from sub-sections
    assert not any("第一小节" in t or "第二小节" in t for t in titles), \
        f"sub-section leaked into chapter list: {titles}"


def test_find_chapters_does_not_rewrite_canonical_titles():
    """Already-canonical "第N章 X" titles should pass through untouched."""
    blocks = [
        _para("第一章 绪论"),
        _para("第二章 文献综述"),
    ]
    chapters = find_chapters(blocks)
    titles = [c["latex_title"] for c in chapters]
    assert "绪论" in titles
    assert "文献综述" in titles


def test_find_chapters_skips_ascii_digit_prefix():
    """ASCII title under digit prefix ("3. Introduction") must NOT become a
    chapter — heuristic is CJK-only by design."""
    blocks = [_para("3. Introduction")]
    chapters = find_chapters(blocks)
    assert chapters == [], f"ASCII title falsely promoted to chapter: {chapters}"
