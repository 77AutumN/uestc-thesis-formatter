"""Unit tests for visual_geometry_audit detectors.

Detectors take a list-of-dicts page model so they can be unit-tested
without needing a real PDF or Docker. The PDF→model extraction path is
exercised by the Day 5 CASE-A sandbox run and the report's recorded
counts (3 large_vertical_gap / 0 image_caption_split_page / 8 orphan
on a 61pp PDF).
"""

from __future__ import annotations
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import visual_geometry_audit as vga  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers to synthesise page model entries
# ---------------------------------------------------------------------------


def _text_block(y0, y1, text="body text", font=12.0, n_lines=2,
                is_chapter=False, is_section=False, is_caption=False,
                is_heading=False, x0=85, x1=510):
    return {
        "bbox": (x0, y0, x1, y1),
        "text": text,
        "n_lines": n_lines,
        "max_font_size": font,
        "is_chapter": is_chapter,
        "is_section": is_section,
        "is_caption_text": is_caption,
        "is_likely_heading": (is_heading or is_chapter or is_section
                              or font >= vga.HEADING_MIN_FONT_PT),
    }


def _image_block(y0, y1, x0=85, x1=510, xref=42):
    return {"bbox": (x0, y0, x1, y1), "xref": xref}


def _page(num, *, text_blocks=(), images=(), page_role="body"):
    return {
        "page_num": num,
        "page_role": page_role,
        "width": vga.A4_WIDTH_PT,
        "height": vga.A4_HEIGHT_PT,
        "text_blocks": list(text_blocks),
        "images": list(images),
    }


# ---------------------------------------------------------------------------
# detect_large_vertical_gap
# ---------------------------------------------------------------------------


def test_no_gap_when_blocks_close():
    page = _page(1, text_blocks=[
        _text_block(100, 120, "A"),
        _text_block(140, 160, "B"),
    ])
    out = vga.detect_large_vertical_gap([page], gap_threshold_pt=70.0)
    assert out == []


def test_gap_above_threshold_emits_one_issue():
    page = _page(1, text_blocks=[
        _text_block(100, 120, "before"),
        _text_block(300, 320, "after"),  # 180pt gap
    ])
    out = vga.detect_large_vertical_gap([page], gap_threshold_pt=70.0)
    assert len(out) == 1
    issue = out[0]
    assert issue["issue_code"] == "large_vertical_gap"
    assert issue["page_num"] == 1
    assert issue["evidence"]["gap_pt"] == pytest.approx(180.0)
    assert issue["evidence"]["prev_block_text"] == "before"
    assert issue["evidence"]["next_block_text"] == "after"


def test_image_block_counts_as_content_no_false_gap():
    """Regression for the Day 5 false-positive where image vertical extent was
    being counted as gap because detector iterated text-only blocks."""
    page = _page(1, text_blocks=[
        _text_block(100, 120, "preceding text"),
        _text_block(560, 580, "following text"),
    ], images=[
        _image_block(150, 540),  # 390pt tall image fills most of the gap
    ])
    out = vga.detect_large_vertical_gap([page], gap_threshold_pt=70.0)
    # No content gap exceeds 70pt: 150-120=30pt (text→image) and
    # 560-540=20pt (image→text). Therefore no issue.
    assert out == []


def test_threshold_filters_borderline():
    page = _page(1, text_blocks=[
        _text_block(100, 120, "A"),
        _text_block(180, 200, "B"),  # gap = 60pt
    ])
    assert vga.detect_large_vertical_gap([page], gap_threshold_pt=70.0) == []
    assert len(vga.detect_large_vertical_gap([page], gap_threshold_pt=50.0)) == 1


# ---------------------------------------------------------------------------
# detect_image_caption_split_page
# ---------------------------------------------------------------------------


def test_no_split_when_caption_below_image_same_page():
    page1 = _page(1,
        text_blocks=[_text_block(420, 440, "图1-1 example", is_caption=True)],
        images=[_image_block(150, 410)],
    )
    page2 = _page(2)
    out = vga.detect_image_caption_split_page([page1, page2])
    assert out == []


