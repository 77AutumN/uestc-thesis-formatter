"""Tests for Phase 2: STEM content handling in pandoc_ast_extract.py.

Covers:
  - inlines_to_latex (Math-aware LaTeX output)
  - handle_figure_block (Figure → LaTeX figure environment)
  - H1 soup classification in generate_chapter_tex
"""
import sys
import os
import pytest

# Add scripts/ to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))

from pandoc_ast_extract import (
    inlines_to_latex,
    inlines_to_text,
    handle_figure_block,
    generate_chapter_tex,
    classify_paragraph,
    is_body_text,
    escape_latex,
    RE_FIG_NUM,
    RE_CAPTION_NUM_PREFIX,
)


# ============================================================
# inlines_to_latex tests
# ============================================================

class TestInlinesToLatex:
    """Test Math-aware LaTeX rendering of inline nodes."""

    def test_plain_text_escapes_special_chars(self):
        """Non-Math text should have LaTeX special chars escaped."""
        inlines = [{"t": "Str", "c": "A & B"}]
        result = inlines_to_latex(inlines)
        assert result == "A \\& B"

    def test_inline_math_preserved(self):
        """InlineMath → $...$"""
        inlines = [
            {"t": "Str", "c": "where"},
            {"t": "Space"},
            {"t": "Math", "c": [{"t": "InlineMath"}, "E = mc^2"]},
        ]
        result = inlines_to_latex(inlines)
        assert "$E = mc^2$" in result
        assert result.startswith("where $E = mc^2$")

    def test_display_math_uses_brackets(self):
        """DisplayMath → \\[ ... \\]"""
        inlines = [
            {"t": "Math", "c": [{"t": "DisplayMath"}, "\\nabla \\times E = 0"]},
        ]
        result = inlines_to_latex(inlines)
        assert "\\[" in result
        assert "\\nabla \\times E = 0" in result
        assert "\\]" in result

    def test_mixed_text_and_math(self):
        """Text with embedded math should not double-escape the math."""
        inlines = [
            {"t": "Str", "c": "电荷密度"},
            {"t": "Math", "c": [{"t": "InlineMath"}, "\\rho"]},
            {"t": "Str", "c": "的单位"},
        ]
        result = inlines_to_latex(inlines)
        assert "电荷密度$\\rho$的单位" == result

    def test_underscore_escaped_outside_math(self):
        """Underscores in text should be escaped, but NOT inside math."""
        inlines = [
            {"t": "Str", "c": "E_field"},
            {"t": "Space"},
            {"t": "Math", "c": [{"t": "InlineMath"}, "E_{field}"]},
        ]
        result = inlines_to_latex(inlines)
        assert "E\\_field" in result  # text underscore escaped
        assert "$E_{field}$" in result  # math underscore NOT escaped

    def test_code_inline_uses_texttt(self):
        """Code inlines should use \\texttt."""
        inlines = [{"t": "Code", "c": [["", [], []], "print()"]}]
        result = inlines_to_latex(inlines)
        assert "\\texttt{print()}" == result

    def test_raw_latex_passthrough(self):
        """RawInline with format=latex should pass through."""
        inlines = [{"t": "RawInline", "c": ["latex", "\\newpage"]}]
        result = inlines_to_latex(inlines)
        assert result == "\\newpage"

    def test_empty_inlines(self):
        result = inlines_to_latex([])
        assert result == ""

    def test_strong_children_escaped(self):
        """Strong wrapper should still escape children."""
        inlines = [{"t": "Strong", "c": [{"t": "Str", "c": "100%"}]}]
        result = inlines_to_latex(inlines)
        assert result == "100\\%"


# ============================================================
# handle_figure_block tests
# ============================================================

def _make_figure_block(caption_text: str, img_src: str,
                       width: str = None, height: str = None):
    """Helper: build a minimal Pandoc Figure AST block."""
    caption_inlines = []
    for word in caption_text.split():
        if caption_inlines:
            caption_inlines.append({"t": "Space"})
        caption_inlines.append({"t": "Str", "c": word})

    img_attrs_kv = []
    if width:
        img_attrs_kv.append(["width", width])
    if height:
        img_attrs_kv.append(["height", height])

    return {
        "t": "Figure",
        "c": [
            ["", [], []],  # attrs
            [None, [{"t": "Para", "c": caption_inlines}]],  # caption
            [{"t": "Plain", "c": [  # body
                {"t": "Image", "c": [
                    ["", [], img_attrs_kv],  # img attrs
                    [],  # alt
                    [img_src, ""],  # [src, title]
                ]}
            ]}],
        ],
    }


