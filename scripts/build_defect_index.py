#!/usr/bin/env python3
"""build_defect_index.py — 扫 reference/defects/D*.md 输出 INDEX.md + dashboard.json

Round 5b: 把 lessons_learned.md 散文升级为结构化卡片 + 自动产出索引.

输入:
  reference/defects/D??.md (一缺陷一文件, YAML frontmatter)

输出:
  reference/defects/INDEX.md       — 给人看, 一表索引 + 按 severity/applies_to_degree 筛
  reference/defects/dashboard.json — 给 AI 看, 机器可读, jq 友好

Usage:
  python build_defect_index.py [--root <repo_root>] [--check]
  --check 只校验不写文件 (CI/test 用)
"""

from __future__ import annotations
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

YAML_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def parse_frontmatter(text: str) -> dict | None:
    """简易 YAML frontmatter parser — 只支持 dump 我们卡片的键. 不引 PyYAML 依赖."""
    m = YAML_RE.match(text)
    if not m:
        return None
    body = m.group(1)
    out: dict = {}
    current_key: str | None = None
    block_buf: list[str] = []
    block_kind: str | None = None  # 'list' or 'pipe'

    def flush_block():
        nonlocal current_key, block_buf, block_kind
        if current_key and block_kind == "list":
            out[current_key] = [x.strip().strip(",") for x in block_buf if x.strip()]
        elif current_key and block_kind == "pipe":
            out[current_key] = "\n".join(block_buf).strip()
        block_buf = []
        block_kind = None
        current_key = None

    for raw in body.splitlines():
        if not raw.strip():
            continue
        if raw.startswith("  - "):
            if block_kind != "list":
                block_kind = "list"
            block_buf.append(raw[4:].strip())
            continue
        if block_kind == "pipe" and (raw.startswith("  ") or raw.startswith("\t")):
            block_buf.append(raw.lstrip())
            continue
        if ":" in raw and not raw.startswith(" "):
            flush_block()
            key, _, val = raw.partition(":")
            key = key.strip()
            val = val.strip()
            current_key = key
            if val == "|":
                block_kind = "pipe"
                continue
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                out[key] = [x.strip() for x in inner.split(",") if x.strip()] if inner else []
                current_key = None
                continue
            out[key] = val
            current_key = None
    flush_block()
    return out


def load_cards(defects_dir: str) -> list[dict]:
    cards = []
    for fname in sorted(os.listdir(defects_dir)):
        if not (fname.startswith("D") and fname.endswith(".md")):
            continue
        path = os.path.join(defects_dir, fname)
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        fm = parse_frontmatter(text)
        if fm is None:
            print(f"  ⚠️  {fname}: 无 YAML frontmatter, 跳过", file=sys.stderr)
            continue
        fm["__file__"] = fname
        cards.append(fm)
    return cards


def validate_cards(cards: list[dict]) -> list[str]:
    errors = []
    required = {"id", "title", "status", "severity", "applies_to_degree",
                "introduced_in", "cases", "fix_location"}
    valid_status = {"shared_code_fixed", "case_private", "pending", "wontfix"}
    valid_severity = {"P0", "P1", "P2"}
    seen_ids = set()
    for c in cards:
        for k in required:
            if k not in c:
                errors.append(f"{c.get('__file__','?')}: 缺字段 {k}")
        if c.get("status") not in valid_status:
            errors.append(f"{c.get('__file__','?')}: status={c.get('status')!r} 不合法")
        if c.get("severity") not in valid_severity:
            errors.append(f"{c.get('__file__','?')}: severity={c.get('severity')!r} 不合法")
        cid = c.get("id")
        if cid in seen_ids:
            errors.append(f"{c.get('__file__','?')}: id={cid} 重复")
        seen_ids.add(cid)
    return errors


def build_dashboard(cards: list[dict]) -> dict:
    """AI-first JSON dashboard — by-defect + by-case + 统计聚合."""
    by_defect = {}
    by_case = defaultdict(list)
    severity_count = Counter()
    status_count = Counter()
    degree_count = Counter()

    for c in cards:
        cid = c["id"]
        cases = c.get("cases", [])
        if isinstance(cases, str):
            cases = [cases]
        by_defect[cid] = {
            "id": cid,
            "title": c.get("title", ""),
            "status": c.get("status", ""),
            "severity": c.get("severity", ""),
            "applies_to_degree": c.get("applies_to_degree", []),
            "introduced_in": c.get("introduced_in", ""),
            "cases": cases,
            "frequency": len(cases),
            "fix_location": c.get("fix_location", ""),
            "test_coverage": c.get("test_coverage", "TODO"),
            "detect_signature": c.get("detect_signature", ""),
            "triggers": c.get("triggers", []),
            "related_defects": c.get("related_defects", []),
            "card_path": f"reference/defects/{c['__file__']}",
        }
        for case in cases:
            by_case[case].append(cid)
        severity_count[c.get("severity", "?")] += 1
        status_count[c.get("status", "?")] += 1
        for d in c.get("applies_to_degree", []):
            degree_count[d] += 1

    return {
        "schema_version": 1,
        "total_defects": len(cards),
        "by_defect": by_defect,
        "by_case": dict(by_case),
        "stats": {
            "severity": dict(severity_count),
            "status": dict(status_count),
            "applies_to_degree": dict(degree_count),
            "top_frequency": sorted(
                [(d["id"], d["frequency"]) for d in by_defect.values()],
                key=lambda x: -x[1],
            )[:10],
        },
    }


