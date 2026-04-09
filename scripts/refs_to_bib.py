#!/usr/bin/env python3
"""
refs_to_bib.py — 中文学术参考文献 (GB/T 7714) → BibTeX

基于 UESTC 实战验证，吸收 Gemini Review 的 7 条异常格式处理建议：
1. 尾部注释剥离
2. 国籍前缀处理 [法]、[德] 等
3. 全局唯一 Citekey (pinyin + year + 去重后缀)
4. 译者分离
5. 全半角标点统一 (NFKC)
6. 不规则空格压缩
7. 按 [M/J/D/N] Strategy Pattern 分类解析

Usage:
    python refs_to_bib.py --input references_raw.txt --output reference.bib
"""

import argparse
import json
import os
import re
import sys
import unicodedata


# === 预处理 ===

def normalize(text):
    """全角→半角, 压缩空格"""
    text = unicodedata.normalize('NFKC', text)
    mapping = {
        '：': ':', '，': ',', '；': ';',
        '（': '(', '）': ')', '。': '.',
        '【': '[', '】': ']',
    }
    for k, v in mapping.items():
        text = text.replace(k, v)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def strip_trailing_note(text):
    """剥离尾部注释 (Review #1)"""
    text = re.sub(r'[(](注[:].*?)[)]$', '', text).strip()
    return text


def extract_nationality(author_str):
    """提取国籍前缀: [法]让·鲍德里亚 → ('法', '让·鲍德里亚')"""
    m = re.match(r'^\[([^\]]+)\]\s*', author_str)
    if m:
        return m.group(1), author_str[m.end():].strip()
    return None, author_str


def extract_translator(text):
    """分离译者: '刘成富,全志钢译' → ('刘成富 and 全志钢', rest)"""
    m = re.search(r'\.([^.]+?)译\.', text)
    if m:
        translators = m.group(1).strip()
        translators = re.sub(r'[,，]', ' and ', translators)
        remaining = text[:m.start()] + '.' + text[m.end():]
        return translators, remaining
    return None, text


def generate_citekey(author, year, used_keys):
    """生成全局唯一 Citekey: author_year[a/b/c]"""
    _, clean_author = extract_nationality(author)

    if re.search(r'[\u4e00-\u9fff]', clean_author):
        surname = clean_author[0]
        pinyin_map = {
            '马': 'ma', '蓝': 'lan', '陈': 'chen', '王': 'wang', '孙': 'sun',
            '孟': 'meng', '刘': 'liu', '杨': 'yang', '喻': 'yu', '张': 'zhang',
            '李': 'li', '郭': 'guo', '胡': 'hu', '曹': 'cao', '丁': 'ding',
            '董': 'dong', '吴': 'wu', '彭': 'peng', '蒋': 'jiang', '汪': 'wang2',
            '陶': 'tao', '姚': 'yao', '赵': 'zhao', '罗': 'luo', '黄': 'huang',
            '徐': 'xu', '周': 'zhou', '高': 'gao', '宋': 'song', '许': 'xu2',
            '钱': 'qian', '郑': 'zheng', '习': 'xi', '毛': 'mao', '邓': 'deng',
            '林': 'lin', '叶': 'ye', '梁': 'liang', '韩': 'han', '唐': 'tang',
            '冯': 'feng', '贺': 'he', '夏': 'xia', '田': 'tian', '任': 'ren',
        }
        key_base = pinyin_map.get(surname, surname)
    else:
        parts = clean_author.split('·')
        key_base = parts[-1].lower() if parts else clean_author[:4].lower()

    key = f"{key_base}{year}"
    if key in used_keys:
        for suffix in 'abcdefghij':
            candidate = f"{key}{suffix}"
            if candidate not in used_keys:
                key = candidate
                break

    used_keys.add(key)
    return key


# === 条目解析器 (Strategy Pattern) ===

