"""tests/test_risk_router.py — Round 7 阶段 D / 5a fixture suite.

验证 RULES 各 trigger detection + 集成 CASE-A docx (skip if not exist).
"""
import os
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(THIS, "..", "scripts"))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import preflight_risk_router as router  # noqa: E402


# ============================================================
# Mock DocxFacts (绕过真 docx 解压)
# ============================================================

class FakeFacts:
    """Mock DocxFacts, 直接给 string 字段."""
    def __init__(self, **kwargs):
        self.docx_path = "fake.docx"
        self.paragraphs = kwargs.get("paragraphs", [])
        self.abstract_zh = kwargs.get("abstract_zh", "")
        self.abstract_en = kwargs.get("abstract_en", "")
        self.references = kwargs.get("references", [])
        self.acknowledgement = kwargs.get("acknowledgement", "")
        self.media_count = kwargs.get("media_count", 0)
        self.textbox_caption_count = kwargs.get("textbox_caption_count", 0)


# ============================================================
# Rule unit tests
# ============================================================

def test_rule_d22_percent_in_abstract():
    f = FakeFacts(abstract_zh="实验范围在 0%~3% 区间")
    assert router._rule_d22(f) is not None
    f2 = FakeFacts(abstract_zh="无百分号文本")
    assert router._rule_d22(f2) is None


def test_rule_d23_proceedings_or_standard():
    f = FakeFacts(references=["Tummala R R. Title[C]. Conf, 2005, 3-7."])
    assert router._rule_d23(f) is not None
    f2 = FakeFacts(references=["Sun Y. Title[J]. Journal, 2020, 10(1): 1-5."])
    assert router._rule_d23(f2) is None  # only [J] no extra type


def test_rule_d24_always_triggers_with_refs():
    f = FakeFacts(references=["any ref"])
    assert router._rule_d24(f) is not None
    f2 = FakeFacts(references=[])
    assert router._rule_d24(f2) is None


def test_rule_d25_western_author():
    f = FakeFacts(references=["Tummala R R. Packaging[C]. Conf, 2005."])
    assert router._rule_d25(f) is not None
    f2 = FakeFacts(references=["全国玻璃委员会(SAC). 标准[S]. 北京, 2023."])
    assert router._rule_d25(f2) is None


def test_rule_d26_tilde_in_abstract():
    f = FakeFacts(abstract_zh="频率范围 0.005~1.0 GHz")
    assert router._rule_d26(f) is not None
    f2 = FakeFacts(abstract_zh="频率范围 0.005 to 1.0 GHz")
    assert router._rule_d26(f2) is None


def test_rule_d27_cite_in_paragraphs():
    f = FakeFacts(paragraphs=["本研究[1, 2]提出新方法。"])
    assert router._rule_d27(f) is not None


def test_rule_d28_always_triggers():
    """D28 是通用风险, 任何 case 都触发."""
    f = FakeFacts()
    assert router._rule_d28(f) is not None


def test_rule_d29_chemistry_in_refs():
    f = FakeFacts(references=["Test. Sb2O3 effect on glass[J]. J, 2020, 10(1): 1-5."])
    assert router._rule_d29(f) is not None
    f2 = FakeFacts(references=["Test. General methodology[J]. J, 2020, 10(1): 1-5."])
    assert router._rule_d29(f2) is None


def test_rule_d30_amp_in_refs():
    f = FakeFacts(references=["Kingery W D. Title[M]. NY: Wiley & Sons, 1976."])
    assert router._rule_d30(f) is not None
    f2 = FakeFacts(references=["Kingery W D. Title[M]. NY: Wiley, 1976."])
    assert router._rule_d30(f2) is None


def test_rule_d31_chinese_org_with_paren():
    f = FakeFacts(references=["全国玻璃仪器标准化技术委员会(SAC/TC 178). 标准[S]. 北京, 2023."])
    assert router._rule_d31(f) is not None
    f2 = FakeFacts(references=["梁天鹏. 论文[D]. 成都: 电子科技大学, 2021."])
    assert router._rule_d31(f2) is None


def test_rule_d39_textbox_caption():
    """D39 (CASE-A): textbox 装 caption 触发 input-side 预警"""
    f = FakeFacts(textbox_caption_count=13)
    assert router._rule_d39_textbox_caption(f) is not None
    f2 = FakeFacts(textbox_caption_count=0)
    assert router._rule_d39_textbox_caption(f2) is None


def test_rule_acknowledgement_placeholder():
    f = FakeFacts(acknowledgement="本论文是在我的导师XX老师指导下完成 ……")
    assert router._rule_acknowledgement_placeholder(f) is not None
    f2 = FakeFacts(acknowledgement="感谢导师陈教授悉心指导。")
    assert router._rule_acknowledgement_placeholder(f2) is None


def test_rule_keyword_count_exceed():
    f = FakeFacts(abstract_zh="正文\n关键词：a，b，c，d，e，f")
    assert router._rule_keyword_count_exceed(f) is not None
    f2 = FakeFacts(abstract_zh="正文\n关键词：a，b，c")
    assert router._rule_keyword_count_exceed(f2) is None


# ============================================================
# DocxFacts slicing (用 fake paragraphs)
# ============================================================

def test_docxfacts_norm_handles_full_width_space():
    """'摘  要' (中间全角/双空格) 应能识别为 '摘要'."""
    assert router.DocxFacts._norm("摘  要") == "摘要"
    assert router.DocxFacts._norm("摘　要") == "摘要"
    assert router.DocxFacts._norm("致 谢") == "致谢"


# ============================================================
# 集成: 跑 CASE-A 真 docx (skip if not exist)
# ============================================================

def test_integration_case012_full_router():
    """跑 CASE-A docx 应触发 ≥10 项 trigger."""
    repo = os.environ.get("THESIS_REPO_ROOT", "")
    docx = os.path.join(repo, "work", "新case.docx")
    if not os.path.isfile(docx):
        import pytest
        pytest.skip("CASE-A 新case.docx 不存在, 跳过集成测试")
    facts = router.DocxFacts(docx)
    assert facts.media_count == 18, f"docx 媒体应 18 张, 实际 {facts.media_count}"
    assert len(facts.references) >= 20, f"references 应 ≥20 条, 实际 {len(facts.references)}"
    assert "Ba" in facts.abstract_zh or "玻璃" in facts.abstract_zh
    hits = router.run_router(docx, dashboard={})
    # CASE-A 应触发: D22-D31 + acknowledgement + keyword 共 12 项
    assert len(hits) >= 10, f"应 ≥10 项触发, 实际 {len(hits)}: {[h['d_id'] for h in hits]}"
