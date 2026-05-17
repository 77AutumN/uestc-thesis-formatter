#!/usr/bin/env python3
"""generate_intake_report.py — Round 8 阶段 B, 整合 intake 报告.

整合 3 个独立 input-side 模块输出, 生成单一 markdown:
  1. profile_router (Round 8-A): 推荐 profile + 证据 + confidence
  2. preflight_check (already): 9 项 docx 输入检查
  3. preflight_risk_router (Round 7-D): D 缺陷风险预警

输出: <output_dir>/intake_report.md

Usage:
    python generate_intake_report.py <docx> --output <intake_report.md> [--profile uestc-bachelor]
    # exit 0 总是 (intake 不阻断, 仅信息)
"""

from __future__ import annotations
import argparse
import os
import sys
from typing import Dict, List

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

import profile_router
import preflight_check
import preflight_risk_router
import route_advisor


def _section_basic(docx_path: str) -> List[str]:
    out = ["## 1. 基本信息", ""]
    if os.path.isfile(docx_path):
        size_kb = os.path.getsize(docx_path) / 1024
        out.append(f"- **docx 路径**: `{docx_path}`")
        out.append(f"- **文件大小**: {size_kb:.1f} KB")
    else:
        out.append(f"- ❌ docx 不存在: {docx_path}")
    out.append("")
    return out


def _section_profile(rec) -> List[str]:
    out = ["## 2. Profile 决策推荐", ""]
    out.append(f"- **推荐 Profile**: `{rec.profile}`")
    out.append(f"- **Confidence**: {rec.confidence:.2f}")
    if rec.user_override:
        if rec.conflicts_with_user:
            out.append(f"- ⚠️  **用户 override**: `{rec.user_override}` (与推荐冲突, 用户优先)")
        else:
            out.append(f"- ✅ **用户 override**: `{rec.user_override}` (一致)")
    out.append("")
    out.append("**证据**:")
    for e in rec.evidence:
        out.append(f"  - {e}")
    if rec.suggest_candidate:
        out.append("")
        out.append(f"⚠️  **建议建立 profile_candidate**: {rec.candidate_reason}")
    out.append("")
    return out


def _section_preflight(report) -> List[str]:
    out = ["## 3. Preflight 检查 (输入 docx 9 项)", ""]
    out.append(f"- 通过: {report.passed} / 失败: {report.failed} / 警告: {report.warnings}")
    if report.ok:
        out.append("- ✅ 全部通过")
    else:
        out.append("- ❌ 有失败项 — 流水线 Step 0 会阻断")
    out.append("")
    out.append("**详细**:")
    for chk in report.checks:
        icon = "✅" if chk["status"] == "PASS" else ("⚠️" if chk["status"] == "WARN" else "❌")
        detail = f" — {chk['detail']}" if chk["detail"] else ""
        out.append(f"  - {icon} {chk['name']}{detail}")
    out.append("")
    return out


def _section_risk_router(hits) -> List[str]:
    out = ["## 4. Risk Router 风险预警 (D 缺陷触发)", ""]
    if not hits:
        out.append("- ✅ 未检测到任何已知风险触发条件")
        out.append("")
        return out

    out.append(f"- 共扫到 **{len(hits)}** 项触发条件")
    out.append("")
    by_status: Dict[str, list] = {}
    for h in hits:
        by_status.setdefault(h["status"], []).append(h)

    icon_map = {
        "shared_code_fixed": "✅",
        "case_private":      "⚠️",
        "pending":           "❌",
        "client_fix":        "📝",
        "wontfix":           "ℹ️",
    }
    label_map = {
        "shared_code_fixed": "已修 (产物不受影响)",
        "case_private":      "candidate (需 case-private 干预)",
        "pending":           "未修 (需立即手动干预)",
        "client_fix":        "客户原稿瑕疵 (告知客户)",
        "wontfix":           "wontfix (设计选择)",
    }
    for status in ["pending", "client_fix", "case_private", "shared_code_fixed", "wontfix"]:
        items = by_status.get(status, [])
        if not items:
            continue
        out.append(f"### {icon_map.get(status, '•')} {label_map.get(status, status)} ({len(items)} 项)")
        out.append("")
        for h in items:
            out.append(f"- **[{h['d_id']}]** {h['title']}")
            out.append(f"  - 触发: {h['evidence']}")
            if h.get("fix_location"):
                out.append(f"  - 修法: `{h['fix_location']}`")
            if h.get("card_path"):
                out.append(f"  - 卡片: `{h['card_path']}`")
        out.append("")
    return out


def _section_client_issues(hits) -> List[str]:
    """从 risk-router hits 中提 client_fix 类, 转客户反馈清单."""
    client_hits = [h for h in hits if h["status"] == "client_fix"]
    out = ["## 5. 客户原稿瑕疵清单 (转述客户)", ""]
    if not client_hits:
        out.append("✅ 客户原稿无已知瑕疵")
        out.append("")
        return out
    for h in client_hits:
        out.append(f"- **{h['title']}**: {h['evidence']}")
    out.append("")
    return out


