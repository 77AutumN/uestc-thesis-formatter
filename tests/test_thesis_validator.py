#!/usr/bin/env python3
"""
test_thesis_validator.py — thesis_validator.py 的单元测试

覆盖范围:
  - Gate 2: CLS 正则提取 (setlength / captionsetup)
  - Gate 1: 结构校验 (outline / meta)
  - 配置加载 (thesis_acceptance.json)
"""

import json
import os
import sys
import tempfile

import pytest

# Add scripts/ to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from thesis_validator import (
    Severity,
    extract_setlength,
    extract_captionsetup,
    validate_cls,
    validate_structure,
    load_acceptance,
)


# ============================================================
# Fixtures
# ============================================================

SAMPLE_CLS_CONTENT = r"""
\setlength{\heavyrulewidth}{1.5pt}
\setlength{\lightrulewidth}{0.75pt}
\setlength{\cmidrulewidth}{0.5pt}

\captionsetup[figure]{aboveskip=6pt, belowskip=12pt}
\captionsetup[table]{aboveskip=12pt, belowskip=6pt}

\setlength{\abovedisplayskip}{6pt}
\setlength{\belowdisplayskip}{6pt}
\setlength{\abovedisplayshortskip}{6pt}
\setlength{\belowdisplayshortskip}{6pt}
"""

SAMPLE_CLS_WRONG = r"""
\setlength{\heavyrulewidth}{1.0pt}
\setlength{\lightrulewidth}{0.5pt}
\captionsetup[figure]{aboveskip=12pt, belowskip=6pt}
"""

SAMPLE_ACCEPTANCE = {
    "version": "2026.1",
    "cls_values": {
        "heavyrulewidth": {"expected": "1.5pt", "tolerance": 0},
        "lightrulewidth": {"expected": "0.75pt", "tolerance": 0},
        "cmidrulewidth": {"expected": "0.5pt", "tolerance": 0},
        "abovedisplayskip": {"expected": "6pt", "tolerance": 0},
        "belowdisplayskip": {"expected": "6pt", "tolerance": 0},
        "abovedisplayshortskip": {"expected": "6pt", "tolerance": 0},
        "belowdisplayshortskip": {"expected": "6pt", "tolerance": 0},
        "figure_aboveskip": {"expected": "6pt", "tolerance": 0},
        "figure_belowskip": {"expected": "12pt", "tolerance": 0},
        "table_aboveskip": {"expected": "12pt", "tolerance": 0},
        "table_belowskip": {"expected": "6pt", "tolerance": 0},
    },
    "structure": {
        "abstract_max_words_master": 800,
        "abstract_max_words_doctor": 1500,
        "keywords_count_min": 3,
        "keywords_count_max": 5,
        "title_max_chars": 25,
        "max_heading_levels": 4,
    },
}


@pytest.fixture
def acceptance():
    return SAMPLE_ACCEPTANCE


@pytest.fixture
def cls_file_ok(tmp_path):
    cls_path = tmp_path / "thesis-uestc.cls"
    cls_path.write_text(SAMPLE_CLS_CONTENT, encoding='utf-8')
    return str(cls_path)


@pytest.fixture
def cls_file_wrong(tmp_path):
    cls_path = tmp_path / "thesis-uestc-wrong.cls"
    cls_path.write_text(SAMPLE_CLS_WRONG, encoding='utf-8')
    return str(cls_path)


@pytest.fixture
def acceptance_json_file(tmp_path):
    path = tmp_path / "thesis_acceptance.json"
    path.write_text(json.dumps(SAMPLE_ACCEPTANCE), encoding='utf-8')
    return str(path)


# ============================================================
# Test: CLS Regex Extraction
# ============================================================

class TestExtractSetlength:
    def test_extract_heavyrulewidth(self):
        assert extract_setlength(SAMPLE_CLS_CONTENT, "heavyrulewidth") == "1.5pt"

    def test_extract_lightrulewidth(self):
        assert extract_setlength(SAMPLE_CLS_CONTENT, "lightrulewidth") == "0.75pt"

    def test_extract_nonexistent(self):
        assert extract_setlength(SAMPLE_CLS_CONTENT, "nonexistent") is None

    def test_extract_displayskip(self):
        assert extract_setlength(SAMPLE_CLS_CONTENT, "abovedisplayskip") == "6pt"
        assert extract_setlength(SAMPLE_CLS_CONTENT, "belowdisplayskip") == "6pt"


