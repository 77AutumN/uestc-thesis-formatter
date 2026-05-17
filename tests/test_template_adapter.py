#!/usr/bin/env python3
"""
test_template_adapter.py — DissertUESTC Template Adapter 回归测试

覆盖范围（来自 Codex Q2 Required Checks）：
  1. 正向断言：各 emit_* 产出正确的新模板命令
  2. 负向断言：产出中不允许出现旧模板残留 token
  3. class option 映射：bachelor / master / promaster / doctor
  4. nonprint / review 标志注入
  5. 马院 (categorized) vs 标准 (standard) 参考文献分支
  6. 元数据 fallback 机制
"""

import json
import os
import sys
import tempfile
import pytest

# 让 pytest 能找到 scripts/ 目录
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from template_adapter import (
    FORBIDDEN_LEGACY_TOKENS,
    assemble_main_tex,
    emit_abstract_en,
    emit_abstract_zh,
    emit_achievement,
    emit_acknowledgement,
    emit_bibliography_categorized,
    emit_bibliography_standard,
    emit_chapter_inputs,
    emit_conclusion,
    emit_cover,
    emit_declaration,
    emit_documentclass,
    emit_en_titlepage,
    emit_toc,
    emit_zh_titlepage,
    load_metadata,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def master_meta():
    """标准硕士论文元数据 (case009 马院)"""
    return {
        "title_cn": "华北抗日根据地小学教育经费工作研究",
        "title_en": "Research on the Funding of Primary Education in the North China Base Areas",
        "author_cn": "张三",
        "author_en": "Zhang San",
        "student_id": "202321180153",
        "major_cn": "马克思主义理论",
        "major_en": "Marxist Theory",
        "school_cn": "马克思主义学院",
        "school_en": "School of Marxism",
        "advisor_name_cn": "李四",
        "advisor_title_cn": "教授",
        "advisor_unit": "电子科技大学",
        "advisor_unit_addr": "成都",
        "advisor_en": "Prof. Li Si",
        "degree_type": "master",
        "cls_num": "D64",
        "udc": "320",
        "submit_date": "2026年4月",
        "defense_date": "2026年5月",
        "grant_unit": "电子科技大学",
        "grant_date": "2026年6月",
    }


@pytest.fixture
def bachelor_meta(master_meta):
    """学士论文元数据"""
    m = master_meta.copy()
    m["degree_type"] = "bachelor"
    return m


@pytest.fixture
def minimal_meta():
    """最小元数据（只有旧提取器产出的 7 个字段）"""
    return {
        "major_cn": "马克思主义理论",
        "school_cn": "马克思主义学院",
        "title_cn": "某研究",
        "major_en": "Marxist Theory",
        "student_id": "202321180153",
        "school_en": "School of Marxism",
        "title_en": "Some Research",
    }


# =============================================================================
# Phase 1: documentclass option mapping
# =============================================================================

class TestDocumentClass:
    @pytest.mark.parametrize("degree,expected_opt", [
        ("bachelor", "bachelor"),
        ("master", "master"),
        ("promaster", "promaster"),
        ("doctor", "doctor"),
    ])
    def test_degree_mapping(self, degree, expected_opt):
        meta = {"degree_type": degree}
        result = emit_documentclass(meta)
        assert f"\\documentclass[{expected_opt}," in result
        assert "DissertUESTC" in result

    def test_nonprint_flag(self):
        meta = {"degree_type": "master"}
        result = emit_documentclass(meta, print_mode="nonprint")
        assert "nonprint" in result

    def test_review_flag(self):
        meta = {"degree_type": "master"}
        result = emit_documentclass(meta, print_mode="review")
        assert "review" in result

    def test_no_legacy_class(self):
        meta = {"degree_type": "master"}
        result = emit_documentclass(meta)
        assert "thesis-uestc" not in result


# =============================================================================
# Phase 2: Cover
# =============================================================================

class TestCover:
    def test_cover_has_all_fields(self, master_meta):
        result = emit_cover(master_meta)
        assert "\\uestccover" in result
        assert master_meta["title_cn"] in result
        assert master_meta["major_cn"] in result
        assert master_meta["student_id"] in result
        assert master_meta["author_cn"] in result
        assert master_meta["advisor_name_cn"] in result
        assert master_meta["advisor_title_cn"] in result
        assert master_meta["school_cn"] in result

    def test_no_legacy_makecover(self, master_meta):
        result = emit_cover(master_meta)
        assert "\\makecover" not in result


# =============================================================================
# Phase 3: Title pages
# =============================================================================

class TestTitlePages:
    def test_zh_titlepage_master(self, master_meta):
        result = emit_zh_titlepage(master_meta)
        assert "\\ClsNum" in result
        assert "\\UDC" in result
        assert "\\DissertationTitle" in result
        assert "\\Author" in result
        assert "\\Supervisor" in result
        assert "\\Major" in result
        assert "\\Date" in result
        assert "\\Grant" in result
        assert "\\uestczhtitlepage" in result

    def test_zh_titlepage_bachelor_skipped(self, bachelor_meta):
        result = emit_zh_titlepage(bachelor_meta)
        assert "\\uestczhtitlepage" not in result
        assert "学士" in result

    def test_en_titlepage_master(self, master_meta):
        result = emit_en_titlepage(master_meta)
        assert "\\uestcentitlepage" in result
        assert master_meta["title_en"] in result

    def test_en_titlepage_bachelor_skipped(self, bachelor_meta):
        result = emit_en_titlepage(bachelor_meta)
        assert "\\uestcentitlepage" not in result

    def test_declaration_master(self, master_meta):
        result = emit_declaration(master_meta)
        assert "\\declaration" in result

    def test_declaration_bachelor_skipped(self, bachelor_meta):
        result = emit_declaration(bachelor_meta)
        assert "\\declaration" not in result


# =============================================================================
# Phase 4: Abstracts
# =============================================================================

class TestAbstracts:
    def test_zh_abstract(self):
        result = emit_abstract_zh("这是摘要内容", "关键词1；关键词2")
        assert "\\zhabstract" in result
        assert "\\zhkeywords{关键词1；关键词2}" in result
        assert "这是摘要内容" in result
        # Negative: no legacy
        assert "chineseabstract" not in result
        assert "\\chinesekeyword" not in result

    def test_en_abstract(self):
        result = emit_abstract_en("This is abstract", "kw1; kw2")
        assert "\\enabstract" in result
        assert "\\enkeywords{kw1; kw2}" in result
        assert "englishabstract" not in result


# =============================================================================
# CASE-A round 4 lun51 fix: 关键词分隔符 → 全角逗号 (zh) / 分号 (en)
# =============================================================================

class TestKeywordSeparator:
    """parse_abstract_text 应在抽取后归一化关键词分隔符 (规范要求 ZH '，').

    防 lun51 严重错误 "关键词分隔符 { 、 } 不符合规范要求 { ， }".
    """

    def test_zh_keywords_dunhao_to_full_comma(self):
        """ZH: 顿号 '、' → 全角逗号 '，' (CASE-A 实战触发场景)."""
        from template_adapter import parse_abstract_text
        text = "正文段。\n关键词：到达时间定位、稳健统计、最小二乘法、离群观测"
        _, kw = parse_abstract_text(text, "zh")
        assert kw == "到达时间定位，稳健统计，最小二乘法，离群观测"
        assert "、" not in kw

    def test_zh_keywords_mixed_separators(self):
        """ZH: 多种混杂分隔符 (中英分号/半角逗号/顿号) 全归一."""
        from template_adapter import parse_abstract_text
        text = "正文。\n关键词: A、B；C;D,E,F"
        _, kw = parse_abstract_text(text, "zh")
        assert kw == "A，B，C，D，E，F"

    def test_en_keywords_use_comma(self):
        """EN: 任意分隔符 → ', ' (CASE-A lun51 本科规范明确, 旧 ';' 不符)."""
        from template_adapter import parse_abstract_text
        text = "Body.\nKeywords: TOA、robust、least-squares"
        _, kw = parse_abstract_text(text, "en")
        assert kw == "TOA, robust, least-squares"

    def test_zh_keywords_already_correct_idempotent(self):
        """ZH: 已是 '，' 分隔的不应被破坏 (幂等)."""
        from template_adapter import parse_abstract_text
        text = "正文。\n关键词：A，B，C"
        _, kw = parse_abstract_text(text, "zh")
        assert kw == "A，B，C"

    def test_empty_keywords_pass_through(self):
        """空关键词不报错."""
        from template_adapter import parse_abstract_text
        text = "正文不带关键词"
        _, kw = parse_abstract_text(text, "zh")
        assert kw == ""


# =============================================================================
# Phase 5: Back matter
# =============================================================================

class TestBackMatter:
    def test_acknowledgement(self):
        result = emit_acknowledgement()
        assert "\\acknowledgement" in result
        assert "\\thesisacknowledgement" not in result

    def test_achievement(self):
        result = emit_achievement()
        assert "\\achievement" in result
        assert "\\thesisaccomplish" not in result

    def test_conclusion(self):
        result = emit_conclusion()
        assert "\\input{misc/conclusion}" in result

    def test_toc(self):
        result = emit_toc()
        assert "\\tableofcontents" in result
        assert "\\thesistableofcontents" not in result


# =============================================================================
# Phase 6: Bibliography branches
# =============================================================================

class TestBibliography:
    def test_standard_bib(self):
        result = emit_bibliography_standard("ref")
        assert "\\bibliography{ref}" in result

    def test_categorized_bib_has_chapter_heading(self):
        result = emit_bibliography_categorized()
        assert "\\chapter*{参考文献}" in result
        assert "\\addcontentsline{toc}{chapter}{参考文献}" in result
        assert "\\markboth{参考文献}" in result
        assert "\\input{bibliography_categorized}" in result


# =============================================================================
# Phase 7: Full assembly — snapshot tests
# =============================================================================

class TestFullAssembly:
    def test_standard_assembly(self, master_meta):
        result = assemble_main_tex(
            meta=master_meta,
            chapter_files=["chapter/ch01", "chapter/ch02"],
            abstract_zh_body="摘要正文",
            abstract_zh_keywords="关键词",
            abstract_en_body="Abstract body",
            abstract_en_keywords="keywords",
            bib_mode="standard",
        )
        # Positive checks (D28 升 shared 后 documentclass 总加 noreminder)
        assert "\\documentclass[master, nonprint, noreminder]{DissertUESTC}" in result
        # D27 shared (本科/硕士/博士都加 cite 上标重定向, marxism 不加)
        assert "\\let\\origcite=\\cite" in result
        assert "\\renewcommand{\\cite}[1]{\\textsuperscript{\\origcite{#1}}}" in result
        assert "\\uestccover" in result
        assert "\\uestczhtitlepage" in result
        assert "\\uestcentitlepage" in result
        assert "\\declaration" in result
        assert "\\zhabstract" in result
        assert "\\enabstract" in result
        assert "\\tableofcontents" in result
        assert "\\input{chapter/ch01}" in result
        assert "\\input{chapter/ch02}" in result
        assert "\\acknowledgement" in result
        assert "\\bibliography{ref}" in result
        assert "\\achievement" in result
        assert "\\begin{document}" in result
        assert "\\end{document}" in result

    def test_marxism_assembly(self, master_meta):
        result = assemble_main_tex(
            meta=master_meta,
            chapter_files=["chapter/ch01", "chapter/ch02", "chapter/ch03"],
            abstract_zh_body="摘要",
            abstract_zh_keywords="马克思",
            bib_mode="categorized",
        )
        # 马院: categorized bibliography with chapter heading
        assert "\\chapter*{参考文献}" in result
        assert "\\input{bibliography_categorized}" in result
        # Must NOT have standard bibliography
        assert "\\bibliography{ref}" not in result

    def test_negative_no_legacy_tokens(self, master_meta):
        """Codex Q2: 生成结果里不允许出现旧模板残留"""
        result = assemble_main_tex(
            meta=master_meta,
            chapter_files=["chapter/ch01"],
            bib_mode="standard",
        )
        for token in FORBIDDEN_LEGACY_TOKENS:
            assert token not in result, f"Legacy token found: {token}"

    def test_negative_no_legacy_marxism(self, master_meta):
        result = assemble_main_tex(
            meta=master_meta,
            chapter_files=["chapter/ch01"],
            bib_mode="categorized",
        )
        for token in FORBIDDEN_LEGACY_TOKENS:
            assert token not in result, f"Legacy token found: {token}"


# =============================================================================
# Phase 8: Metadata fallback (F2)
# =============================================================================

class TestMetadataFallback:
    def test_minimal_meta_does_not_crash(self, minimal_meta):
        """旧版提取器只产出 7 个字段，adapter 必须用 fallback 补齐"""
        result = assemble_main_tex(
            meta=minimal_meta,
            chapter_files=["chapter/ch01"],
            bib_mode="standard",
        )
        assert "\\documentclass" in result
        assert "\\uestccover" in result
        # Should use default degree_type = master
        assert "master" in result

    def test_load_metadata_fallbacks(self, tmp_path):
        """写一个 7 字段的 JSON，验证 load_metadata 返回完整 21 字段"""
        meta_file = tmp_path / "cover_metadata.json"
        meta_file.write_text(json.dumps({
            "major_cn": "测试专业",
            "school_cn": "测试学院",
            "title_cn": "测试标题",
            "major_en": "Test Major",
            "student_id": "123456",
            "school_en": "Test School",
            "title_en": "Test Title",
        }), encoding="utf-8")

        loaded = load_metadata(str(meta_file))
        assert loaded["advisor_unit"] == "电子科技大学"
        assert loaded["advisor_unit_addr"] == "成都"
        assert loaded["grant_unit"] == "电子科技大学"
        assert loaded["degree_type"] == "master"
        assert loaded["cls_num"] == ""
        assert loaded["udc"] == ""


# ============================================================
# Round 8 阶段 C — D24/D26/D27 升 shared 回归
# ============================================================

def test_d24_bibliography_uses_cite_map_order():
    """D24 shared: 传 cite_map → emit_bibliography_standard 按顺序逐条 \\nocite, 不用 \\nocite{*}."""
    from template_adapter import emit_bibliography_standard
    cm = {"1": "first_key", "2": "second_key", "3": "third_key"}
    out = emit_bibliography_standard("ref", cite_map=cm)
    assert "\\nocite{*}" not in out
    assert "\\nocite{first_key}" in out
    assert "\\nocite{second_key}" in out
    assert "\\nocite{third_key}" in out
    assert out.index("first_key") < out.index("second_key")


def test_d24_bibliography_fallback_no_cite_map():
    """没传 cite_map 时仍用 \\nocite{*} (兼容)."""
    from template_adapter import emit_bibliography_standard
    out = emit_bibliography_standard("ref")
    assert "\\nocite{*}" in out


def test_d24v2_nocite_in_prelude_skips_nocite():
    """D24 v2 (CASE-A): nocite_in_prelude=True 时, emit_bibliography_standard 仅返回
    \\bibliography{ref}, 跳过 \\nocite 块 (假定调用方已在 prelude emit)."""
    from template_adapter import emit_bibliography_standard
    cm = {"1": "k1", "2": "k2"}
    out = emit_bibliography_standard("ref", cite_map=cm, nocite_in_prelude=True)
    assert "\\bibliography{ref}" in out
    assert "\\nocite" not in out  # prelude 负责 emit


def test_d24v2_emit_nocite_prelude_keys_in_order():
    """D24 v2: emit_nocite_prelude 按 cite_map 1..N 顺序 emit \\nocite{key}."""
    from template_adapter import emit_nocite_prelude
    cm = {"1": "alpha_key", "2": "beta_key", "3": "gamma_key"}
    out = emit_nocite_prelude(cm)
    assert "\\nocite{alpha_key}" in out
    assert "\\nocite{beta_key}" in out
    assert "\\nocite{gamma_key}" in out
    assert out.index("alpha_key") < out.index("beta_key") < out.index("gamma_key")


def test_d24v2_emit_nocite_prelude_empty_for_no_cite_map():
    """D24 v2: 无 cite_map → emit_nocite_prelude 返回空串 (调用方决定 fallback)."""
    from template_adapter import emit_nocite_prelude
    assert emit_nocite_prelude(None) == ""
    assert emit_nocite_prelude({}) == ""


def test_d24v2_assemble_main_tex_nocite_before_chapters():
    """D24 v2 整合: assemble_main_tex 把 \\nocite 块放在 \\input{chapter/...} 之前."""
    from template_adapter import assemble_main_tex
    meta = {
        "title_cn": "T", "author_cn": "A", "student_id": "1",
        "major_cn": "M", "school_cn": "信息与通信工程学院",
        "advisor_name_cn": "D", "advisor_title_cn": "教授",
        "degree_type": "bachelor",
    }
    cm = {"1": "earlier_key", "2": "later_key"}
    result = assemble_main_tex(
        meta=meta,
        chapter_files=["chapter/ch01.tex"],
        bib_mode="standard",
        cite_map=cm,
    )
    nocite_pos = result.find("\\nocite{earlier_key}")
    chapter_pos = result.find("\\input{chapter/ch01")
    biblio_pos = result.find("\\bibliography{ref}")
    assert nocite_pos > 0, "nocite block 必须 emit"
    assert chapter_pos > 0, "chapter input 必须 emit"
    assert nocite_pos < chapter_pos, (
        f"\\nocite 必须在 \\input{{chapter}} 之前 (D24 v2 关键约束). "
        f"实际: nocite@{nocite_pos}  chapter@{chapter_pos}"
    )
    assert biblio_pos > chapter_pos, "\\bibliography 仍在文末"


def test_d26_tilde_escape_in_abstract():
    """D26 shared: 摘要中 ~ 转 \\textasciitilde{}, 渲染字面波浪号."""
    from template_adapter import emit_abstract_zh
    out = emit_abstract_zh("频段 0.005~1.0 GHz", "kw")
    assert "\\textasciitilde{}" in out
    body_part = out.split("\\zhkeywords")[0]
    assert "~" not in body_part.replace("\\textasciitilde{}", "")


def test_d27_cite_redirect_skipped_for_marxism():
    """D27: marxism profile (脚注引用) 不加 \\cite 重定向."""
    from template_adapter import assemble_main_tex
    marxism_meta = {
        "title_cn": "测试", "author_cn": "作者", "student_id": "1",
        "major_cn": "马克思主义", "school_cn": "马克思主义学院",
        "advisor_name_cn": "导师", "advisor_title_cn": "教授",
        "degree_type": "master",
    }
    result = assemble_main_tex(
        meta=marxism_meta,
        chapter_files=["chapter/ch01"],
        bib_mode="categorized",
    )
    assert "\\let\\origcite=\\cite" not in result