def parse_book(text, citekey):
    """解析 [M] 著作"""
    translator, text = extract_translator(text)
    parts = text.split('[M].')
    if len(parts) < 2:
        return None, f"无法解析著作: {text[:60]}"

    author_title = parts[0].strip()
    pub_info = parts[1].strip()

    dot_pos = author_title.find('.')
    author = author_title[:dot_pos].strip() if dot_pos != -1 else author_title
    title = author_title[dot_pos+1:].strip() if dot_pos != -1 else ""

    publisher, address, year = "", "", ""
    m = re.search(r'(.+?):(.+?),(\d{4})', pub_info)
    if m:
        address, publisher, year = m.group(1).strip(), m.group(2).strip(), m.group(3)
    else:
        m2 = re.search(r'(\d{4})', pub_info)
        year = m2.group(1) if m2 else "0000"
        publisher = pub_info

    _, clean_author = extract_nationality(author)

    bib = f"@book{{{citekey},\n"
    bib += f"  author = {{{clean_author}}},\n"
    bib += f"  title = {{{title}}},\n"
    if translator:
        bib += f"  translator = {{{translator}}},\n"
    bib += f"  publisher = {{{publisher}}},\n"
    if address:
        bib += f"  address = {{{address}}},\n"
    bib += f"  year = {{{year}}},\n"
    bib += f"}}\n\n"
    return bib, None


def parse_article(text, citekey):
    """解析 [J] 期刊"""
    parts = text.split('[J].')
    if len(parts) < 2:
        return None, f"无法解析期刊: {text[:60]}"

    author_title = parts[0].strip()
    journal_info = parts[1].strip()

    dot_pos = author_title.find('.')
    author = author_title[:dot_pos].strip() if dot_pos != -1 else author_title
    title = author_title[dot_pos+1:].strip() if dot_pos != -1 else ""

    journal, year, number, pages = "", "", "", ""
    m = re.match(r'(.+?),\s*(\d{4})\s*,\s*\(?(\d+)\)?\s*:\s*([\d\-+]+)', journal_info)
    if m:
        journal, year, number, pages = m.group(1).strip(), m.group(2), m.group(3), m.group(4)
    else:
        m2 = re.match(r'(.+?),\s*(\d{4})\s*,?\s*(\d+)\s*\((\d+)\)\s*:\s*([\d\-+]+)', journal_info)
        if m2:
            journal, year, number, pages = m2.group(1).strip(), m2.group(2), m2.group(4), m2.group(5)
        else:
            m3 = re.search(r'(\d{4})', journal_info)
            year = m3.group(1) if m3 else "0000"
            journal = journal_info

    bib = f"@article{{{citekey},\n"
    bib += f"  author = {{{author}}},\n"
    bib += f"  title = {{{title}}},\n"
    bib += f"  journal = {{{journal}}},\n"
    bib += f"  year = {{{year}}},\n"
    if number:
        bib += f"  number = {{{number}}},\n"
    if pages:
        bib += f"  pages = {{{pages}}},\n"
    bib += f"}}\n\n"
    return bib, None


def parse_thesis(text, citekey):
    """解析 [D] 学位论文"""
    parts = text.split('[D].')
    if len(parts) < 2:
        return None, f"无法解析学位论文: {text[:60]}"

    author_title = parts[0].strip()
    school_info = parts[1].strip()

    dot_pos = author_title.find('.')
    author = author_title[:dot_pos].strip() if dot_pos != -1 else author_title
    title = author_title[dot_pos+1:].strip() if dot_pos != -1 else ""

    school, year = "", ""
    m = re.match(r'(.+?),\s*(\d{4})', school_info)
    if m:
        school, year = m.group(1).strip(), m.group(2)

    bib = f"@mastersthesis{{{citekey},\n"
    bib += f"  author = {{{author}}},\n"
    bib += f"  title = {{{title}}},\n"
    bib += f"  school = {{{school}}},\n"
    bib += f"  year = {{{year}}},\n"
    bib += f"  type = {{硕士学位论文}},\n"
    bib += f"}}\n\n"
    return bib, None


