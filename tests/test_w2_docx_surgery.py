"""tests/test_w2_docx_surgery.py — W2 docx_surgery plan/apply/verify suite.

依赖 fixtures: surgery_relabel_minimal.docx + surgery_inject_minimal.docx.
"""
from __future__ import annotations
import json
import os
import shutil
import sys
import tempfile

import pytest

THIS = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(THIS, "..", "scripts"))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import docx_surgery as ds  # noqa: E402

FIXTURE_RELABEL = os.path.join(THIS, "fixtures", "surgery_relabel_minimal.docx")
FIXTURE_INJECT = os.path.join(THIS, "fixtures", "surgery_inject_minimal.docx")


def _need(p):
    if not os.path.isfile(p):
        pytest.skip(f"fixture missing: {p}")


def test_plan_relabel_fixture_emits_relabel_op():
    """relabel fixture: plan 应 emit register_heading_style + relabel_pstyle 各 ≥1."""
    _need(FIXTURE_RELABEL)
    with tempfile.TemporaryDirectory() as td:
        docx = os.path.join(td, "case.docx")
        shutil.copy(FIXTURE_RELABEL, docx)
        plan_path = os.path.join(td, "plan.json")
        plan = ds.cmd_plan(docx, plan_path)
        types = {op["type"] for op in plan["operations"]}
        assert "relabel_pstyle" in types
        assert "register_heading_style" in types
        # relabel op 应包含 1-1级 → Heading 1
        relabel = next(op for op in plan["operations"] if op["type"] == "relabel_pstyle")
        assert relabel["enabled"]
        assert "1-1级" in relabel["params"]["style_map"]


def test_plan_inject_fixture_does_not_crash():
    """inject fixture: plan 不抛 (W2 inject detector 是 stub, 主体 W3 补)."""
    _need(FIXTURE_INJECT)
    with tempfile.TemporaryDirectory() as td:
        docx = os.path.join(td, "case.docx")
        shutil.copy(FIXTURE_INJECT, docx)
        plan_path = os.path.join(td, "plan.json")
        plan = ds.cmd_plan(docx, plan_path)
        # W2: inject_heading_before 任何 op 都应默认 enabled=false 等人工 review
        for op in plan["operations"]:
            if op["type"] == "inject_heading_before":
                assert not op["enabled"], f"inject op {op['id']} should default disabled"


def test_apply_relabel_fixture_visible_text_unchanged_and_heading_count():
    """apply relabel: visible text hash 不变 + heading_counts 按 expected_delta."""
    _need(FIXTURE_RELABEL)
    with tempfile.TemporaryDirectory() as td:
        docx = os.path.join(td, "case.docx")
        shutil.copy(FIXTURE_RELABEL, docx)
        pre_hash = ds._visible_text_hash(docx)
        plan_path = os.path.join(td, "plan.json")
        ds.cmd_plan(docx, plan_path)
        report = ds.cmd_apply(docx, plan_path, backup_tag="TEST", output_dir=td)
        assert report["status"] == "succeeded", report.get("error")
        post_hash = ds._visible_text_hash(docx)
        assert pre_hash == post_hash
        # 检查 heading_counts >= 期望
        relabel_report = next(r for r in report["operations"] if r["type"] == "relabel_pstyle")
        delta = relabel_report["actual_delta"]["heading_counts"]
        assert delta.get("Heading 1", 0) >= 2  # fixture 有 2 个 1-1级


def test_apply_failure_does_not_modify_source():
    """apply 失败时 source docx 不动 (mock op 抛异常)."""
    _need(FIXTURE_RELABEL)
    with tempfile.TemporaryDirectory() as td:
        docx = os.path.join(td, "case.docx")
        shutil.copy(FIXTURE_RELABEL, docx)
        original_sha = ds._sha256_file(docx)
        plan_path = os.path.join(td, "plan.json")
        ds.cmd_plan(docx, plan_path)

        # mock _apply_relabel_pstyle 抛
        original = ds._APPLIERS["relabel_pstyle"]
        ds._APPLIERS["relabel_pstyle"] = lambda tp, op: (_ for _ in ()).throw(RuntimeError("mock fail"))
        try:
            report = ds.cmd_apply(docx, plan_path, backup_tag="FAILTEST", output_dir=td)
        finally:
            ds._APPLIERS["relabel_pstyle"] = original
        assert report["status"] == "failed"
        # source 应不变
        post_sha = ds._sha256_file(docx)
        assert post_sha == original_sha
        # temp 应改名 FAILED
        assert "failed_temp_path" in report


def test_verify_relabel_passes():
    """完整 plan/apply/verify 闭环 → verify pass."""
    _need(FIXTURE_RELABEL)
    with tempfile.TemporaryDirectory() as td:
        docx = os.path.join(td, "case.docx")
        shutil.copy(FIXTURE_RELABEL, docx)
        plan_path = os.path.join(td, "plan.json")
        ds.cmd_plan(docx, plan_path)
        ds.cmd_apply(docx, plan_path, backup_tag="VERIFY", output_dir=td)
        verify_report = ds.cmd_verify(docx, plan_path, output_dir=td)
        assert verify_report["overall_passed"], json.dumps(verify_report, indent=2, ensure_ascii=False)


def test_apply_sha256_mismatch_raises():
    """apply 时 docx sha256 与 plan 不匹配 → raise."""
    _need(FIXTURE_RELABEL)
    with tempfile.TemporaryDirectory() as td:
        docx = os.path.join(td, "case.docx")
        shutil.copy(FIXTURE_RELABEL, docx)
        plan_path = os.path.join(td, "plan.json")
        ds.cmd_plan(docx, plan_path)
        # 改 plan 的 sha256
        with open(plan_path, encoding="utf-8") as f:
            plan = json.load(f)
        plan["source_docx_sha256"] = "deadbeef" * 8
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f)
        with pytest.raises(RuntimeError, match="sha256 mismatch"):
            ds.cmd_apply(docx, plan_path, backup_tag="SHA", output_dir=td)
