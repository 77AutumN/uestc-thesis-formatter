"""Unit tests for AST-based cover metadata extraction and block stripping.

Phase A: STEM Pipeline Engine Tests
These tests validate the new functions added for STEM thesis support:
- extract_cover_metadata_from_ast(): paragraph-based cover extraction
- strip_cover_and_toc_blocks(): cover/TOC block pollution prevention
"""
import pytest
import re
import sys
import os

# Add scripts to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from pandoc_ast_extract import (
    extract_cover_metadata_from_ast,
    strip_cover_and_toc_blocks,
    normalize_text,
    inlines_to_text,
)


# ============================================================
# Helpers: build synthetic AST blocks
# ============================================================

def _para(text: str) -> dict:
    """Create a synthetic Para block with a single Str inline."""
    return {"t": "Para", "c": [{"t": "Str", "c": text}]}


def _header(level: int, text: str) -> dict:
    """Create a synthetic Header block."""
    return {"t": "Header", "c": [level, ["", [], []], [{"t": "Str", "c": text}]]}


def _blockquote(texts: list) -> dict:
    """Create a BlockQuote containing multiple Para sub-blocks."""
    paras = [_para(t) for t in texts]
    return {"t": "BlockQuote", "c": paras}


# ============================================================
# Tests: extract_cover_metadata_from_ast
# ============================================================

class TestExtractCoverMetadataFromAst:
    """Test the AST paragraph-based cover metadata extractor."""

    def _build_stem_cover(self):
        """Build a synthetic STEM thesis cover AST (matches real 毕业论文.docx structure)."""
        return [
            _para("电 子 科 技 大 学"),                  # 0: university header
            _para("UNIVERSITY OF ELECTRONIC SCIENCE AND TECHNOLOGY OF CHINA"),  # 1
            _para("学士学位论文"),                        # 2: degree type
            _para("BACHELOR THESIS"),                     # 3
            _para(""),                                    # 4: empty
            _para("论文题目\t基于快速直接算法的"),         # 5: title field
            _para("雷达散射中心成像"),                    # 6: title continuation
            _blockquote([                                 # 7: metadata in BlockQuote
                "学\u3000院\t电子科学与工程学院",
                "专\u3000业\t电子科学与技术",
                "学\u3000号\t202400000000",
                "作者姓名\t张三",
                "指导教师\t李四 副研究员",
            ]),
            _header(1, "摘要"),                           # 8: abstract starts = first_chapter_idx
        ]

    def test_basic_stem_extraction(self):
        """STEM cover with all fields in paragraph+BlockQuote layout."""
        blocks = self._build_stem_cover()
        first_ch_idx = 8  # 摘要
        meta = extract_cover_metadata_from_ast(blocks, first_ch_idx)

        assert meta["title_cn"] == "基于快速直接算法的雷达散射中心成像"
        assert meta["school_cn"] == "电子科学与工程学院"
        assert meta["major_cn"] == "电子科学与技术"
        assert meta["student_id"] == "202400000000"
        assert meta["author_cn"] == "张三"
        assert meta["advisor_name_cn"] == "李四"
        assert meta["advisor_title_cn"] == "副研究员"
        assert "_cover_block_indices" in meta

    def test_cover_block_indices_include_blockquote(self):
        """Verify BlockQuote parent index is included in cover indices."""
        blocks = self._build_stem_cover()
        meta = extract_cover_metadata_from_ast(blocks, 8)
        indices = meta["_cover_block_indices"]

        # Block 7 (BlockQuote) should be in the indices
        assert 7 in indices
        # University header blocks should be captured
        assert 0 in indices
        assert 1 in indices

    def test_master_thesis_label(self):
        """Master thesis label should also be recognized."""
        blocks = [
            _para("电 子 科 技 大 学"),
            _para("硕士学位论文"),
            _para("MASTER THESIS"),
            _para("论文题目\t深度学习优化方法研究"),
            _blockquote(["作者姓名\t张三"]),
            _header(1, "第一章 绪论"),
        ]
        meta = extract_cover_metadata_from_ast(blocks, 5)
        assert meta["title_cn"] == "深度学习优化方法研究"
        assert meta["author_cn"] == "张三"

    def test_no_cover_returns_empty(self):
        """If no cover fields found, return empty dict (with empty indices)."""
        blocks = [
            _para("这是一段正文"),
            _header(1, "第一章 绪论"),
        ]
        meta = extract_cover_metadata_from_ast(blocks, 1)
        assert meta.get("title_cn") is None
        assert meta["_cover_block_indices"] == []

    def test_advisor_without_title(self):
        """Advisor with only name, no title."""
        blocks = [
            _para("论文题目\t测试论文"),
            _blockquote(["指导教师\t李四"]),
            _header(1, "摘要"),
        ]
        meta = extract_cover_metadata_from_ast(blocks, 2)
        assert meta["advisor_name_cn"] == "李四"
        assert meta["advisor_title_cn"] == ""


