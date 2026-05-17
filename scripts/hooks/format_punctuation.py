import os
import re
import sys
import glob

# Allow `python scripts/hooks/format_punctuation.py` direct invocation.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.text_filters import fix_quotes


_RE_HALFWIDTH_COMMA_TO_FULL = re.compile(r'(?<=[一-鿿，。；：、！？\]\)】])\s*,\s*(?=[一-鿿])')
_RE_HALFWIDTH_DOT_TO_FULL = re.compile(r'(?<=[一-鿿，。；：、！？\]\)】])\s*\.\s*(?=[一-鿿])')
_RE_DEDUPE_FULLCOMMA = re.compile(r'，{2,}')
_RE_DEDUPE_FULLDOT = re.compile(r'。{2,}')
_RE_CROSS_COMMA_DOT = re.compile(r'，\s*。')
_RE_CROSS_DOT_COMMA = re.compile(r'。\s*，')


def normalize_cjk_punct(text: str) -> str:
    """CASE-A round 4 lun51 fix: CJK 段落里半角 ',' '.' → 全角 '，' '。'.

    触发条件 (二者皆需): 半角标点 lookbehind 是 CJK / 全角标点 / 右括号, 且 lookahead 是 CJK.
       这样 'Smith, J.' / '[x,y]' / '1.5' / '\\cite{a,b}' / '$x, y$' 都不动 — 西文/数字/数学
       内的逗号几乎从不接 CJK, lookahead 自动过滤.
    后处理: 连续相同标点 dedupe + 跨标点 '，.' '.，' (CASE-A 实战示例 '示例，.示例') 收为单字.
    """
    text = _RE_HALFWIDTH_COMMA_TO_FULL.sub('，', text)
    text = _RE_HALFWIDTH_DOT_TO_FULL.sub('。', text)
    text = _RE_DEDUPE_FULLCOMMA.sub('，', text)
    text = _RE_DEDUPE_FULLDOT.sub('。', text)
    text = _RE_CROSS_COMMA_DOT.sub('，', text)
    text = _RE_CROSS_DOT_COMMA.sub('，', text)
    return text


def format_punctuation(template_dir: str, config: dict):
    print("  [Hook] Running format_punctuation")

    quote_style = config.get("quote_style", "mixed")

    def fix_allowbreak(text):
        def repl_footnote(m):
            content = m.group(1)
            content = re.sub(r',', r',\\allowbreak ', content)
            content = re.sub(r':', r':\\allowbreak ', content)
            return r'\\footnote{' + content + '}'

        return re.sub(r'\\footnote\{([^}]+)\}', repl_footnote, text)

    def fix_bib_allowbreak(text):
        lines = text.split('\n')
        for i, line in enumerate(lines):
            if line.strip().startswith('\\item'):
                line = re.sub(r',', r',\\allowbreak ', line)
                line = re.sub(r':', r':\\allowbreak ', line)
                lines[i] = line
        return '\n'.join(lines)

    # 1. Chapters
    ch_dir = os.path.join(template_dir, 'chapter')
    if os.path.exists(ch_dir):
        for ch_file in glob.glob(os.path.join(ch_dir, "*.tex")):
            with open(ch_file, 'r', encoding='utf-8') as f:
                content = f.read()

            content = normalize_cjk_punct(content)  # CASE-A: 先归一 CJK 半角→全角
            content = fix_quotes(content, quote_style)
            content = fix_allowbreak(content)

            with open(ch_file, 'w', encoding='utf-8') as f:
                f.write(content)

    # 2. Bibliography
    bib_file = os.path.join(template_dir, 'bibliography_categorized.tex')
    if os.path.exists(bib_file):
        with open(bib_file, 'r', encoding='utf-8') as f:
            content = f.read()
            
        content = fix_quotes(content, quote_style)
        content = fix_bib_allowbreak(content)
        
        with open(bib_file, 'w', encoding='utf-8') as f:
            f.write(content)
            
    print("    -> Punctuation formatting complete.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # We pass template_dir
        format_punctuation(sys.argv[1], {"quote_style": "fullwidth_chinese"})
