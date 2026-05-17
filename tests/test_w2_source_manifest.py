"""tests/test_w2_source_manifest.py — W2 source_manifest 端到端 fixture suite.

依赖 tests/fixtures/surgery_relabel_minimal.docx + textbox_caption_minimal.docx.
"""
from __future__ import annotations
import os
import sys

import pytest

THIS = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(THIS, "..", "scripts"))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import source_manifest as sm  # noqa: E402

FIXTURE_RELABEL = os.path.join(THIS, "fixtures", "surgery_relabel_minimal.docx")
FIXTURE_TEXTBOX = os.path.join(THIS, "fixtures", "textbox_caption_minimal.docx")


def _need(p):
    if not os.path.isfile(p):
        pytest.skip(f"fixture missing: {p}")


def test_probe_manifest_required_top_level():
    _need(FIXTURE_RELABEL)
    m = sm.build_probe_manifest(FIXTURE_RELABEL)
    required = {"schema_version", "manifest_id", "generated_at", "generator", "source",
                "completeness", "paragraphs", "headings", "lists", "figures", "textboxes",
                "references", "tables", "equations", "footnotes", "cover_metadata", "diagnostics"}
    assert required.issubset(m.keys())
    assert m["schema_version"] == sm.SCHEMA_VERSION
    assert m["generator"]["mode"] == "probe"


def test_probe_manifest_completeness_probe_mode():
    _need(FIXTURE_RELABEL)
    m = sm.build_probe_manifest(FIXTURE_RELABEL)
    completeness = set(m["completeness"])
    assert {"raw_docx", "relationships", "styles"}.issubset(completeness)
    assert "pandoc_ast" not in completeness
    assert "extractor_outputs" not in completeness


def test_probe_manifest_relabel_fixture_detects_custom_heading():
    """relabel fixture 必须识别 custom_style heading 并标 needs_surgery=True."""
    _need(FIXTURE_RELABEL)
    m = sm.build_probe_manifest(FIXTURE_RELABEL)
    custom_h = [h for h in m["headings"] if h["source"] == "custom_style"]
    assert len(custom_h) >= 2  # 至少 "第一章" + "第二章"
    assert all(h["needs_surgery"] for h in custom_h)
    assert all(h["suggested_operation"] == "relabel_pstyle" for h in custom_h)


def test_probe_manifest_textbox_fixture_collects_caption():
    _need(FIXTURE_TEXTBOX)
    m = sm.build_probe_manifest(FIXTURE_TEXTBOX)
    cap_textboxes = [t for t in m["textboxes"] if t["caption_like"]]
    assert len(cap_textboxes) >= 1
    assert any(t["label"] == "图1-1" for t in cap_textboxes)


def test_id_uniqueness():
    _need(FIXTURE_RELABEL)
    m = sm.build_probe_manifest(FIXTURE_RELABEL)
    for collection in ("paragraphs", "headings", "textboxes", "figures"):
        ids = [it["id"] for it in m.get(collection, [])]
        assert len(set(ids)) == len(ids), f"{collection} duplicate ids"


def test_validate_manifest_reports_no_errors_for_probe():
    _need(FIXTURE_RELABEL)
    m = sm.build_probe_manifest(FIXTURE_RELABEL)
    errors = sm.validate_manifest(m)
    assert errors == [], f"validation errors: {errors}"


def test_validate_manifest_detects_missing_top_level():
    _need(FIXTURE_RELABEL)
    m = sm.build_probe_manifest(FIXTURE_RELABEL)
    del m["headings"]
    errors = sm.validate_manifest(m)
    assert any("missing top-level" in e for e in errors)