class TestHandleFigureBlock:
    """Test Figure block → LaTeX figure environment."""

    def test_basic_figure(self):
        block = _make_figure_block(
            "图2-1 RWG基函数模型示意图",
            "fake/path/to/media/image2.png",
            width="2.5in",
        )
        result = handle_figure_block(block)
        assert "\\begin{figure}[H]" in result
        assert "\\centering" in result
        assert "\\includegraphics" in result
        assert "media/image2.png" in result
        assert "\\caption{" in result
        assert "RWG" in result
        assert "\\end{figure}" in result

    def test_figure_label_extraction(self):
        block = _make_figure_block("图3-5 测试图", "media/image5.png")
        result = handle_figure_block(block)
        assert "\\label{fig:3-5}" in result

    def test_figure_width_capped(self):
        """Width > 5.5in should be capped at 0.9\\textwidth."""
        block = _make_figure_block("图1-1 test", "media/image1.png", width="6.0in")
        result = handle_figure_block(block)
        assert "0.90\\textwidth" in result

    def test_figure_no_width(self):
        """Missing width defaults to 0.8\\textwidth."""
        block = _make_figure_block("图1-1 test", "media/image1.png")
        result = handle_figure_block(block)
        assert "0.8\\textwidth" in result

    def test_figure_no_image(self):
        """Figure with no Image inline → placeholder comment."""
        block = {"t": "Figure", "c": [["", [], []], [None, []], []]}
        result = handle_figure_block(block)
        assert "% [FIGURE:" in result

    def test_malformed_figure(self):
        block = {"t": "Figure", "c": []}
        result = handle_figure_block(block)
        assert "malformed" in result

    def test_custom_media_base(self):
        block = _make_figure_block("图1-1 x", "any/path/img.png")
        result = handle_figure_block(block, media_base="images")
        assert "images/img.png" in result

    def test_figure_special_chars_in_caption(self):
        """Special LaTeX chars in caption should be escaped."""
        block = _make_figure_block("图2-3 模型A&B的比较", "media/img.png")
        result = handle_figure_block(block)
        assert "A\\&B" in result


# ============================================================
# H1 soup classification tests
# ============================================================

class TestH1SoupClassification:
    """Test that Header L1 blocks are correctly classified."""

    def _make_header(self, level, text):
        inlines = [{"t": "Str", "c": text}]
        return {"t": "Header", "c": [level, ["", [], []], inlines]}

    def _make_para(self, text):
        return {"t": "Para", "c": [{"t": "Str", "c": text}]}

    def test_h1_chapter_skipped(self):
        """H1 with '第X章' should be skipped (chapter already in \\chapter)."""
        blocks = [
            self._make_header(1, "第二章 电磁散射特性的基本理论"),  # start
            self._make_header(1, "第二章 电磁散射特性的基本理论"),  # duplicate
        ]
        result = generate_chapter_tex(blocks, 0, 2, "电磁散射特性的基本理论")
        # Only the \\chapter line, no duplicate
        assert result.count("\\chapter") == 1

    def test_h1_section_recognized(self):
        """H1 with 'X.Y title' should become \\section."""
        blocks = [
            self._make_header(1, "第一章 绪论"),  # chapter start
            self._make_header(1, "1.1 研究工作的背景与意义"),  # section
        ]
        result = generate_chapter_tex(blocks, 0, 2, "绪论")
        assert "\\section{研究工作的背景与意义}" in result

    def test_h1_subsection_recognized(self):
        """H1 with 'X.Y.Z title' should become \\subsection."""
        blocks = [
            self._make_header(1, "第一章 绪论"),
            self._make_header(1, "1.2.1 电磁散射特性研究历史与现状"),
        ]
        result = generate_chapter_tex(blocks, 0, 2, "绪论")
        assert "\\subsection{电磁散射特性研究历史与现状}" in result

    def test_h1_body_text_as_paragraph(self):
        """H1 that doesn't match any heading pattern → body paragraph."""
        blocks = [
            self._make_header(1, "第一章 绪论"),
            self._make_header(1, "矩量法是计算电磁学中非常经典的积分方程法。"),
        ]
        result = generate_chapter_tex(blocks, 0, 2, "绪论")
        # Should be plain text, not a heading command
        assert "矩量法是计算电磁学中非常经典的积分方程法。" in result
        assert "\\section" not in result.split("\\chapter")[1]  # after chapter line

    def test_h1_with_math_as_paragraph(self):
        """H1 body text with Math inline should preserve the math."""
        blocks = [
            self._make_header(1, "第一章 绪论"),
            {"t": "Header", "c": [1, ["", [], []], [
                {"t": "Str", "c": "其中"},
                {"t": "Math", "c": [{"t": "InlineMath"}, "E = mc^2"]},
                {"t": "Str", "c": "是能量方程"},
            ]]},
        ]
        result = generate_chapter_tex(blocks, 0, 2, "绪论")
        assert "$E = mc^2$" in result

    def test_backward_compat_marxism(self):
        """A well-structured doc (no H1 soup) should still work correctly."""
        blocks = [
            self._make_para("第一章 绪论"),  # start (Para type)
            self._make_para("本章介绍了关于统战的基本理论。"),
            self._make_para("1.1 研究背景"),
            self._make_para("统战工作的重要性不言而喻。"),
        ]
        # Simulate chapter starting at block 0
        result = generate_chapter_tex(blocks, 0, 4, "绪论")
        assert "\\chapter{绪论}" in result
        assert "\\section{研究背景}" in result
        assert "统战工作的重要性不言而喻。" in result

    def test_h3_math_not_subsection(self):
        """H3 containing Math nodes → body text, NOT \\subsection."""
        blocks = [
            self._make_header(1, "第一章 绪论"),
            {"t": "Header", "c": [3, ["", [], []], [
                {"t": "Math", "c": [{"t": "InlineMath"}, "E = mc^2"]},
                {"t": "Str", "c": " （2-1）"},
            ]]},
        ]
        result = generate_chapter_tex(blocks, 0, 2, "绪论")
        assert "\\subsection" not in result
        assert "$E = mc^2$" in result

    def test_h2_section_number_stripped(self):
        """H2 with '2.2 电磁积分方程' → \\section{电磁积分方程}."""
        blocks = [
            self._make_header(1, "第二章 基本理论"),
            self._make_header(2, "2.2 电磁积分方程"),
        ]
        result = generate_chapter_tex(blocks, 0, 2, "基本理论")
        assert "\\section{电磁积分方程}" in result
        assert "2.2" not in result.split("\\chapter")[1]