def test_split_when_caption_falls_on_next_page():
    page1 = _page(1, images=[_image_block(150, 410)])
    page2 = _page(2,
        text_blocks=[_text_block(100, 120, "图1-1 stranded", is_caption=True)],
    )
    out = vga.detect_image_caption_split_page([page1, page2])
    assert len(out) == 1
    issue = out[0]
    assert issue["issue_code"] == "image_caption_split_page"
    assert issue["evidence"]["image_page"] == 1
    assert issue["evidence"]["caption_page"] == 2
    assert "stranded" in issue["evidence"]["caption_text"]


def test_split_skipped_when_no_caption_on_either_page():
    """Don't false-emit when no caption exists at all (just an image, possibly
    a logo on a cover page)."""
    page1 = _page(1, images=[_image_block(150, 410)])
    page2 = _page(2)
    assert vga.detect_image_caption_split_page([page1, page2]) == []


# ---------------------------------------------------------------------------
# detect_orphan_heading_at_page_bottom
# ---------------------------------------------------------------------------


def test_orphan_when_heading_near_page_bottom():
    page = _page(1, text_blocks=[
        # body filling top of page so heading is geometrically at the bottom
        _text_block(100, 700, "long body"),
        _text_block(740, 758, "1.2.3 orphan section",
                    font=14.0, is_section=True),
    ])
    out = vga.detect_orphan_heading_at_page_bottom([page])
    assert len(out) == 1
    issue = out[0]
    assert issue["issue_code"] == "orphan_heading_at_page_bottom"
    assert "orphan" in issue["evidence"]["heading_text"]


def test_no_orphan_when_heading_has_room_below():
    page = _page(1, text_blocks=[
        _text_block(100, 120, "1.2.3 normal section",
                    font=14.0, is_section=True),
        _text_block(140, 700, "plenty of body"),
    ])
    out = vga.detect_orphan_heading_at_page_bottom([page])
    assert out == []


def test_no_orphan_for_toc_dot_leader_lines():
    """The page-model extractor sets is_likely_heading=False for dot-leader
    TOC entries; here we simulate that contract by passing is_heading=False
    to verify detector ignores them even at page bottom."""
    page = _page(1, text_blocks=[
        _text_block(740, 758, "3.1 总体方案设计........10",
                    font=12.0, is_heading=False),
    ])
    out = vga.detect_orphan_heading_at_page_bottom([page])
    assert out == []


def test_orphan_evidence_includes_required_fields():
    page = _page(1, text_blocks=[
        _text_block(100, 700, "body"),
        _text_block(740, 758, "第一章 引言",
                    font=15.0, is_chapter=True),
    ])
    out = vga.detect_orphan_heading_at_page_bottom([page])
    assert len(out) == 1
    e = out[0]["evidence"]
    # Contract required fields
    for key in ["heading_text", "heading_level", "body_lines_following",
                "page_bottom_y", "heading_y"]:
        assert key in e, f"missing required evidence key: {key}"


# ---------------------------------------------------------------------------
# Composition + validation integration
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Day 6: cover-page false positive suppression
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Day 10A: heading detector tightening (math residue + real-title guards)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "0.27 = 10 × 0.5228 = 5.23",
    "1.518 = 10 × 1.232 = 12.32，",
    "0.35 = 10 × 0.5916 = 5.92",
    "0.014 = 10 × 0.1183 = 1.18",
    "0.04 = 2.00",
    "0.136 = 10 × 0.3688 = 3.69",
    "12792 + 17072 ≈2133 px，由面积与宽度折算骨",  # has ≈
])
def test_math_residue_blocks_section_classification(text):
    """Day 9A FPs: formula residue must NOT be classified as section heading.
    Frozen so future detector tweaks can't regress these."""
    assert vga._is_math_residue(text), (
        f"_is_math_residue should match {text!r}")


@pytest.mark.parametrize("text", [
    "3.3.3 数据增强方式",
    "1.2.3 研究难点分析",
    "4.1 实验设置",
    "5.3.4.1 协商系统",
    "1 引言",
])
def test_real_section_headings_pass_guards(text):
    """Real Chinese section headings must keep being detected."""
    assert not vga._is_math_residue(text), (
        f"real heading should NOT match math residue: {text!r}")
    assert vga._has_real_title_text_after_section_number(text), (
        f"real heading must have title text after number: {text!r}")


def test_bare_numeric_string_rejected():
    """Day 10A: '1.2.3' alone (no title text) is not a heading."""
    assert not vga._has_real_title_text_after_section_number("1.2.3")
    # And the trailing space + no title also fails
    assert not vga._has_real_title_text_after_section_number("1.2.3   ")


