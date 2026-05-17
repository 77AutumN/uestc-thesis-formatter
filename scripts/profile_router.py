#!/usr/bin/env python3
"""profile_router.py — Round 8 阶段 A, profile 决策推荐器.

输入: docx path (+ 可选用户指定 profile)
输出: (推荐 profile, 证据列表, confidence 0-1, 是否建议建 candidate)

设计原则 (见 docs/profile_policy.md):
  - 默认覆盖 4 个 profile: stem / uestc / uestc-bachelor / uestc-marxism
  - 不机械按学院名建 profile, 仅在引用体系/章节体系/CLS/编译链 4 类实质差异时才推 candidate
  - 用户指定 profile 优先, 但仍报告冲突证据

判定规则 (优先级递减):
  1. 封面含 "BACHELOR THESIS" 或 "学士学位论文" → uestc-bachelor (high confidence)
  2. 学院 = 马克思主义学院 → uestc-marxism (high)
  3. 封面含 "硕士/博士学位论文" + UESTC → uestc (high)
  4. 学院在 STEM 列表中 + 无 UESTC 模板信号 → stem (medium)
  5. 否则 → uestc (medium-low) + 建议看证据手动决定

Usage:
    python profile_router.py <docx_path> [--user-profile <name>] [--json]
    # exit 0 总是 (router 不阻断)
"""

from __future__ import annotations
import argparse
import json
import os
import re
import sys
import zipfile
from dataclasses import dataclass, field, asdict
from typing import List, Optional

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

try:
    from xml.etree import ElementTree as ET
except ImportError:
    ET = None  # type: ignore

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

KNOWN_PROFILES = {"stem", "uestc", "uestc-bachelor", "uestc-marxism"}

# UESTC 学院列表 (常见, 不全)
UESTC_STEM_COLLEGES = {
    "信息与通信工程学院", "电子科学与工程学院", "计算机科学与工程学院",
    "自动化工程学院", "光电科学与工程学院", "机械与电气工程学院",
    "材料与能源学院", "集成电路科学与工程学院", "示范性微电子学院",
    "航空航天学院", "资源与环境学院", "生命科学与技术学院",
    "数学科学学院", "物理学院",
}
UESTC_MARXISM_COLLEGE = "马克思主义学院"
UESTC_NON_STEM_COLLEGES = {
    "经济与管理学院", "公共管理学院", "外国语学院", "格拉斯哥学院",
    "医学院", "法学院",
}


@dataclass
class ProfileRecommendation:
    profile: str
    confidence: float
    evidence: List[str] = field(default_factory=list)
    suggest_candidate: bool = False
    candidate_reason: str = ""
    user_override: Optional[str] = None
    conflicts_with_user: bool = False


def _read_docx_paragraphs(docx_path: str) -> List[str]:
    """解压 docx, 返回所有段落文本 (空段去掉)"""
    if not os.path.isfile(docx_path):
        return []
    try:
        with zipfile.ZipFile(docx_path) as z:
            if "word/document.xml" not in z.namelist():
                return []
            with z.open("word/document.xml") as f:
                tree = ET.parse(f)
    except (zipfile.BadZipFile, ET.ParseError):
        return []
    out = []
    for p in tree.getroot().iter(W_NS + "p"):
        text = "".join((t.text or "") for t in p.iter(W_NS + "t"))
        if text.strip():
            out.append(text)
    return out


def _detect_cover_signals(paragraphs: List[str]) -> dict:
    """从前 30 段 (封面区) 抽信号."""
    head = "\n".join(paragraphs[:30])
    return {
        "has_bachelor_thesis_en": "BACHELOR THESIS" in head,
        "has_bachelor_thesis_zh": "学士学位论文" in head,
        "has_master_thesis_zh": "硕士学位论文" in head,
        "has_doctor_thesis_zh": "博士学位论文" in head,
        "has_uestc_zh": "电子科技大学" in head,
        "has_uestc_en": "University of Electronic Science and Technology" in head,
    }


def _detect_college(paragraphs: List[str]) -> Optional[str]:
    """扫前 50 段, 找学院名 (匹配已知列表)."""
    head_text = "\n".join(paragraphs[:50])
    if UESTC_MARXISM_COLLEGE in head_text:
        return UESTC_MARXISM_COLLEGE
    for college in list(UESTC_STEM_COLLEGES) + list(UESTC_NON_STEM_COLLEGES):
        if college in head_text:
            return college
    return None


def _detect_foreign_literature(paragraphs: List[str]) -> bool:
    """检测是否含外文资料章 (本科必含)."""
    full_text = "\n".join(paragraphs)
    return ("外文资料原文" in full_text or "外文资料译文" in full_text)


