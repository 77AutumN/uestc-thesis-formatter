"""
Hook: format_punctuation — 全角引号替换 & 脚注/参考文献 allowbreak 注入

从 profile 动态加载 quote_style，不硬编码任何学院特定默认值。

Usage:
  被 run_v2.py 管线调用:
    format_punctuation(template_dir, config)

  独立运行:
    python format_punctuation.py <template_dir> --profile <name>

  配置自检 (Smoke Test):
    python format_punctuation.py --profile <name> --dry-run
"""
import argparse
import glob
import json
import os
import re
import sys


def load_profile_config(profile_name: str) -> dict:
    """从 templates/<profile>/profile.json 加载配置"""
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


def format_punctuation(template_dir: str, config: dict):
    print("  [Hook] Running format_punctuation")

    quote_style = config.get("quote_style", "mixed")

    def fix_quotes(text):
        if quote_style == "fullwidth_chinese":
            text = re.sub(r'``', '\u201c', text)
            text = re.sub(r"''", '\u201d', text)
            text = text.replace('\u201c', '\u201c').replace('\u201d', '\u201d')
        return text

    def fix_allowbreak(text):
        def repl_footnote(m):
            content = m.group(1)
            content = re.sub(r',', r',\\allowbreak ', content)
            content = re.sub(r':', r':\\allowbreak ', content)
            return r'\\footnote{' + content + '}'

        return re.sub(r'\\footnote\{([^}]+)\}', repl_footnote, text)

    def fix_bib_allowbreak(text):
        lines = text.split('\\n')
        for i, line in enumerate(lines):
            if line.strip().startswith('\\item'):
                line = re.sub(r',', r',\\allowbreak ', line)
                line = re.sub(r':', r':\\allowbreak ', line)
                lines[i] = line
        return '\\n'.join(lines)

    # 1. Chapters
    ch_dir = os.path.join(template_dir, 'chapter')
    if os.path.exists(ch_dir):
        for ch_file in glob.glob(os.path.join(ch_dir, "*.tex")):
            with open(ch_file, 'r', encoding='utf-8') as f:
                content = f.read()

            content = fix_quotes(content)
            content = fix_allowbreak(content)

            with open(ch_file, 'w', encoding='utf-8') as f:
                f.write(content)

    # 2. Bibliography
    bib_file = os.path.join(template_dir, 'bibliography_categorized.tex')
    if os.path.exists(bib_file):
        with open(bib_file, 'r', encoding='utf-8') as f:
            content = f.read()

        content = fix_quotes(content)
        content = fix_bib_allowbreak(content)

        with open(bib_file, 'w', encoding='utf-8') as f:
            f.write(content)

    print("    -> Punctuation formatting complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Format punctuation hook")
    parser.add_argument("template_dir", nargs="?", help="Template project directory")
    parser.add_argument("--profile", required=True, help="Profile name (e.g. uestc, uestc-marxism)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print resolved config and exit without processing files")
    args = parser.parse_args()

    config = load_profile_config(args.profile)

    if args.dry_run:
        print(f"[dry-run] profile={args.profile}")
        print(f"  quote_style={config.get('quote_style', 'mixed')}")
        sys.exit(0)

    if not args.template_dir:
        parser.error("template_dir is required when not using --dry-run")

    format_punctuation(args.template_dir, config)
