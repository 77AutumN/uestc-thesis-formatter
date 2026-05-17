"""tests/test_w3_mutants.py — W3 D40/D41/D42 deterministic mutants 回归测试.

依赖 tests/fixtures/mutant_caption_math.docx + mutant_caption_lookalike.docx
+ mutant_inline_eq.docx (build_w3_mutants.py 产物).
"""
from __future__ import annotations
import os
import sys

import pytest

THIS = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(THIS, "..", "scripts"))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import pandoc_ast_extract as ext  # noqa: E402
import recover_figures as rf  # noqa: E402
import source_manifest as sm  # noqa: E402

FX_CAPTION_MATH = os.path.join(THIS, "fixtures", "mutant_caption_math.docx")
FX_CAPTION_LOOKALIKE = os.path.join(THIS, "fixtures", "mutant_caption_lookalike.docx")
FX_INLINE_EQ = os.path.join(THIS, "fixtures", "mutant_inline_eq.docx")


def _need(p):
    if not os.path.isfile(p):
        pytest.skip(f"fixture missing: {p} (run build_w3_mutants.py)")


# ============================================================
# D40: whole-paragraph inline math → equation
# ============================================================

def test_d40_inline_eq_half_width_match():
    """整段半角 `$x+y$ (3-1)` → equation block."""
    out = ext._maybe_emit_inline_numbered_equation("$x + y = z$ (3-1)")
    assert out is not None
    assert "\\begin{equation}" in out
    assert "x + y = z" in out
    assert "\\tag{3-1}" in out


def test_d40_inline_eq_full_width_match():
    """整段全角 `$a+b$（3-2）` → equation block."""
    out = ext._maybe_emit_inline_numbered_equation("$a + b = c$（3-2）")
    assert out is not None
    assert "\\tag{3-2}" in out


def test_d40_inline_eq_negative_inline_ref():
    """正文 inline ref `如式 $x+y$ (3-1) 所示` 不应匹配 (整段锚定要求)."""
    out = ext._maybe_emit_inline_numbered_equation("如式 $x+y$ (3-1) 所示")
    assert out is None


def test_d40_inline_eq_negative_no_math():
    """无 inline math 不匹配."""
    assert ext._maybe_emit_inline_numbered_equation("正文段 (3-1)") is None


# ============================================================
# D41: caption Math (oMath) recovery
# ============================================================

def test_d41_caption_oMath_recovered_in_paragraph_text():
    """recover_figures._text_of_paragraph 抓 <m:oMath> 内 <m:t> 拼 $...$."""
    _need(FX_CAPTION_MATH)
    paras, _ = rf.parse_docx(FX_CAPTION_MATH)
    # 找 caption 段
    cap_text = None
    for p in paras:
        if p["text"].startswith("图3-4"):
            cap_text = p["text"]
            break
    assert cap_text is not None
    assert "$" in cap_text  # math part 已被 $ 包裹
    assert "Δτ" in cap_text or "|" in cap_text


def test_d41_source_manifest_has_omath_field():
    """source_manifest paragraphs 含 has_omath / contains_inline_math 字段."""
    _need(FX_CAPTION_MATH)
    m = sm.build_probe_manifest(FX_CAPTION_MATH)
    has_omath_count = sum(1 for p in m["paragraphs"] if p.get("has_omath"))
    assert has_omath_count >= 1


# ============================================================
# D42: caption-lookalike body strip
# ============================================================

def test_d42_caption_role_classifier_sentence_long():
    """长段 + 句末标点 + 触发词 → caption_lookalike_body."""
    _need(FX_CAPTION_LOOKALIKE)
    m = sm.build_probe_manifest(FX_CAPTION_LOOKALIKE)
    lookalike = [p for p in m["paragraphs"]
                 if p.get("caption_role") == "caption_lookalike_body"]
    assert len(lookalike) >= 1
    assert any("给出" in p["text"] for p in lookalike)


def test_d42_caption_role_classifier_short_anchor():
    """短 caption 段 → caption_anchor."""
    _need(FX_CAPTION_LOOKALIKE)
    m = sm.build_probe_manifest(FX_CAPTION_LOOKALIKE)
    anchors = [p for p in m["paragraphs"]
               if p.get("caption_role") == "caption_anchor"]
    assert len(anchors) >= 1
    # 短 caption 段 "图3-4：测试 caption" 应是 anchor
    assert any("图3-4" in p["text"] and "给出" not in p["text"] for p in anchors)
