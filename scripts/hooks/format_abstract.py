"""
Hook: format_abstract — 格式化中英文摘要为 LaTeX 环境

从 profile 动态加载 abstract_keywords_delimiter 和 quote_style，
不硬编码任何学院特定默认值。

Usage:
  被 run_v2.py 管线调用:
    format_abstract(extracted_dir, template_dir, config)

  独立运行:
    python format_abstract.py <extracted_dir> <template_dir> --profile <name>

  配置自检 (Smoke Test):
    python format_abstract.py --profile <name> --dry-run
"""
import argparse
import json
import os
import re
import sys


def load_profile_config(profile_name: str) -> dict:
    """从 templates/<profile>/profile.json 加载配置"""
    # 搜索路径：相对于本脚本 → 相对于 repo root
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(script_dir, '..', '..'))

    candidates = [
        os.path.join(repo_root, 'templates', profile_name, 'profile.json'),
        os.path.join(script_dir, '..', '..', 'templates', profile_name, 'profile.json'),
    ]
    for path in candidates:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    raise FileNotFoundError(
        f"Profile '{profile_name}' not found. Searched: {candidates}"
    )


def format_abstract(extracted_dir: str, template_dir: str, config: dict):
    print(f"  [Hook] Running format_abstract")

    misc_dir = os.path.join(template_dir, "misc")
    os.makedirs(misc_dir, exist_ok=True)

    delimiter = config.get("abstract_keywords_delimiter", ",")

    def fix_quotes(text):
        if config.get("quote_style") == "fullwidth_chinese":
            text = re.sub(r'``', '\u201c', text)
            text = re.sub(r"''", '\u201d', text)
            text = text.replace('\u201c', '\u201c').replace('\u201d', '\u201d')
        return text

    # Chinese abstract
    zh_file = os.path.join(extracted_dir, "abstract_zh.txt")
    if os.path.exists(zh_file):
        with open(zh_file, 'r', encoding='utf-8') as f:
            abs_zh = f.read()

        lines = abs_zh.split('\\n')
        text_lines = []
        kw = ""
        for line in lines:
            if '关键词' in line or '关键词:' in line or '关键词：' in line:
                kw = re.sub(r'^.*?关键词[：:]?\s*', '', line).strip()
            else:
                text_lines.append(line)

        abs_zh_clean = fix_quotes('\\n'.join(text_lines).strip())
        zh_out = f"\\begin{{chineseabstract}}\\n{abs_zh_clean}\\n\\chinesekeyword{{{kw}}}\\n\\end{{chineseabstract}}\\n"

        with open(os.path.join(misc_dir, 'chinese_abstract.tex'), 'w', encoding='utf-8') as f:
            f.write(zh_out)

    # English abstract
    en_file = os.path.join(extracted_dir, "abstract_en.txt")
    if os.path.exists(en_file):
        with open(en_file, 'r', encoding='utf-8') as f:
            abs_en = f.read()

        abs_en = re.sub(r'ABSTRACT\\n?', '', abs_en)

        lines = abs_en.split('\\n')
        text_lines = []
        kw_en = ""
        for line in lines:
            if 'Keywords' in line or 'Keywords:' in line or 'Keywords：' in line:
                kw_en = re.sub(r'^.*?Keywords?[：:]?\s*', '', line, flags=re.IGNORECASE).strip()
            else:
                text_lines.append(line)

        abs_en_clean = fix_quotes('\\n'.join(text_lines).strip())
        kw_en = re.sub(r'[,;]\s*', f'{delimiter} ', kw_en)

        en_out = f"\\begin{{englishabstract}}\\n{abs_en_clean}\\n\\englishkeyword{{{kw_en}}}\\n\\end{{englishabstract}}\\n"

        with open(os.path.join(misc_dir, 'english_abstract.tex'), 'w', encoding='utf-8') as f:
            f.write(en_out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Format abstract hook")
    parser.add_argument("extracted_dir", nargs="?", help="Extracted content directory")
    parser.add_argument("template_dir", nargs="?", help="Template project directory")
    parser.add_argument("--profile", required=True, help="Profile name (e.g. uestc, uestc-marxism)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print resolved config and exit without processing files")
    args = parser.parse_args()

    config = load_profile_config(args.profile)

    if args.dry_run:
        print(f"[dry-run] profile={args.profile}")
        print(f"  abstract_keywords_delimiter={config.get('abstract_keywords_delimiter', ',')}")
        print(f"  quote_style={config.get('quote_style', 'mixed')}")
        sys.exit(0)

    if not args.extracted_dir or not args.template_dir:
        parser.error("extracted_dir and template_dir are required when not using --dry-run")

    format_abstract(args.extracted_dir, args.template_dir, config)