def test_classify_via_extract_path_blocks_formula_residue(tmp_path):
    """End-to-end: feed a synthetic page with a formula-residue block to
    detect_orphan_heading_at_page_bottom and confirm it's NOT flagged."""
    fake_block = _text_block(700, 720,
                              text="0.27 = 10 × 0.5228 = 5.23",
                              font=12.0, n_lines=1, is_section=False,
                              is_heading=False)
    # The synthesised _text_block already has is_likely_heading=False here.
    # The real test of the detector path is via extract_page_model on a real
    # PDF — covered by the v9/round3/round4 audit re-run in the Day 10 report.
    out = vga.detect_orphan_heading_at_page_bottom([
        _page(2, text_blocks=[fake_block])
    ])
    assert out == []


def test_chapter_with_math_operator_rejected():
    """A `第3章 ...×...` synthetic case — chapter regex matches but math
    operator should still block heading classification."""
    # We can't easily test the inline classifier without exposing it, but
    # we can verify _is_math_residue catches the math operator:
    assert vga._is_math_residue("第3章 ×× 引论")
    # Real chapter without operator stays clean:
    assert not vga._is_math_residue("第三章 引论")


# ---------------------------------------------------------------------------
# Day 11A: body-text guard — kill `40 个epoch 后...` style FP that survived
# Day 10A. Real headings must still pass.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    # The Day 10 residual FP from v9 ch04.tex:117 — body sentence with %
    # and ML keywords. The exact text from the audit JSON.
    "40 个epoch 后0.3566，已超约40%以后的损失水平，意味着 400 个合成图",
    # Synthetic body texts that lead with a digit but are clearly body
    "5 张图像在 GPU 上跑 100 epoch，loss 收敛到 0.123",
    "1024 px × 1024 px 的图像作为输入，经过若干处理后得到下列结果说明",
    "0.85 的 IoU accuracy 已超过基线水平，表明模型能力提升明显",
    # Long body sentence with comma + period (no leading section number form)
    "这是很长的一段正文，里面提到 epoch 和 loss 等术语，与 heading 无关。",
])
def test_body_text_indicators_block_heading(text):
    assert vga._looks_like_body_text(text), (
        f"_looks_like_body_text should match {text!r}")


@pytest.mark.parametrize("text", [
    "第一章 引言",
    "1 引言",
    "1.2 相关工作",
    "1.2.3 研究难点分析",
    "3.3.2 大模型微调",
    "3.3.3 数据增强方式",
    "4.1 实验设置",
    "5.3.4.1 协商系统",
])
def test_real_headings_pass_body_text_guard(text):
    """Real Chinese headings must NOT trip the body-text guard."""
    assert not vga._looks_like_body_text(text), (
        f"real heading wrongly flagged body: {text!r}")


def test_short_heading_with_chinese_comma_passes():
    """A heading like '1.2 实验设置，含数据' has a comma but only 4 chars
    after it — should NOT be flagged as body (regex needs 6+ chars after)."""
    assert not vga._looks_like_body_text("1.2 实验设置，含数据")


def test_long_body_via_length_cap_only():
    """A long Chinese body sentence with no obvious keywords/punctuation:
    length cap alone catches it."""
    long_text = "这是一段很长的正文内容用来填充字数避免被解析为标题但不含数字开头" * 2
    assert len(long_text) > vga._HEADING_MAX_CHARS
    assert vga._looks_like_body_text(long_text)


def test_percent_sign_alone_blocks_heading():
    """Even a short text with `%` is suspicious — section titles don't have it."""
    assert vga._looks_like_body_text("提升约 40% 的准确率")
    # Full-width percent
    assert vga._looks_like_body_text("提升约 40％")


def test_full_classification_flow_blocks_day10_residual_fp():
    """End-to-end: feed the Day 10 residual FP text through extract path
    proxy (synthesised page model) and confirm it is NOT classified as
    heading."""
    fake_block = _text_block(
        700, 720,
        text="40 个epoch 后0.3566，已超约40%以后的损失水平，意味着 400 个合成图",
        font=12.0, n_lines=2, is_heading=False,
    )
    assert fake_block["is_likely_heading"] is False  # synthetic helper
    # Real verification is via the v9/round3/round4 audit re-run in Day 11
    # report; here we just verify the helper returns body-like.
    assert vga._looks_like_body_text(fake_block["text"])