def build_index_md(cards: list[dict], dashboard: dict) -> str:
    lines = [
        "# 缺陷卡片索引 (D-card INDEX)",
        "",
        "> 自动生成 — 不要手动编辑. 改动来源: `reference/defects/D??.md`",
        "> 重新生成: `python scripts/build_defect_index.py`",
        "",
        f"**总数**: {dashboard['total_defects']} 张卡片. **AI 友好版**: `dashboard.json` (jq 检索).",
        "",
        "## 按命中频率排序 (Top 5 最常踩)",
        "",
        "| Rank | ID | 频率 | 标题 | 状态 | severity |",
        "|------|----|------|------|------|----------|",
    ]
    for rank, (cid, freq) in enumerate(dashboard["stats"]["top_frequency"][:5], 1):
        d = dashboard["by_defect"][cid]
        lines.append(f"| {rank} | [{cid}]({d['card_path'].replace('reference/defects/', '')}) | {freq} | {d['title'][:50]} | {d['status']} | {d['severity']} |")
    lines.append("")
    lines.append("## 全部缺陷 (按 ID)")
    lines.append("")
    lines.append("| ID | 标题 | severity | status | 学位 | cases | fix_location |")
    lines.append("|----|------|----------|--------|------|-------|--------------|")
    for cid in sorted(dashboard["by_defect"].keys()):
        d = dashboard["by_defect"][cid]
        degrees = ",".join(d.get("applies_to_degree", []))
        cases = ",".join(d.get("cases", []))
        loc = d.get("fix_location", "")[:50]
        lines.append(f"| [{cid}]({d['card_path'].replace('reference/defects/', '')}) | {d['title'][:40]} | {d['severity']} | {d['status']} | {degrees} | {cases} | {loc} |")
    lines.append("")
    lines.append("## 统计")
    lines.append("")
    lines.append(f"- **severity**: {dashboard['stats']['severity']}")
    lines.append(f"- **status**: {dashboard['stats']['status']}")
    lines.append(f"- **applies_to_degree**: {dashboard['stats']['applies_to_degree']}")
    lines.append("")
    lines.append("## 按 case 索引 (哪个 case 命中了哪些 D)")
    lines.append("")
    for case, ds in sorted(dashboard["by_case"].items()):
        lines.append(f"- **{case}**: {', '.join(sorted(ds))}")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".."), help="repo root (default: 自动定位)")
    ap.add_argument("--check", action="store_true", help="只校验不写文件")
    args = ap.parse_args()

    # 自动定位 reference/defects/ — 跑在 .agents/skills/thesis-formatter/scripts/ 时,
    # repo root 是 ./ (4 层 up: scripts → thesis-formatter → skills → .agents → root)
    root = os.path.abspath(args.root)
    defects_dir = os.path.join(root, "reference", "defects")
    if not os.path.isdir(defects_dir):
        # fallback: 搜索 reference/defects 在 cwd 上下 2 层
        cwd = os.getcwd()
        for cand in [cwd, os.path.dirname(cwd), os.path.dirname(os.path.dirname(cwd))]:
            test = os.path.join(cand, "reference", "defects")
            if os.path.isdir(test):
                defects_dir = test
                root = cand
                break
        else:
            print(f"❌ 找不到 reference/defects/ (--root={root})", file=sys.stderr)
            sys.exit(1)

    cards = load_cards(defects_dir)
    print(f"  📚 加载 {len(cards)} 张卡片 from {defects_dir}")

    errors = validate_cards(cards)
    if errors:
        print("  ❌ Schema 校验失败:")
        for e in errors:
            print(f"    - {e}")
        if args.check:
            sys.exit(1)
    else:
        print("  ✅ 全部卡片 schema 合规")

    if args.check:
        sys.exit(0 if not errors else 1)

    dashboard = build_dashboard(cards)
    json_path = os.path.join(defects_dir, "dashboard.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=2, sort_keys=False)
    print(f"  ✅ {json_path}")

    index_md = build_index_md(cards, dashboard)
    index_path = os.path.join(defects_dir, "INDEX.md")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_md)
    print(f"  ✅ {index_path}")

    print(f"\n  Top 5 最常踩: {dashboard['stats']['top_frequency'][:5]}")


if __name__ == "__main__":
    main()