# ============================================================
# Tests: strip_cover_and_toc_blocks
# ============================================================

class TestStripCoverAndTocBlocks:
    """Test the cover/TOC block stripping function."""

    def test_strip_cover_blocks(self):
        """Cover blocks are marked as Null."""
        blocks = [
            _para("电 子 科 技 大 学"),     # 0
            _para("论文题目\t测试"),          # 1
            _para("其他正文段落"),             # 2
            _header(1, "第一章 绪论"),        # 3
        ]
        cover_indices = [0, 1]
        stripped = strip_cover_and_toc_blocks(blocks, cover_indices, 3)

        assert stripped >= 2
        assert blocks[0]["t"] == "Null"
        assert blocks[1]["t"] == "Null"
        assert blocks[2]["t"] == "Para"  # Not stripped

    def test_strip_toc_entries(self):
        """TOC text blocks (after '目录' heading) are marked as Null."""
        blocks = [
            _para("目录"),                           # 0: TOC header
            _para("第一章 绪论 1"),                   # 1: TOC entry
            _para("1.2 课题研究历史 2"),               # 2: TOC entry
            _para("第二章 理论基础 5"),                # 3: TOC entry
            _header(1, "第一章 绪论"),                # 4: real chapter
        ]
        stripped = strip_cover_and_toc_blocks(blocks, [], 4)

        assert blocks[0]["t"] == "Null"  # 目录 heading
        assert blocks[1]["t"] == "Null"  # TOC entry
        assert blocks[3]["t"] == "Null"  # TOC entry
        assert blocks[4]["t"] == "Header"  # Real chapter untouched

    def test_no_false_positives_without_toc(self):
        """Without a '目录' heading, regular paragraphs are not stripped."""
        blocks = [
            _para("第一章 绪论 1"),  # Looks like TOC but no preceding '目录'
            _header(1, "第一章 绪论"),
        ]
        stripped = strip_cover_and_toc_blocks(blocks, [], 1)
        assert blocks[0]["t"] == "Para"  # Not stripped

    def test_combined_cover_and_toc_strip(self):
        """Both cover blocks and TOC blocks are stripped in one call."""
        blocks = [
            _para("电 子 科 技 大 学"),     # 0: cover
            _para("目录"),                   # 1: TOC header
            _para("第一章 绪论 1"),           # 2: TOC entry
            _header(1, "第一章 绪论"),        # 3: real chapter
        ]
        stripped = strip_cover_and_toc_blocks(blocks, [0], 3)

        assert blocks[0]["t"] == "Null"
        assert blocks[1]["t"] == "Null"
        assert blocks[2]["t"] == "Null"
        assert stripped >= 3


# ============================================================
# Integration test: full pipeline with real docx (skip if not available)
# ============================================================

STEM_DOCX = r"C:\fake\path\to\thesis.docx"


@pytest.mark.skipif(not os.path.exists(STEM_DOCX), reason="STEM docx not found")
class TestRealStemDocx:
    """Integration tests using the actual STEM thesis document."""

    @pytest.fixture(scope="class")
    def ast_data(self):
        from pandoc_ast_extract import run_pandoc
        return run_pandoc(STEM_DOCX)

    @pytest.fixture(scope="class")
    def chapters_and_blocks(self, ast_data):
        from pandoc_ast_extract import find_chapters
        blocks = ast_data["blocks"]
        chapters = find_chapters(blocks)
        return blocks, chapters

    def test_real_stem_metadata_extraction(self, chapters_and_blocks):
        blocks, chapters = chapters_and_blocks
        first_ch = chapters[0]["idx"]
        meta = extract_cover_metadata_from_ast(blocks, first_ch)

        assert "title_cn" in meta
        assert "author_cn" in meta
        assert "school_cn" in meta
        assert meta["student_id"] == "202400000000"

    def test_real_stem_block_stripping(self, chapters_and_blocks):
        import copy
        blocks_copy = copy.deepcopy(chapters_and_blocks[0])
        chapters = chapters_and_blocks[1]
        first_ch = chapters[0]["idx"]

        meta = extract_cover_metadata_from_ast(blocks_copy, first_ch)
        indices = meta.pop("_cover_block_indices", [])
        stripped = strip_cover_and_toc_blocks(blocks_copy, indices, first_ch)

        assert stripped > 0
        # The TOC header (目录) should be nullified
        toc_found = False
        for b in blocks_copy:
            if b.get("t") == "Null":
                toc_found = True
                break
        assert toc_found