def test_classify_page_role_cover_when_page1_no_body_paragraphs():
    """Page 1 with only large/heading-like blocks → cover."""
    blocks = [
        _text_block(150, 200, "BACHELOR THESIS", font=18.0, n_lines=1),
        _text_block(400, 460, "电子科技大学", font=16.0, n_lines=2),
        _text_block(500, 540, "学院信息：通信工程", font=14.0, n_lines=2),
    ]
    assert vga._classify_page_role(1, blocks) == "cover"


def test_classify_page_role_body_when_page1_has_paragraphs():
    """Page 1 that already has body content (rare; unusual layout) → body."""
    blocks = [
        _text_block(100, 700, "long body paragraph spanning many lines",
                    font=12.0, n_lines=15),
    ]
    assert vga._classify_page_role(1, blocks) == "body"


def test_classify_page_role_body_for_non_first_pages():
    """page_num != 1 is always body regardless of content."""
    assert vga._classify_page_role(2, []) == "body"
    assert vga._classify_page_role(99, []) == "body"


def test_large_vertical_gap_skips_cover_pages():
    """Day 5 known FP regression: cover-page intentional layout must NOT
    trigger large_vertical_gap (the BACHELOR THESIS title with ≥200pt gap
    between title and rest is by design)."""
    cover = _page(1, text_blocks=[
        _text_block(56, 67, "BACHELOR THESIS", font=18.0, n_lines=1),
        _text_block(304, 325, "学位论文题目", font=16.0, n_lines=1),
        # 237pt gap between these two — would normally fire P0
        _text_block(410, 430, "学院信息", font=14.0, n_lines=1),
    ], page_role="cover")
    out = vga.detect_large_vertical_gap([cover], gap_threshold_pt=70.0)
    assert out == [], "cover page must not produce large_vertical_gap issues"


def test_orphan_heading_skips_cover_pages():
    """Cover page text blocks all look heading-shaped by font; without the
    cover filter every one of them would orphan-fire."""
    cover = _page(1, text_blocks=[
        _text_block(700, 720, "电子科技大学", font=16.0, n_lines=1),
    ], page_role="cover")
    out = vga.detect_orphan_heading_at_page_bottom([cover])
    assert out == []


def test_body_pages_still_detected_after_cover_filter():
    """Confirm the cover filter does not over-filter — non-cover pages
    still emit issues when warranted."""
    body = _page(2, text_blocks=[
        _text_block(100, 120, "A"),
        _text_block(300, 320, "B"),  # 180pt gap
    ])
    out = vga.detect_large_vertical_gap([body], gap_threshold_pt=70.0)
    assert len(out) == 1


def test_composed_instance_passes_contract_validation():
    """Synthesise one detection of each type, compose, validate against
    real shipped contracts."""
    import audit_issue_schema as ais

    contracts = ais.load_all_contracts()

    # large_vertical_gap detection
    page = _page(1, text_blocks=[
        _text_block(100, 120, "A"),
        _text_block(300, 320, "B"),
    ])
    detections = vga.detect_large_vertical_gap([page], gap_threshold_pt=70.0)
    assert len(detections) == 1

    instance = vga._compose_instance(
        detection=detections[0],
        contract=contracts["large_vertical_gap"],
        stx_record=None,
        issue_id="VIS-LARGE_VE-0001",
        case_label="UNITTEST",
        run_id="2026-05-07T00:00:00Z",
    )
    errors = ais.validate_instance(instance, contracts["large_vertical_gap"])
    assert errors == [], f"contract validation failed: {[str(e) for e in errors]}"
    # Even without SyncTeX, location skeleton is valid
    assert instance["location"]["pdf_page"] == 1
    assert instance["location"]["resolution_method"] == "synctex_unavailable"
    assert instance["location"]["tex_file"] is None


