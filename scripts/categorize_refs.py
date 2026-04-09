#!/usr/bin/env python3
r"""
categorize_refs.py — 马克思学院 profile: 生成分类参考文献 LaTeX 文件

将 references_raw.txt 中的参考文献按类型分为四类：
  1. 著作类 [M]
  2. 期刊类 [J]
  3. 学位论文类 [D]
  4. 网页报纸类 [N], [EB/OL], [OL], [R/OL] 等

每类独立编号 [1]-[N]，空类不生成。

输出: bibliography_categorized.tex（可直接 \input{} 到 main.tex）

用法:
  python categorize_refs.py <references_raw_path> <output_path>
  例: python categorize_refs.py "extracted/references_raw.txt" "output/bibliography_categorized.tex"
"""

import argparse
import json
import os
import re
import sys


# 文献类型分类规则
CATEGORIES = [
    {
        'key': 'book',
        'label': '一、著作类',
        'patterns': [r'\[M\]', r'［M］', r'\[G\]', r'［G］', r'\[C\]', r'［C］', r'\[Z\]', r'［Z］', r'\[R\]', r'［R］'],
    },
    {
        'key': 'article',
        'label': '二、期刊类',
        'patterns': [r'\[J\]', r'［J］'],
    },
    {
        'key': 'thesis',
        'label': '三、学位论文类',
        'patterns': [r'\[D\]', r'［D］'],
    },
    {
        'key': 'online',
        'label': '四、网页报纸类',
        'patterns': [r'\[N\]', r'［N］', r'\[EB/OL\]', r'［EB/OL］', r'\[OL\]', r'［OL］', r'\[R/OL\]', r'［R/OL］', r'\[N/OL\]', r'［N/OL］'],
    },
]


def load_references(raw_path):
    """加载原始引用文本，返回清理后的条目列表"""
    # Word 原文中可能自带的分类标题，需要过滤掉
    CATEGORY_HEADERS = re.compile(
        r'^.*类[：:]?\s*$'
    )
    refs = []
    with open(raw_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # 跳过 Word 原文中的分类标题行
            if CATEGORY_HEADERS.match(line):
                continue
            # 去掉 [数字] 前缀
            line = re.sub(r'^\[\d+\]\s*', '', line)
            # 去掉尾部注释 （注：...）
            line = re.sub(r'（注：[^）]*）', '', line)
            refs.append(line.strip())
    return refs


def classify_reference(ref_text):
    """根据文献类型标识判断分类"""
    for cat in CATEGORIES:
        for pattern in cat['patterns']:
            if re.search(pattern, ref_text):
                return cat['key']
    return 'unknown'


def escape_latex(text):
    """转义 LaTeX 特殊字符"""
    text = text.replace('&', r'\&')
    text = text.replace('%', r'\%')
    text = text.replace('#', r'\#')
    text = text.replace('_', r'\_')
    return text


def generate_categorized_bibliography(refs):
    """生成分类参考文献 LaTeX 内容"""
    # 分类
    categorized = {cat['key']: [] for cat in CATEGORIES}

    for ref in refs:
        cat_key = classify_reference(ref)
        if cat_key == 'unknown':
            categorized['book'].append(ref) # Fallback unknown to book
        else:
            categorized[cat_key].append(ref)

    # 生成 LaTeX
    lines = []
    lines.append(r'% 分类参考文献 — 自动生成 by categorize_refs.py')
    lines.append(r'% 马克思主义学院格式：按类型分组，每组独立编号')
    lines.append('')
    lines.append(r'\chapter*{参考文献}')
    lines.append(r'\addcontentsline{toc}{chapter}{参考文献}')
    lines.append(r'\markboth{参考文献}{参考文献}')
    lines.append('')

    cat_index = 0
    for cat in CATEGORIES:
        items = categorized[cat['key']]
        if not items:
            continue  # 空类不列

        cat_index += 1
        lines.append(r'\vspace{1em}')
        lines.append(r'\noindent{\heiti ' + cat['label'] + r'}')
        lines.append(r'\vspace{0.5em}')
        lines.append('')
        lines.append(r'\begin{enumerate}[label={[\arabic*]}, leftmargin=2.5em, itemsep=0.2em]')

        for item in items:
            escaped = escape_latex(item)
            lines.append(f'  \\item {escaped}')

        lines.append(r'\end{enumerate}')
        lines.append('')

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(
        description='马克思学院分类参考文献生成器：按著作/期刊/学位论文/网页报纸分类'
    )
    parser.add_argument('input', help='参考文献原文文件 (references_raw.txt)')
    parser.add_argument('output', help='输出 LaTeX 文件路径 (bibliography_categorized.tex)')
    parser.add_argument('--categories-json', default=None,
                        help='自定义分类规则 JSON（从 profile.json 提取）')
    args = parser.parse_args()

    raw_path = args.input
    output_path = args.output

    print("=" * 60)
    print("categorize_refs.py — 分类参考文献生成器")
    print("=" * 60)

    # Step 1: 加载原始引用
    print(f"\n📖 加载: {raw_path}")
    if not os.path.exists(raw_path):
        print(f"  ❌ 文件不存在: {raw_path}")
        sys.exit(1)

    try:
        refs = load_references(raw_path)
        print(f"  共加载 {len(refs)} 条引用")
    except Exception as e:
        print(f"  ❌ 加载失败: {e}")
        sys.exit(1)

    # Step 2: 分类统计
    print("\n📊 分类统计:")
    categorized = {cat['key']: [] for cat in CATEGORIES}
    unknown = []
    for ref in refs:
        cat_key = classify_reference(ref)
        if cat_key == 'unknown':
            unknown.append(ref)
        else:
            categorized[cat_key].append(ref)

    for cat in CATEGORIES:
        count = len(categorized[cat['key']])
        if count > 0:
            print(f"  {cat['label']}: {count} 条")

    if unknown:
        print(f"  ⚠️ 未分类: {len(unknown)} 条")
        for u in unknown:
            display = u[:60] + "..." if len(u) > 60 else u
            print(f"    - {display}")

    # Step 3: 生成 LaTeX
    print(f"\n📝 生成: {output_path}")
    try:
        content = generate_categorized_bibliography(refs)
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"  ✅ 已生成分类参考文献文件")
    except Exception as e:
        print(f"  ❌ 生成失败: {e}")
        sys.exit(1)

    # 保存分类报告
    report = {
        'total_refs': len(refs),
        'categories': {cat['key']: len(categorized[cat['key']]) for cat in CATEGORIES},
        'unknown_count': len(unknown),
        'unknown_items': [u[:100] for u in unknown],
    }
    report_dir = os.path.dirname(output_path) or '.'
    report_path = os.path.join(report_dir, 'categorize_report.json')
    try:
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"  📋 报告: {report_path}")
    except Exception as e:
        print(f"  ⚠️ 报告保存失败: {e}")


if __name__ == '__main__':
    main()

