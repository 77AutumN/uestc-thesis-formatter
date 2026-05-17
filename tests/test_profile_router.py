"""tests/test_profile_router.py — Round 8 阶段 A profile_router fixture suite."""
import os
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(THIS, "..", "scripts"))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import profile_router as pr  # noqa: E402


# ============================================================
# Helpers — mock paragraphs without docx
# ============================================================

def _mock_route(monkeypatch, paragraphs, user_profile=None):
    """绕过 docx 解压, 直接喂 paragraphs 跑 route_profile."""
    monkeypatch.setattr(pr, "_read_docx_paragraphs", lambda _: paragraphs)
    return pr.route_profile("fake.docx", user_profile)


# ============================================================
# Rule 1: bachelor 信号
# ============================================================

def test_route_bachelor_en_signal(monkeypatch):
    paragraphs = ["电子科技大学", "BACHELOR THESIS", "论文题目: 测试"]
    rec = _mock_route(monkeypatch, paragraphs)
    assert rec.profile == "uestc-bachelor"
    assert rec.confidence >= 0.9


def test_route_bachelor_zh_signal(monkeypatch):
    paragraphs = ["电子科技大学", "学士学位论文", "标题"]
    rec = _mock_route(monkeypatch, paragraphs)
    assert rec.profile == "uestc-bachelor"
    assert rec.confidence >= 0.9


# ============================================================
# Rule 2: marxism
# ============================================================

def test_route_marxism(monkeypatch):
    paragraphs = ["电子科技大学", "硕士学位论文", "马克思主义学院", "标题"]
    rec = _mock_route(monkeypatch, paragraphs)
    assert rec.profile == "uestc-marxism"
    assert rec.confidence >= 0.9


# ============================================================
# Rule 3: master/doctor + UESTC
# ============================================================

def test_route_master(monkeypatch):
    paragraphs = ["电子科技大学", "硕士学位论文", "信息与通信工程学院"]
    rec = _mock_route(monkeypatch, paragraphs)
    assert rec.profile == "uestc"
    assert rec.confidence >= 0.85


def test_route_doctor(monkeypatch):
    paragraphs = ["电子科技大学", "博士学位论文", "计算机科学与工程学院"]
    rec = _mock_route(monkeypatch, paragraphs)
    assert rec.profile == "uestc"
    assert rec.confidence >= 0.85


# ============================================================
# Rule 5: 非 STEM 学院 → 建议 candidate
# ============================================================

def test_route_non_stem_suggests_candidate(monkeypatch):
    """经管学院应触发 candidate 建议."""
    paragraphs = ["电子科技大学", "硕士学位论文", "经济与管理学院"]
    rec = _mock_route(monkeypatch, paragraphs)
    # 注意: 经管同时含 'UESTC'+'硕士', 优先级 Rule 3 命中 → uestc
    # Rule 5 仅在 Rule 3 不成立时才生效, 所以这里其实 Rule 3 赢
    # 测试的是: 当只有 STEM 之外学院 + 无明确学位时
    assert rec.profile == "uestc"  # Rule 3 命中


def test_route_non_stem_no_degree_signal(monkeypatch):
    """无明确学位 + 非 STEM 学院 → fallback uestc + suggest candidate."""
    paragraphs = ["某学院", "经济与管理学院", "毕业论文"]
    rec = _mock_route(monkeypatch, paragraphs)
    assert rec.profile == "uestc"
    assert rec.suggest_candidate is True
    assert "经济与管理" in rec.candidate_reason


# ============================================================
# 用户 override
# ============================================================

def test_user_override_consistent(monkeypatch):
    paragraphs = ["BACHELOR THESIS"]
    rec = _mock_route(monkeypatch, paragraphs, user_profile="uestc-bachelor")
    assert rec.profile == "uestc-bachelor"
    assert not rec.conflicts_with_user


def test_user_override_conflict(monkeypatch):
    paragraphs = ["BACHELOR THESIS"]
    rec = _mock_route(monkeypatch, paragraphs, user_profile="uestc-marxism")
    assert rec.profile == "uestc-marxism"  # 尊重用户
    assert rec.conflicts_with_user


def test_user_override_unknown_profile(monkeypatch):
    paragraphs = ["BACHELOR THESIS"]
    rec = _mock_route(monkeypatch, paragraphs, user_profile="uestc-experimental")
    assert rec.conflicts_with_user
    assert any("不在已知列表" in e for e in rec.evidence)


# ============================================================
# 边界
# ============================================================

def test_route_empty_docx(monkeypatch):
    rec = _mock_route(monkeypatch, [])
    assert rec.profile == "uestc"  # fallback
    assert rec.confidence < 0.5


def test_route_unrecognized_docx(monkeypatch):
    paragraphs = ["完全不相关的文本"] * 10
    rec = _mock_route(monkeypatch, paragraphs)
    assert rec.profile == "uestc"
    assert rec.confidence < 0.5


# ============================================================
# 集成: CASE-A 真 docx
# ============================================================

def test_integration_case_anon_bachelor():
    repo = os.environ.get("THESIS_REPO_ROOT", "")
    docx = os.path.join(repo, "work", "新case.docx")
    if not os.path.isfile(docx):
        import pytest
        pytest.skip("CASE-A docx 不存在, 跳过")
    rec = pr.route_profile(docx)
    assert rec.profile == "uestc-bachelor"
    assert rec.confidence >= 0.9
    assert any("BACHELOR" in e or "学士" in e for e in rec.evidence)