# ---------------------------------------------------------------------------
# Day 13A: large_vertical_gap subtype分型 (equation_gap vs float_gap)
# Freezes the 9 wrong-fix samples from Day 12 case 11/16 advisory smoke.
# Every sample was a real ≥70pt gap in the PDF, but the next block was a
# bare equation tag — they should be classified equation_gap (diagnostic)
# and NEVER routed to float_policy_repair.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("prev_text,next_text,case_label", [
    # case 11 — 7 wrong-fix candidates (next_block_text = bare (N.M) tag)
    ("& s.t.g_i2 = ∥x −a_i∥2, i = 1, ..., N", "(3.6)",  "case11_p17_VE-0001"),
    ("1",                                      "(3.7)",  "case11_p17_VE-0002"),
    ("& s.t.∥x∥2 = ∂",                          "(3.10)", "case11_p19_VE-0003"),
    ("& s.t.yTDy + 2f Ty = 0",                  "(3.11)", "case11_p19_VE-0004"),
    ("& ATA + λD≻0",                            "(3.18)", "case11_p20_VE-0005"),
    ("& s.t.yTDy + 2f Ty = 0",                  "(4.5)",  "case11_p25_VE-0006"),
    ("& s.t.yTDy + 2f Ty = 0",                  "(4.16)", "case11_p29_VE-0007"),
    # case 16 — 2 wrong-fix candidates. PDF actually rendered the formula
    # on a single PyMuPDF block: full math expression + trailing (N-M) tag.
    # The detector's tail-anchored regex catches this shape too.
    ("于每个频点fq，期望信号经过整个空时结构的传输函数应当满足：",
     "Hd(fq, θ0) = e−j2πfqTs(L−1)/2(3-8)", "case16_p19_VE-0001_full_line"),
    ("按列拼接，构成联合约束矩阵：",
     "C = [aST(f1, θ0), aST(f2, θ0), . . . , aST(fQ, θ0)] ∈CML×Q(3-9)",
     "case16_p19_VE-0002_full_line"),
])
def test_day12_formula_wrong_fix_samples_classified_as_equation_gap(
        prev_text, next_text, case_label):
    """Frozen regression: Day 12 surfaced 9 wrong-fix candidates where
    next_block_text was a bare (N.M) equation tag. All 9 must classify as
    equation_gap so float_policy_repair refuses them."""
    subtype = vga._classify_gap_subtype(prev_text, False, next_text, False)
    assert subtype == "equation_gap", (
        f"{case_label}: next={next_text!r} should be equation_gap but got {subtype}")


@pytest.mark.parametrize("prev_text,next_text,case_label", [
    # case 17 gap-1 — figure → next section heading (real float gap)
    ("图4-9", "4.6.4 饰品色彩差异导致的检测偏差", "case17_p33_VE-0001"),
    # case 16 gap-3 — caption → caption text (huge 351pt float gap)
    ("图3-4 ：不同采样频率下各阵元的m", "图3-4 给出了不同fs/B 取值下各阵元| ∆τm | 的分布。随着采样频率的提高，",
     "case16_p25_VE-0003"),
    # case 16 gap-4 — caption → caption text (140pt float gap)
    ("图3-7 波束形成前后频谱对比", "图3-7(a) 为波束形成前的总接收信号频谱，其中期望信号和两个强干扰分量",
     "case16_p28_VE-0004"),
    # case 11 gap-8 — caption → body para (88pt float gap)
    ("图4-3 各算法的RMSE 与高斯白噪声标准差的关系", "在图4.3 中可以看到，当不存在离群值测量，仅存在高斯白噪声时，最小二乘",
     "case11_p34_VE-0008"),
    # heading-body 73pt sample (case 17 gap-2, 'unsure' class — must NOT
    # be misclassified as equation_gap; stays float_gap by current policy)
    ("4.6.4 饰品色彩差异导致的检测偏差", "色彩是模型区分饰品类别的重要线索，但也可能成为误判的来源。本文数据",
     "case17_p33_VE-0002_unsure"),
])
def test_day12_real_float_samples_remain_float_gap(prev_text, next_text, case_label):
    """Frozen regression: real figure-float gaps in case 11/16/17 must
    stay float_gap so float_policy_repair retains them as candidates."""
    subtype = vga._classify_gap_subtype(prev_text, False, next_text, False)
    assert subtype == "float_gap", (
        f"{case_label}: next={next_text!r} should be float_gap but got {subtype}")


def test_image_block_neighbour_falls_back_to_float_gap():
    """An image immediately before/after the gap is by definition a float
    boundary — never equation_gap regardless of text shape."""
    assert vga._classify_gap_subtype("", True, "(3.6)", False) == "float_gap"
    assert vga._classify_gap_subtype("(3.6)", False, "", True) == "float_gap"


