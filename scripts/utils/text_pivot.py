"""text_pivot.py — placeholder pivot replace 算法 (Round 9 W2).

为 .tex / 任意文本流的 cascade-safe 替换. CASE-A round2 表 4 编号
4-2..4-8 → 4-1..4-7 第一版用倒序 sub 致 cascade overwrite (4-3→4-2 后,
4-2→4-1 又把刚改的吞掉). placeholder pivot 两阶段:
  - 阶段 A: 全部 source -> placeholder (token_prefix + key)
  - 阶段 B: placeholder -> target

不属于 docx_surgery (那是 OOXML 级 B 类结构修复). 这里是 .tex 字符串工具.
"""
from __future__ import annotations
import re
from typing import Dict, Tuple


def pivot_replace(text: str, mapping: Dict[str, str],
                  token_prefix: str = "__PIVOT__") -> Tuple[str, Dict]:
    """Cascade-safe 替换. 返回 (new_text, report).

    mapping: {source_pattern: target_string}. source_pattern 当 literal.
    若需 regex 用 re.escape() 后传入.

    report 字段:
      - phase_a_subs: int — 阶段 A 替换数
      - phase_b_subs: int — 阶段 B 替换数
      - unreplaced_keys: list — mapping key 但 phase_a 没命中 (source 文本不含)
      - collisions: list — placeholder 跟 mapping value 冲突 (target 含 placeholder, 极罕见)
    """
    report: Dict = {
        "phase_a_subs": 0,
        "phase_b_subs": 0,
        "unreplaced_keys": [],
        "collisions": [],
    }
    if not mapping:
        return text, report

    # 检测 collision: target 不能含 placeholder
    for k, v in mapping.items():
        if token_prefix in v:
            report["collisions"].append(f"target {v!r} contains placeholder")
    if report["collisions"]:
        return text, report

    # 阶段 A: 所有 source key → placeholder
    new_text = text
    keys_sorted = sorted(mapping.keys(), key=len, reverse=True)
    for k in keys_sorted:
        placeholder = f"{token_prefix}{k}{token_prefix}"
        before = new_text
        new_text = new_text.replace(k, placeholder)
        cnt = (len(before) - len(new_text) + len(placeholder) * 0) // 1  # placeholder count
        # 直接用差长度算不准, 用 count
        cnt = before.count(k)
        report["phase_a_subs"] += cnt
        if cnt == 0:
            report["unreplaced_keys"].append(k)

    # 阶段 B: placeholder → target
    for k in keys_sorted:
        placeholder = f"{token_prefix}{k}{token_prefix}"
        cnt = new_text.count(placeholder)
        new_text = new_text.replace(placeholder, mapping[k])
        report["phase_b_subs"] += cnt

    return new_text, report


# ============================================================
# CLI (可选)
# ============================================================

def main():
    import argparse
    import json
    import sys
    ap = argparse.ArgumentParser(description="Cascade-safe text replace via placeholder pivot")
    ap.add_argument("--input", required=True, help="input file")
    ap.add_argument("--mapping", required=True, help="mapping JSON file: {source: target}")
    ap.add_argument("--output", default="", help="output (default: stdout)")
    ap.add_argument("--in-place", action="store_true", help="write back to input")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        text = f.read()
    with open(args.mapping, encoding="utf-8") as f:
        mapping = json.load(f)
    new_text, report = pivot_replace(text, mapping)
    if args.in_place:
        with open(args.input, "w", encoding="utf-8") as f:
            f.write(new_text)
    elif args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(new_text)
    else:
        sys.stdout.write(new_text)
    print(f"  pivot_replace: A={report['phase_a_subs']} / B={report['phase_b_subs']} / "
          f"unreplaced={len(report['unreplaced_keys'])} / collisions={len(report['collisions'])}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