class TestExtractCaptionsetup:
    def test_extract_figure_aboveskip(self):
        assert extract_captionsetup(SAMPLE_CLS_CONTENT, "figure", "aboveskip") == "6pt"

    def test_extract_figure_belowskip(self):
        assert extract_captionsetup(SAMPLE_CLS_CONTENT, "figure", "belowskip") == "12pt"

    def test_extract_table_aboveskip(self):
        assert extract_captionsetup(SAMPLE_CLS_CONTENT, "table", "aboveskip") == "12pt"

    def test_extract_table_belowskip(self):
        assert extract_captionsetup(SAMPLE_CLS_CONTENT, "table", "belowskip") == "6pt"

    def test_extract_nonexistent_type(self):
        assert extract_captionsetup(SAMPLE_CLS_CONTENT, "listing", "aboveskip") is None


# ============================================================
# Test: Gate 2 — CLS Compliance
# ============================================================

class TestValidateCls:
    def test_all_pass(self, cls_file_ok, acceptance):
        report = validate_cls(cls_file_ok, acceptance)
        assert report.ok is True
        assert report.failed == 0
        assert report.passed == 11  # All 11 values checked

    def test_wrong_values(self, cls_file_wrong, acceptance):
        report = validate_cls(cls_file_wrong, acceptance)
        assert report.ok is False
        # heavyrulewidth: 1.0pt != 1.5pt → FAIL
        # lightrulewidth: 0.5pt != 0.75pt → FAIL
        # figure_aboveskip: 12pt != 6pt → FAIL
        assert report.failed >= 3

    def test_missing_cls(self, acceptance):
        report = validate_cls("/nonexistent/file.cls", acceptance)
        assert report.ok is False
        assert report.failed == 1

    def test_cls_report_contains_all_vars(self, cls_file_ok, acceptance):
        report = validate_cls(cls_file_ok, acceptance)
        check_names = [c.name for c in report.checks]
        assert "heavyrulewidth" in check_names
        assert "figure_belowskip" in check_names
        assert "table_aboveskip" in check_names


# ============================================================
# Test: Gate 1 — Structure Validation
# ============================================================

class TestValidateStructure:
    def test_good_meta(self, tmp_path, acceptance):
        meta = {
            "abstract_word_count": 650,
            "keywords_zh": ["关键词1", "关键词2", "关键词3", "关键词4"],
            "title_zh": "基于深度学习的图像分割研究",
            "citation_markers_in_body": 42,
        }
        meta_path = tmp_path / "thesis_meta.json"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')

        report = validate_structure(str(meta_path), None, acceptance)
        assert report.ok is True

    def test_abstract_too_long(self, tmp_path, acceptance):
        meta = {
            "abstract_word_count": 900,
            "keywords_zh": ["a", "b", "c"],
            "title_zh": "短标题",
            "citation_markers_in_body": 10,
        }
        meta_path = tmp_path / "thesis_meta.json"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')

        report = validate_structure(str(meta_path), None, acceptance, degree="master")
        # 900 > 800 → WARN
        abstract_check = [c for c in report.checks if "Abstract" in c.name]
        assert len(abstract_check) == 1
        assert abstract_check[0].severity == Severity.WARN

    def test_no_citation_markers(self, tmp_path, acceptance):
        meta = {
            "abstract_word_count": 500,
            "keywords_zh": ["a", "b", "c"],
            "title_zh": "短标题",
            "citation_markers_in_body": 0,
        }
        meta_path = tmp_path / "thesis_meta.json"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')

        report = validate_structure(str(meta_path), None, acceptance)
        cite_check = [c for c in report.checks if "Citation" in c.name]
        assert len(cite_check) == 1
        assert cite_check[0].severity == Severity.WARN

    def test_outline_with_chapters(self, tmp_path, acceptance):
        outline = [
            {"title": "第一章 绪论"},
            {"title": "第二章 相关工作"},
            {"title": "第三章 方法"},
            {"title": "第四章 实验"},
            {"title": "第五章 总结"},
        ]
        outline_path = tmp_path / "outline.json"
        outline_path.write_text(json.dumps(outline, ensure_ascii=False), encoding='utf-8')

        report = validate_structure(None, str(outline_path), acceptance)
        ch_check = [c for c in report.checks if "Chapter" in c.name]
        assert len(ch_check) == 1
        assert ch_check[0].severity == Severity.PASS

    def test_missing_meta(self, acceptance):
        report = validate_structure("/nonexistent.json", None, acceptance)
        assert report.warned >= 1


# ============================================================
# Test: Config Loading
# ============================================================

class TestLoadAcceptance:
    def test_load_valid(self, acceptance_json_file):
        config = load_acceptance(acceptance_json_file)
        assert config["version"] == "2026.1"
        assert "cls_values" in config
        assert "heavyrulewidth" in config["cls_values"]

    def test_load_missing(self):
        config = load_acceptance("/nonexistent/config.json")
        assert config == {}