# ============================================================
# RE_FIG_NUM pattern tests
# ============================================================

class TestFigNumPattern:
    def test_dash_format(self):
        m = RE_FIG_NUM.match("图2-1 RWG基函数模型示意图")
        assert m
        assert m.group(1) == "2"
        assert m.group(2) == "1"
        assert "RWG" in m.group(3)

    def test_dot_format(self):
        m = RE_FIG_NUM.match("图3.5 test")
        assert m
        assert m.group(1) == "3"
        assert m.group(2) == "5"

    def test_no_space(self):
        m = RE_FIG_NUM.match("图21 caption")
        assert m
        assert m.group(1) == "2"
        assert m.group(2) == "1"

    def test_no_match(self):
        m = RE_FIG_NUM.match("这不是图题")
        assert m is None


# ============================================================
# is_body_text tests (Bug 1 fix)
# ============================================================

class TestIsBodyText:
    """Test body text detection for TOC leakage prevention."""

    def test_short_title_not_body(self):
        assert not is_body_text("矩量法概述")

    def test_section_number_title_not_body(self):
        assert not is_body_text("3.2 实验装置和方法")

    def test_long_paragraph_is_body(self):
        text = "我们使用SMW算法对这个矩阵求逆得到一系列结果表明该方法在实际应用中具有很好的效果。"
        assert is_body_text(text)

    def test_sentence_with_period_is_body(self):
        assert is_body_text("这类问题出现时被积函数就会产生变化。")

    def test_sentence_with_comma_long_is_body(self):
        text = "在当前，本文即将要阐述的转台逆合成孔径成像技术"
        assert is_body_text(text)

    def test_sentence_with_semicolon_is_body(self):
        assert is_body_text("第一步完成；开始第二步")

    def test_short_comma_not_body(self):
        """Short title with comma should NOT be body."""
        assert not is_body_text("3.2 装置方法")

    def test_parentheses_is_body(self):
        assert is_body_text("自适应交叉（ACA）")

    def test_english_text_long_is_body(self):
        text = "The Sherman-Morrison-Woodbury algorithm is used to compute the inverse of this matrix efficiently."
        assert is_body_text(text)

    def test_subsection_title_not_body(self):
        """Real subsection titles should pass through."""
        assert not is_body_text("矩量法原理")
        assert not is_body_text("基函数与测试函数的选择")
        assert not is_body_text("奇异点问题")


# ============================================================
# classify_paragraph body text rejection (Bug 1+5 fix)
# ============================================================