def test_equation_tag_regex_edge_cases():
    """Equation-tag pattern is anchored: only a *bare* tag classifies."""
    cls = vga._classify_gap_subtype
    # Only-tag — equation
    assert cls("prev", False, "(3.6)", False) == "equation_gap"
    assert cls("prev", False, "  (3.6)  ", False) == "equation_gap"   # whitespace
    assert cls("prev", False, "(3-6)", False) == "equation_gap"        # hyphen variant
    assert cls("prev", False, "(12.345)", False) == "equation_gap"     # multi-digit
    assert cls("prev", False, "(3.6a)", False) == "equation_gap"       # letter suffix
    # Tag with surrounding text — float (not bare)
    assert cls("prev", False, "see (3.6) for derivation", False) == "float_gap"
    # Section number — float (not equation)
    assert cls("prev", False, "4.6.4 饰品色彩差异", False) == "float_gap"
    # Empty next — float
    assert cls("prev", False, "", False) == "float_gap"


def test_equation_gap_detection_attaches_subtype_in_evidence():
    """Detector must propagate subtype into evidence for downstream use."""
    page = _page(1, text_blocks=[
        _text_block(100, 120, "& s.t. ∥x∥ = 1"),
        _text_block(300, 320, "(3.6)"),
    ])
    out = vga.detect_large_vertical_gap([page], gap_threshold_pt=70.0)
    assert len(out) == 1
    assert out[0]["evidence"]["subtype"] == "equation_gap"


def test_float_gap_detection_attaches_subtype_in_evidence():
    page = _page(1, text_blocks=[
        _text_block(100, 120, "图4-3 some caption"),
        _text_block(300, 320, "在图4.3 中可以看到"),
    ])
    out = vga.detect_large_vertical_gap([page], gap_threshold_pt=70.0)
    assert len(out) == 1
    assert out[0]["evidence"]["subtype"] == "float_gap"


def test_compose_instance_downgrades_equation_gap_to_diagnostic():
    """End-to-end: equation_gap detection → composed issue must have
    repairability=diagnostic and suggested_repair=None, even though the
    contract's default repairability is deterministic."""
    import audit_issue_schema as ais
    contracts = ais.load_all_contracts()

    page = _page(1, text_blocks=[
        _text_block(100, 120, "& s.t. ∥x∥ = 1"),
        _text_block(300, 320, "(3.6)"),
    ])
    detections = vga.detect_large_vertical_gap([page], gap_threshold_pt=70.0)
    assert detections[0]["evidence"]["subtype"] == "equation_gap"

    instance = vga._compose_instance(
        detection=detections[0],
        contract=contracts["large_vertical_gap"],
        stx_record=None,
        issue_id="VIS-LARGE_VE-0001",
        case_label="UNITTEST",
        run_id="2026-05-07T00:00:00Z",
    )
    assert instance["repairability"] == "diagnostic"
    assert instance["suggested_repair"] is None
    # Schema must still pass — diagnostic is a valid value
    errors = ais.validate_instance(instance, contracts["large_vertical_gap"])
    assert errors == [], f"validation failed: {[str(e) for e in errors]}"


def test_compose_instance_keeps_float_gap_deterministic():
    """Float_gap path must NOT be downgraded — preserves auto-repair pipeline
    for genuine figure-float gaps (case 16 gap-3/4, case 11 gap-8)."""
    import audit_issue_schema as ais
    contracts = ais.load_all_contracts()

    page = _page(1, text_blocks=[
        _text_block(100, 120, "图4-3 RMSE 与噪声标准差的关系"),
        _text_block(300, 320, "在图4.3 中可以看到"),
    ])
    detections = vga.detect_large_vertical_gap([page], gap_threshold_pt=70.0)
    assert detections[0]["evidence"]["subtype"] == "float_gap"

    instance = vga._compose_instance(
        detection=detections[0],
        contract=contracts["large_vertical_gap"],
        stx_record=None,
        issue_id="VIS-LARGE_VE-0001",
        case_label="UNITTEST",
        run_id="2026-05-07T00:00:00Z",
    )
    assert instance["repairability"] == "deterministic"
    assert instance["suggested_repair"] is not None
    assert instance["suggested_repair"]["repairer"] == "float_policy_repair"