def _section_recommendation(rec, preflight_report, hits) -> List[str]:
    out = ["## 6. 建议路径 (Claude/用户决策点)", ""]
    pending = [h for h in hits if h["status"] in ("pending", "case_private")]
    if not preflight_report.ok:
        out.append(f"❌ **Preflight 失败 {preflight_report.failed} 项** — Step 0 会阻断, 修 input docx 或调 profile 再重跑")
    elif pending:
        out.append(f"⚠️  **{len(pending)} 项需要 case-private 干预**:")
        for h in pending:
            out.append(f"   - {h['d_id']}: {h['title']}")
        out.append("   → 走流水线时关注产物 audit, 或参考 candidate 卡片预先 case-private 修")
    else:
        out.append("✅ **input 侧无阻断风险**, 可直接走流水线 `run_v2.py --profile " + rec.profile + "`")
    out.append("")
    out.append("**双层保险衔接**:")
    out.append("- input 侧: 本 intake 报告 + Step -1 risk-router (Round 7-D)")
    out.append("- output 侧: Step 6c product_audit Check 1-15 (Round 7-C + W4 + W5 Wave 2)")
    out.append("")
    return out


def _section_route_advisor(advisor_result: dict) -> List[str]:
    """Section 7 (W5 Wave 2 Item 3): docx_direct vs latex_v2 route hint."""
    out = ["## 7. 交付路线推荐 (W5 Wave 2)", ""]
    route = advisor_result["recommended_route"]
    rationale = advisor_result["rationale"]
    emoji = "📦" if route == "docx_direct" else "🛠️"
    out.append(f"- **推荐路线**: `{route}` {emoji}")
    out.append(f"- **理由**: {rationale}")
    out.append(f"- **交付模式**: `{advisor_result['deliverable_mode']}` (脚本只推荐, 不自动切换)")
    out.append("")
    out.append("**4 条件检查** (`reference/defects/proposed/CANDIDATE_docx_direct_route_roi_2026-05-08.md`):")
    cond_titles = [
        "header/footer (STYLEREF / PAGE field)",
        "built-in Heading 1/2/3 样式",
        "客户原稿无破损",
        "仅交付 docx (用户决定)",
    ]
    keys = [
        "condition_1_header_footer",
        "condition_2_builtin_headings",
        "condition_3_no_corruption",
        "condition_4_docx_only_delivery",
    ]
    for i, (title, key) in enumerate(zip(cond_titles, keys), start=1):
        c = advisor_result[key]
        mark = "✅" if c["met"] else "❌"
        out.append(f"  {mark} Condition {i}: {title}")
        for ev in c["evidence"]:
            out.append(f"      - {ev}")
    out.append("")
    return out


def generate(docx_path: str, output_path: str, user_profile: str = None, deliverable: str = "unknown") -> str:
    """生成 intake_report.md 内容并写入文件. 返回 markdown 字符串."""
    rec = profile_router.route_profile(docx_path, user_profile)
    pre_report = preflight_check.run_preflight(docx_path, rec.profile)
    # risk router (复用 5b dashboard)
    dashboard_path = ""
    cur = os.path.abspath(docx_path)
    for _ in range(5):
        cur = os.path.dirname(cur)
        cand = os.path.join(cur, "reference", "defects", "dashboard.json")
        if os.path.isfile(cand):
            dashboard_path = cand
            break
    dashboard = preflight_risk_router.load_dashboard(dashboard_path) if dashboard_path else {}
    hits = preflight_risk_router.run_router(docx_path, dashboard)
    advisor_result = route_advisor.detect_route_eligibility(docx_path, deliverable_mode=deliverable)

    lines = [f"# Intake Report — {os.path.basename(docx_path)}", ""]
    lines.extend(_section_basic(docx_path))
    lines.extend(_section_profile(rec))
    lines.extend(_section_preflight(pre_report))
    lines.extend(_section_risk_router(hits))
    lines.extend(_section_client_issues(hits))
    lines.extend(_section_recommendation(rec, pre_report, hits))
    lines.extend(_section_route_advisor(advisor_result))

    md = "\n".join(lines)
    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(md)
    return md


def main():
    ap = argparse.ArgumentParser(description="Intake report 生成器 (Round 8-B)")
    ap.add_argument("docx", help="输入 docx 路径")
    ap.add_argument("--output", required=True, help="输出 markdown 路径")
    ap.add_argument("--profile", default=None, help="用户指定 profile (override 推荐)")
    ap.add_argument(
        "--deliverable",
        default="unknown",
        choices=["docx_only", "pdf_required", "unknown"],
        help="客户交付格式 (W5 Wave 2: docx_direct vs latex_v2 路线推荐输入)",
    )
    args = ap.parse_args()

    md = generate(args.docx, args.output, args.profile, args.deliverable)
    print(f"✅ Intake report 已写入: {args.output}")
    print(f"   总行数: {len(md.splitlines())}")
    sys.exit(0)


if __name__ == "__main__":
    main()