def route_profile(docx_path: str, user_profile: Optional[str] = None) -> ProfileRecommendation:
    """主决策函数."""
    paragraphs = _read_docx_paragraphs(docx_path)
    if not paragraphs:
        return ProfileRecommendation(
            profile=user_profile or "uestc",
            confidence=0.1,
            evidence=["docx 无法解析或为空"],
            suggest_candidate=False,
            user_override=user_profile,
        )

    signals = _detect_cover_signals(paragraphs)
    college = _detect_college(paragraphs)
    has_foreign = _detect_foreign_literature(paragraphs)

    evidence = []
    if signals["has_uestc_zh"] or signals["has_uestc_en"]:
        evidence.append("封面含 UESTC 校名")
    if college:
        evidence.append(f"识别学院: {college}")
    if has_foreign:
        evidence.append("含外文资料章 (本科必含)")

    # 决策树
    rec_profile = None
    confidence = 0.0
    suggest_candidate = False
    candidate_reason = ""

    # Rule 1: bachelor 信号最强
    if signals["has_bachelor_thesis_en"] or signals["has_bachelor_thesis_zh"]:
        rec_profile = "uestc-bachelor"
        confidence = 0.95
        evidence.append("封面含 'BACHELOR THESIS' / '学士学位论文'")

    # Rule 2: marxism
    elif college == UESTC_MARXISM_COLLEGE:
        rec_profile = "uestc-marxism"
        confidence = 0.95
        evidence.append("学院为马克思主义学院 → 脚注引用 + 分类参考文献")

    # Rule 3: master/doctor + UESTC
    elif (signals["has_master_thesis_zh"] or signals["has_doctor_thesis_zh"]) and \
         (signals["has_uestc_zh"] or signals["has_uestc_en"]):
        rec_profile = "uestc"
        confidence = 0.90
        evidence.append("封面含 '硕士/博士学位论文' + UESTC 校名")

    # Rule 4: STEM 学院 + 非 UESTC 模板 → stem
    elif college in UESTC_STEM_COLLEGES and not (signals["has_uestc_zh"] or signals["has_uestc_en"]):
        rec_profile = "stem"
        confidence = 0.70
        evidence.append("STEM 学院 + 无明确 UESTC 校名 → 通用 stem profile")

    # Rule 5: 非 STEM 学院 (经管/医学/外语等) — 暂归 uestc + 建议看 candidate
    elif college in UESTC_NON_STEM_COLLEGES:
        rec_profile = "uestc"
        confidence = 0.50
        suggest_candidate = True
        candidate_reason = (
            f"学院 {college} 不在已验证 4 profile 范围, 建议先用 uestc 跑一遍 "
            f"intake, 若发现实质差异 (引用体系/章节/CLS) 再考虑写 profile_candidate"
        )
        evidence.append(f"学院 {college} 未充分验证")

    # Fallback
    else:
        rec_profile = "uestc"
        confidence = 0.30
        evidence.append("无明确学位/学院信号, fallback uestc")

    # 用户 override 处理
    conflicts = False
    if user_profile:
        if user_profile not in KNOWN_PROFILES:
            evidence.append(f"⚠️ 用户指定 profile '{user_profile}' 不在已知列表 {KNOWN_PROFILES}")
            conflicts = True
        elif user_profile != rec_profile:
            evidence.append(
                f"⚠️ 用户指定 '{user_profile}' 与推荐 '{rec_profile}' 不一致 (尊重用户选择, 但请核对)"
            )
            conflicts = True

    return ProfileRecommendation(
        profile=user_profile if user_profile else rec_profile,
        confidence=confidence,
        evidence=evidence,
        suggest_candidate=suggest_candidate,
        candidate_reason=candidate_reason,
        user_override=user_profile,
        conflicts_with_user=conflicts,
    )


def format_report(rec: ProfileRecommendation, docx_path: str) -> str:
    out = []
    out.append("=" * 60)
    out.append(f"profile_router — Profile 决策推荐 (Round 8 / 5a 前置)")
    out.append(f"docx: {docx_path}")
    out.append("=" * 60)
    out.append(f"📋 推荐 Profile: {rec.profile}")
    out.append(f"📊 Confidence: {rec.confidence:.2f}")
    if rec.user_override:
        if rec.conflicts_with_user:
            out.append(f"⚠️  用户指定 override: {rec.user_override} (与推荐冲突, 用户选择优先)")
        else:
            out.append(f"✅ 用户指定 override: {rec.user_override} (与推荐一致)")
    out.append("")
    out.append("📝 证据:")
    for e in rec.evidence:
        out.append(f"  - {e}")
    if rec.suggest_candidate:
        out.append("")
        out.append("⚠️ 建议建立 profile_candidate:")
        out.append(f"   {rec.candidate_reason}")
        out.append("   流程: 见 docs/profile_policy.md §5")
    out.append("=" * 60)
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Profile 决策推荐器 (Round 8)")
    ap.add_argument("docx", help="输入 docx 路径")
    ap.add_argument("--user-profile", default=None, help="用户指定 profile (override 推荐)")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而非 markdown")
    args = ap.parse_args()

    rec = route_profile(args.docx, args.user_profile)

    if args.json:
        print(json.dumps(asdict(rec), ensure_ascii=False, indent=2))
    else:
        print(format_report(rec, args.docx))

    sys.exit(0)  # router 不阻断


if __name__ == "__main__":
    main()