class TestClassifyParagraphBodyRejection:
    """Ensure classify_paragraph rejects body text even if it starts with section numbers."""

    def test_numbered_body_text_rejected(self):
        """'3.4.1 我们使用SMW算法...' should NOT be subsection."""
        text = "3.4.1 我们使用SMW算法对这个矩阵求逆得到一系列结果表明该方法在实际应用中具有很好的效果。"
        result = classify_paragraph(text)
        assert result is None

    def test_real_subsection_accepted(self):
        """'2.4.1 矩量法概述' should be subsection."""
        result = classify_paragraph("2.4.1 矩量法概述")
        assert result is not None
        assert result[0] == "subsection"
        assert result[1] == "矩量法概述"

    def test_real_section_accepted(self):
        result = classify_paragraph("3.2 实验装置和方法")
        assert result is not None
        assert result[0] == "section"
        assert result[1] == "实验装置和方法"

    def test_chapter_always_accepted(self):
        """Chapter titles should never be rejected even if long."""
        text = "第三章 快速直接求解算法及其在电磁散射中的应用与算例分析验证"
        result = classify_paragraph(text)
        assert result is not None
        assert result[0] == "chapter"

    def test_long_section_number_body_rejected(self):
        """Long paragraph starting with section number is body text."""
        text = "4.1 在当前，本文即将要阐述的转台逆合成孔径成像技术是雷达目标散射中心成像诊断的主要方法之一。"
        result = classify_paragraph(text)
        assert result is None


# ============================================================
# Caption prefix stripping (Bug 2 fix)
# ============================================================

class TestCaptionPrefixStripping:
    """Test that figure captions have redundant number prefix stripped."""

    def test_strip_dash_prefix(self):
        text = "图2-1 RWG基函数模型示意图"
        result = RE_CAPTION_NUM_PREFIX.sub("", text).strip()
        assert result == "RWG基函数模型示意图"

    def test_strip_dot_prefix(self):
        text = "图3.5 测试图"
        result = RE_CAPTION_NUM_PREFIX.sub("", text).strip()
        assert result == "测试图"

    def test_no_prefix_unchanged(self):
        text = "RWG基函数模型示意图"
        result = RE_CAPTION_NUM_PREFIX.sub("", text).strip()
        assert result == "RWG基函数模型示意图"

    def test_figure_block_no_double_numbering(self):
        """handle_figure_block should strip caption number prefix."""
        block = _make_figure_block(
            "图2-4 RCS数据对比图",
            "media/image5.png",
            width="3.0in",
        )
        result = handle_figure_block(block)
        assert "\\caption{RCS数据对比图}" in result
        # Should NOT have "图2-4" inside caption
        assert "图2-4" not in result.split("\\caption")[1].split("}")[0]

    def test_figure_block_preserves_label(self):
        """Label should still use the figure number."""
        block = _make_figure_block("图2-4 RCS数据对比图", "media/image5.png")
        result = handle_figure_block(block)
        assert "\\label{fig:2-4}" in result


# ============================================================
# H3 long-text demotion in generate_chapter_tex (Bug 1+5 integration)
# ============================================================

class TestH3LongTextDemotion:
    """Test that H3 blocks with long body text are demoted to paragraphs."""

    def _make_header(self, level, text):
        inlines = [{"t": "Str", "c": text}]
        return {"t": "Header", "c": [level, ["", [], []], inlines]}

    def test_h3_long_body_demoted(self):
        """H3 with sentence text → body paragraph, NOT \\subsection."""
        blocks = [
            self._make_header(1, "第三章 快速直接求解算法"),
            self._make_header(3, "我们使用SMW算法对这个矩阵求逆得到相应的结果以验证算法的正确性。"),
        ]
        result = generate_chapter_tex(blocks, 0, 2, "快速直接求解算法")
        assert "\\subsection" not in result
        assert "SMW算法" in result

    def test_h3_short_title_kept(self):
        """H3 with proper short title → \\subsection."""
        blocks = [
            self._make_header(1, "第二章 基本理论"),
            self._make_header(3, "2.4.1 矩量法概述"),
        ]
        result = generate_chapter_tex(blocks, 0, 2, "基本理论")
        assert "\\subsection{矩量法概述}" in result

    def test_h2_long_body_demoted(self):
        """H2 with sentence text → body paragraph, NOT \\section."""
        blocks = [
            self._make_header(1, "第四章 成像技术"),
            self._make_header(2, "在当前，本文即将要阐述的转台逆合成孔径成像技术是雷达目标散射中心成像诊断的主要方法之一。"),
        ]
        result = generate_chapter_tex(blocks, 0, 2, "成像技术")
        assert "\\section" not in result.split("\\chapter")[1]
        assert "转台逆合成孔径" in result