def parse_newspaper(text, citekey):
    """解析 [N] 报纸"""
    parts = text.split('[N].')
    if len(parts) < 2:
        return None, f"无法解析报纸: {text[:60]}"

    author_title = parts[0].strip()
    pub_info = parts[1].strip()

    dot_pos = author_title.find('.')
    author = author_title[:dot_pos].strip() if dot_pos != -1 else author_title
    title = author_title[dot_pos+1:].strip() if dot_pos != -1 else ""

    year = ""
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', pub_info)
    if m:
        year = m.group(1)

    journal = re.split(r',', pub_info)[0].strip() if ',' in pub_info else pub_info

    bib = f"@article{{{citekey},\n"
    bib += f"  author = {{{author}}},\n"
    bib += f"  title = {{{title}}},\n"
    bib += f"  journal = {{{journal}}},\n"
    bib += f"  year = {{{year}}},\n"
    bib += f"  note = {{报纸}},\n"
    bib += f"}}\n\n"
    return bib, None


# === 主流程 ===

def main():
    parser = argparse.ArgumentParser(description='中文学术参考文献 → BibTeX')
    parser.add_argument('--input', required=True, help='参考文献原文文件')
    parser.add_argument('--output', required=True, help='输出 .bib 文件路径')
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"❌ 文件不存在: {args.input}")
        sys.exit(1)

    with open(args.input, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    used_keys = set()
    bib_entries = []
    report = {'total': 0, 'success': 0, 'warnings': []}
    cite_map = {}
    idx = 0

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        idx += 1
        
        if line.endswith('：') or line.endswith(':'):
            continue  # 跳过分类标题

        line = normalize(line)
        line = strip_trailing_note(line)

        # 可选的 [数字] 前缀 — 有则剥离，无则直接处理
        m = re.match(r'^\[(\d+)\]\s*', line)
        if m:
            entry_text = line[m.end():].strip()
        else:
            entry_text = line

        # 跳过没有文献类型标记的行
        if not re.search(r'\[(M|J|D|N|C|R|S|P|Z)\]', entry_text):
            report['warnings'].append({'type': 'SKIP', 'text': line[:80]})
            continue

        report['total'] += 1

        year_match = re.search(r'(\d{4})', entry_text)
        year = year_match.group(1) if year_match else "0000"

        dot_pos = entry_text.find('.')
        author_part = entry_text[:dot_pos].strip() if dot_pos != -1 else entry_text[:10]
        citekey = generate_citekey(author_part, year, used_keys)
        
        cite_map[str(idx)] = citekey

        # Strategy Pattern: 按类型分路
        bib, warning = None, None
        if '[M]' in entry_text:
            bib, warning = parse_book(entry_text, citekey)
        elif '[J]' in entry_text:
            bib, warning = parse_article(entry_text, citekey)
        elif '[D]' in entry_text:
            bib, warning = parse_thesis(entry_text, citekey)
        elif '[N]' in entry_text:
            bib, warning = parse_newspaper(entry_text, citekey)
        else:
            warning = f"未知文献类型: {entry_text[:60]}"

        if bib:
            bib_entries.append(bib)
            report['success'] += 1
        if warning:
            report['warnings'].append({'type': 'PARSE_ERROR', 'text': warning})
            bib_entries.append(f"% WARNING: {warning}\n")

    # 写入 .bib
    output_dir = os.path.dirname(args.output) or '.'
    os.makedirs(output_dir, exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(f"% 自动生成的 BibTeX 文件\n")
        f.write(f"% 共 {len(bib_entries)} 条文献\n")
        f.write(f"% 生成工具: refs_to_bib.py (thesis-formatter skill)\n\n")
        for entry in bib_entries:
            f.write(entry)

    # 写入 cite_map.json
    input_dir = os.path.dirname(args.input) or '.'
    cite_map_path = os.path.join(input_dir, 'cite_map.json')
    with open(cite_map_path, 'w', encoding='utf-8') as f:
        json.dump(cite_map, f, ensure_ascii=False, indent=2)

    # 写入报告
    report_path = os.path.join(output_dir, 'refs_report.json')
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"✅ 生成 {report['success']}/{report['total']} 条 BibTeX → {args.output}")
    if report['warnings']:
        print(f"⚠️ {len(report['warnings'])} 条警告，详见 {report_path}")


if __name__ == '__main__':
    main()
