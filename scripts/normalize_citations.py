#!/usr/bin/env python3
r"""normalize_citations.py

Bridge script: convert Word-style [数字] citation markers in LaTeX chapters
to \cite{citekey} format using cite_map.json.

Handles:
  - Single:  [4]       → \cite{让2014}
  - Range:   [4-6]     → \cite{让2014,赫2008,居2006}
  - List:    [22, 32]  → \cite{cao2022,yao2022}
  - Mixed:   [4, 9-11] → \cite{让2014,lan2018,chen2023,wang2023}

Usage:
  python normalize_citations.py <cite_map.json> <chapters_dir>
"""

import json
import os
import re
import sys
import glob


def load_cite_map(path: str) -> dict:
    """Load cite_map.json → {int_index: citekey}"""
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    # Convert string keys to int for easy range lookups
    return {int(k): v for k, v in raw.items()}


def expand_citation_token(token: str, cite_map: dict) -> list:
    """Expand a single token like '4', '4-6' into a list of citekeys.
    
    Returns list of citekeys, or empty list if any index is missing.
    """
    token = token.strip()
    keys = []

    # Range: "4-6"
    range_match = re.match(r"^(\d+)\s*[-–—]\s*(\d+)$", token)
    if range_match:
        start, end = int(range_match.group(1)), int(range_match.group(2))
        for i in range(start, end + 1):
            if i in cite_map:
                keys.append(cite_map[i])
            else:
                # Missing index — still include as fallback
                keys.append(f"MISSING_{i}")
        return keys

    # Single number: "4"
    single_match = re.match(r"^(\d+)$", token)
    if single_match:
        idx = int(single_match.group(1))
        if idx in cite_map:
            return [cite_map[idx]]
        else:
            return [f"MISSING_{idx}"]

    return []


def convert_bracket_to_cite(text: str, cite_map: dict, stats: dict) -> str:
    r"""Replace [数字] patterns with \cite{citekey} in text.
    
    Pattern matches: [4], [4-6], [22, 32], [4, 9-11, 20] etc.
    Does NOT match: \begin{enumerate}[label=...], [M], [J], [D] etc.
    """

    # Pattern: [ followed by digits/ranges/commas, then ]
    # Must not be preceded by backslash (LaTeX commands like \begin{...}[...])
    # Note: do NOT use (?<!\w) as \w matches Chinese characters in Unicode mode
    pattern = r"(?<!\\)\[(\d[\d\s,，\-–—]*\d|\d)\]"

    def replacer(match):
        full_match = match.group(0)  # e.g., "[4-6]" or "[22, 32]"
        inner = match.group(1)       # e.g., "4-6" or "22, 32"

        # Split by comma (both Chinese and English)
        tokens = re.split(r"[,，]", inner)
        
        all_keys = []
        for token in tokens:
            keys = expand_citation_token(token, cite_map)
            all_keys.extend(keys)

        if not all_keys:
            return full_match  # Can't resolve, leave original

        # Check for missing references
        missing = [k for k in all_keys if k.startswith("MISSING_")]
        if missing:
            stats["warnings"].append(
                f"引用 {full_match} 中部分序号无法映射: {missing}"
            )
            # Still convert the resolvable ones
            all_keys = [k for k in all_keys if not k.startswith("MISSING_")]
            if not all_keys:
                return full_match

        stats["replaced"] += 1
        cite_str = ",".join(all_keys)
        return rf"\cite{{{cite_str}}}"

    return re.sub(pattern, replacer, text)


def process_file(filepath: str, cite_map: dict, stats: dict) -> bool:
    r"""Process a single .tex file, replacing [数字] with \cite{key}."""
    with open(filepath, "r", encoding="utf-8") as f:
        original = f.read()

    file_stats = {"replaced": 0, "warnings": []}
    converted = convert_bracket_to_cite(original, cite_map, file_stats)

    if file_stats["replaced"] > 0:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(converted)
        stats["files_modified"] += 1

    stats["total_replaced"] += file_stats["replaced"]
    stats["warnings"].extend(file_stats["warnings"])
    
    basename = os.path.basename(filepath)
    if file_stats["replaced"] > 0:
        print(f"  ✅ {basename}: {file_stats['replaced']} 处引用已转换")
    else:
        print(f"  ⏭  {basename}: 无需转换")
    
    if file_stats["warnings"]:
        for w in file_stats["warnings"]:
            print(f"    ⚠️ {w}")

    return True


def main():
    if len(sys.argv) < 3:
        print("用法: python normalize_citations.py <cite_map.json> <chapters_dir>")
        sys.exit(1)

    cite_map_path = sys.argv[1]
    chapters_dir = sys.argv[2]

    # Validate inputs
    if not os.path.exists(cite_map_path):
        print(f"❌ cite_map.json 不存在: {cite_map_path}")
        sys.exit(1)

    if not os.path.isdir(chapters_dir):
        print(f"❌ 章节目录不存在: {chapters_dir}")
        sys.exit(1)

    print(f"\n{'='*50}")
    print(f"  Citation Normalizer: [数字] → \\cite{{key}}")
    print(f"{'='*50}")

    # Load cite_map
    cite_map = load_cite_map(cite_map_path)
    print(f"  映射表: {len(cite_map)} 条引用")

    # Find all .tex files
    tex_files = sorted(glob.glob(os.path.join(chapters_dir, "ch*.tex")))
    if not tex_files:
        print(f"  ⚠️ 未找到 ch*.tex 文件: {chapters_dir}")
        sys.exit(0)

    print(f"  章节文件: {len(tex_files)} 个\n")

    # Process
    stats = {
        "total_replaced": 0,
        "files_modified": 0,
        "warnings": [],
    }

    for tex_file in tex_files:
        process_file(tex_file, cite_map, stats)

    # Summary
    print(f"\n{'─'*50}")
    print(f"  总计: {stats['total_replaced']} 处引用转换, "
          f"{stats['files_modified']}/{len(tex_files)} 个文件被修改")
    if stats["warnings"]:
        print(f"  警告: {len(stats['warnings'])} 条")
    print(f"{'─'*50}\n")

    # Save report
    report_path = os.path.join(chapters_dir, "normalize_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    # CRITICAL: Assert that conversions happened for marxism profile
    if stats["total_replaced"] == 0:
        print("❌ 严重: 未找到任何 [数字] 引用标记，脚注转换将无法生效！")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
