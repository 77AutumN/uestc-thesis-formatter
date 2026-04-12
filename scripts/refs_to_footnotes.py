#!/usr/bin/env python3
r"""
refs_to_footnotes.py — 马克思学院 profile: \cite{key} → \footnote{完整文献条目}

将正文中的 \cite{citekey} 替换为 \footnote{GB/T 7714 格式化的完整文献条目}。
每次引用都生成独立脚注（含重复引用），UESTC cls 已有 footmisc 每页重编号。

数据源:
  - references_raw.txt: 人工排版好的原始引用文本
  - cite_map.json: {index → citekey} 映射表
  - reference.bib: 用于确定 citekey 顺序

用法:
  python refs_to_footnotes.py <extracted_dir> <chapters_dir>
  例: python refs_to_footnotes.py "extracted" "output/chapter"
"""

import argparse
import os
import re
import json
import glob
import sys


def load_raw_references(raw_path):
    """
    读取 references_raw.txt，返回按顺序排列的引用文本列表（1-based index）。
    去掉 [数字] 前缀，去掉尾部注释 （注：...）
    """
    refs = {}
    idx = 0
    with open(raw_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            idx += 1

            # 去掉 [数字] 前缀
            line = re.sub(r'^\[\d+\]\s*', '', line)

            # 去掉括号注释 （注：...）
            line = re.sub(r'（注：[^）]*）', '', line)

            # 去掉国籍标识 [法] [美] 等 — 保留，因为这是正式引用的一部分
            # 不做去除

            refs[idx] = line.strip()

    return refs


def build_citekey_to_text(cite_map_path, raw_refs):
    """
    结合 cite_map.json 和 raw references，建立 citekey → 引用文本 的映射。
    cite_map.json: {"1": "ma2012", "2": "ma2001", ...}
    """
    with open(cite_map_path, 'r', encoding='utf-8') as f:
        cite_map = json.load(f)

    citekey_to_text = {}
    for idx_str, citekey in cite_map.items():
        idx = int(idx_str)
        if idx in raw_refs:
            citekey_to_text[citekey] = raw_refs[idx]
        else:
            print(f"  ⚠️ 警告: cite_map 索引 [{idx}] ({citekey}) 在 raw references 中无对应条目")

    return citekey_to_text


def escape_for_footnote(text):
    """
    转义 LaTeX 特殊字符，确保脚注内容安全。
    注意：全角标点在中文文献中很常见，不需要转义。
    """
    # 只转义最常见的 LaTeX 特殊字符
    text = text.replace('&', r'\&')
    text = text.replace('%', r'\%')
    text = text.replace('#', r'\#')
    text = text.replace('_', r'\_')
    # 不转义 ~ 和 ^ ，中文文献中罕见
    return text


def replace_cite_with_footnote(tex_path, citekey_to_text):
    r"""
    将 .tex 文件中的 \cite{key} 和 \cite{key1,key2} 替换为 \footnote{...}。
    多引用 \cite{a,b} → \footnote{refA}\footnote{refB}
    """
    with open(tex_path, 'r', encoding='utf-8') as f:
        content = f.read()

    replaced_count = 0
    missing_keys = set()

    def replace_match(match):
        nonlocal replaced_count
        keys_str = match.group(1).strip()
        keys = [k.strip() for k in keys_str.split(',')]

        footnotes = []
        all_found = True
        for key in keys:
            if key in citekey_to_text:
                text = escape_for_footnote(citekey_to_text[key])
                footnotes.append(f'\\footnote{{{text}}}')
            else:
                missing_keys.add(key)
                all_found = False
                # 保留为注释标记，不丢失引用
                footnotes.append(f'\\footnote{{[TODO: {key}]}}')

        replaced_count += 1
        return ''.join(footnotes)

    # 匹配 \cite{...} 模式
    content = re.sub(r'\\cite\{([^}]+)\}', replace_match, content)

    with open(tex_path, 'w', encoding='utf-8') as f:
        f.write(content)

    return replaced_count, missing_keys


def main():
    parser = argparse.ArgumentParser(
        description='马克思学院引用格式转换：\\cite{key} → \\footnote{完整文献条目}'
    )
    parser.add_argument('extracted_dir', help='提取输出目录（含 references_raw.txt 和 cite_map.json）')
    parser.add_argument('chapters_dir', help='章节 .tex 文件目录')
    parser.add_argument('--dry-run', action='store_true', help='仅报告将做的修改，不实际写入')
    args = parser.parse_args()

    extracted_dir = args.extracted_dir
    chapters_dir = args.chapters_dir

    raw_path = os.path.join(extracted_dir, 'references_raw.txt')
    cite_map_path = os.path.join(extracted_dir, 'cite_map.json')

    print("=" * 60)
    print("refs_to_footnotes.py — 马克思学院引用格式转换")
    print("=" * 60)

    # Step 1: 加载原始引用文本
    print("\n📖 Step 1: 加载 references_raw.txt")
    if not os.path.exists(raw_path):
        print(f"  ❌ 文件不存在: {raw_path}")
        sys.exit(1)

    try:
        raw_refs = load_raw_references(raw_path)
        print(f"  共加载 {len(raw_refs)} 条原始引用")
    except Exception as e:
        print(f"  ❌ 加载失败: {e}")
        sys.exit(1)

    # Step 2: 建立 citekey → 引用文本映射
    print("\n🔗 Step 2: 建立 citekey → 引用文本映射")
    if not os.path.exists(cite_map_path):
        print(f"  ❌ 文件不存在: {cite_map_path}")
        sys.exit(1)

    try:
        citekey_to_text = build_citekey_to_text(cite_map_path, raw_refs)
        print(f"  共建立 {len(citekey_to_text)} 条映射")
    except Exception as e:
        print(f"  ❌ 映射构建失败: {e}")
        sys.exit(1)

    # 打印前5条验证
    for i, (key, text) in enumerate(citekey_to_text.items()):
        if i >= 5:
            break
        display = text[:60] + "..." if len(text) > 60 else text
        print(f"  {key} → {display}")

    # Step 3: 替换 .tex 文件中的 \cite{} → \footnote{}
    print("\n📝 Step 3: 替换 \\cite{{}} → \\footnote{{}}")
    tex_files = sorted(glob.glob(os.path.join(chapters_dir, 'ch*.tex')))

    if not tex_files:
        print(f"  ❌ 未找到章节文件: {chapters_dir}/ch*.tex")
        sys.exit(1)

    if args.dry_run:
        print("  [DRY RUN] 仅扫描，不修改文件")

    total_replaced = 0
    all_missing = set()

    for tex in tex_files:
        try:
            if args.dry_run:
                # 读取但不写入
                with open(tex, 'r', encoding='utf-8') as f:
                    content = f.read()
                count = len(re.findall(r'\\cite\{[^}]+\}', content))
                basename = os.path.basename(tex)
                print(f"  {basename}: {count} 处 \\cite{{}} 待替换")
                total_replaced += count
            else:
                count, missing = replace_cite_with_footnote(tex, citekey_to_text)
                basename = os.path.basename(tex)
                print(f"  {basename}: {count} 处替换")
                total_replaced += count
                all_missing.update(missing)
        except Exception as e:
            print(f"  ⚠️ 处理 {os.path.basename(tex)} 失败: {e}")
            all_missing.add(f"FILE_ERROR:{os.path.basename(tex)}")

    action = "扫描到" if args.dry_run else "替换"
    print(f"\n✅ 总计{action} {total_replaced} 处引用 → 脚注")

    if all_missing:
        print(f"\n⚠️ 以下 {len(all_missing)} 个 citekey 未找到对应引用文本:")
        for key in sorted(all_missing):
            print(f"  - {key}")

    # 保存转换报告
    report = {
        'total_replaced': total_replaced,
        'total_refs': len(citekey_to_text),
        'missing_keys': sorted(all_missing),
        'files_processed': [os.path.basename(f) for f in tex_files],
        'dry_run': args.dry_run,
    }
    report_path = os.path.join(extracted_dir, 'footnote_report.json')
    try:
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n📋 报告已保存: {report_path}")
    except Exception as e:
        print(f"\n⚠️ 报告保存失败: {e}")


if __name__ == '__main__':
    main()

