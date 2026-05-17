"""tests/test_defect_cards.py — Round 5b 卡片库 schema 一致性验证.

验证 reference/defects/D??.md 全部合规, build_defect_index.py 输出与卡片同步.
"""
import json
import os
import re
import subprocess
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.normpath(os.path.join(THIS, ".."))
SCRIPTS = os.path.join(SKILL_DIR, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

# repo root 解析: skill 可能跑在 .agent/skills/(单) 或 .agents/skills/(复) 副本
# 兜底用绝对硬编码 + env override
REPO_ROOT = os.environ.get("THESIS_REPO_ROOT", r"./
DEFECTS_DIR = os.path.join(REPO_ROOT, "reference", "defects")
if not os.path.isdir(DEFECTS_DIR):
    import pytest
    pytest.skip(f"defects dir not found at {DEFECTS_DIR}, set THESIS_REPO_ROOT env",
                allow_module_level=True)

import build_defect_index  # noqa: E402


def test_defects_dir_exists():
    assert os.path.isdir(DEFECTS_DIR), f"defects 目录不存在: {DEFECTS_DIR}"


def test_card_template_exists():
    assert os.path.isfile(os.path.join(DEFECTS_DIR, "CARD_TEMPLATE.md"))


def test_at_least_20_cards():
    cards = build_defect_index.load_cards(DEFECTS_DIR)
    # Round 5b baseline: D1-D21 = 21 张
    assert len(cards) >= 20, f"卡片数 {len(cards)} < 20 (Round 5b 基线)"


def test_all_cards_schema_valid():
    cards = build_defect_index.load_cards(DEFECTS_DIR)
    errors = build_defect_index.validate_cards(cards)
    assert not errors, "卡片 schema 错误:\n" + "\n".join(errors)


def test_no_duplicate_ids():
    cards = build_defect_index.load_cards(DEFECTS_DIR)
    ids = [c.get("id") for c in cards]
    assert len(ids) == len(set(ids)), f"重复 ID: {[i for i in ids if ids.count(i) > 1]}"


def test_id_format():
    cards = build_defect_index.load_cards(DEFECTS_DIR)
    for c in cards:
        cid = c.get("id", "")
        assert re.match(r"^D\d{2,3}$", cid), f"id={cid!r} 不符合 D## 格式 (file: {c.get('__file__')})"


def test_introduced_in_format():
    cards = build_defect_index.load_cards(DEFECTS_DIR)
    for c in cards:
        intro = c.get("introduced_in", "")
        assert re.match(r"^CASE-\d{3}$", intro), f"{c.get('__file__')}: introduced_in={intro!r} 不符合 CASE-### 格式"


def test_dashboard_can_be_built():
    cards = build_defect_index.load_cards(DEFECTS_DIR)
    dashboard = build_defect_index.build_dashboard(cards)
    assert dashboard["schema_version"] == 1
    assert dashboard["total_defects"] == len(cards)
    assert "by_defect" in dashboard
    assert "by_case" in dashboard
    assert "stats" in dashboard


def test_check_mode_runs_clean(tmp_path):
    """跑 build_defect_index.py --check, 退出码必须 0."""
    script = os.path.join(SCRIPTS, "build_defect_index.py")
    result = subprocess.run(
        [sys.executable, script, "--root", REPO_ROOT, "--check"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, f"check 失败:\nstdout={result.stdout}\nstderr={result.stderr}"
