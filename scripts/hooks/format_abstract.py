"""format_abstract hook — write misc/{chinese,english}_abstract.tex.

CASE-A rewrite: the previous version had three bugs:
  (1) split('\\n') used the LITERAL two-char string '\\n' as separator (escaped
      twice in source), so abstract text was never split into lines and the
      keyword extractor matched nothing
  (2) output template wrote literal '\\n' instead of real newlines, producing
      uncompilable LaTeX
  (3) used forbidden DissertUESTC macros (\\chineseabstract, \\chinesekeyword);
      v2 engine expects \\zhabstract, \\zhkeywords, \\enabstract, \\enkeywords

Also: drop trailing TOC bleed (e.g. "外文资料原文 9", "ABSTRACT") that the
extractor sometimes leaves on the abstract txts.
"""
import os
import re
import sys

# Allow `python scripts/hooks/format_abstract.py` direct invocation.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.text_filters import fix_quotes


# Garbage lines often appended to abstract_*.txt by the extractor's section
# detector when the source docx has a ToC near the abstract. Strip these.
_ZH_TRAILING_GARBAGE = ("ABSTRACT",)
_EN_TRAILING_GARBAGE_PATTERNS = (
    r"^外文资料(原文|译文)\s*\d*\s*$",
    r"^ABSTRACT\s*$",
    r"^摘\s*要\s*$",
)


def _strip_trailing_garbage(text: str, en: bool = False) -> str:
    lines = text.splitlines()
    while lines:
        last = lines[-1].strip()
        if not last:
            lines.pop()
            continue
        is_garbage = False
        if en:
            for pat in _EN_TRAILING_GARBAGE_PATTERNS:
                if re.match(pat, last):
                    is_garbage = True
                    break
        else:
            if last in _ZH_TRAILING_GARBAGE:
                is_garbage = True
        if is_garbage:
            lines.pop()
        else:
            break
    return "\n".join(lines)


def format_abstract(extracted_dir: str, template_dir: str, config: dict):
    print(f"  [Hook] Running format_abstract")

    misc_dir = os.path.join(template_dir, "misc")
    os.makedirs(misc_dir, exist_ok=True)

    delimiter = config.get("abstract_keywords_delimiter", ",")
    quote_style = config.get("quote_style", "")

    # Chinese abstract
    zh_file = os.path.join(extracted_dir, "abstract_zh.txt")
    if os.path.exists(zh_file):
        with open(zh_file, "r", encoding="utf-8") as f:
            abs_zh = _strip_trailing_garbage(f.read(), en=False)
        lines = abs_zh.split("\n")
        text_lines = []
        kw = ""
        for line in lines:
            if "关键词" in line:
                kw = re.sub(r"^.*?关键词[：:]?\s*", "", line).strip()
            else:
                text_lines.append(line)

        abs_zh_clean = fix_quotes("\n".join(text_lines).strip(), quote_style)
        zh_out = (
            "\\zhabstract\n"
            f"{abs_zh_clean}\n"
            f"\\zhkeywords{{{kw}}}\n"
        )
        with open(os.path.join(misc_dir, "chinese_abstract.tex"), "w", encoding="utf-8") as f:
            f.write(zh_out)

    # English abstract
    en_file = os.path.join(extracted_dir, "abstract_en.txt")
    if os.path.exists(en_file):
        with open(en_file, "r", encoding="utf-8") as f:
            abs_en = _strip_trailing_garbage(f.read(), en=True)
        # Remove leading "ABSTRACT" header line if present
        abs_en = re.sub(r"^\s*ABSTRACT\s*\n?", "", abs_en, flags=re.IGNORECASE)
        lines = abs_en.split("\n")
        text_lines = []
        kw_en = ""
        for line in lines:
            if re.search(r"Keywords?[：:]", line, re.IGNORECASE):
                kw_en = re.sub(r"^.*?Keywords?[：:]?\s*", "", line, flags=re.IGNORECASE).strip()
            else:
                text_lines.append(line)

        abs_en_clean = fix_quotes("\n".join(text_lines).strip(), quote_style)
        # Re-normalize keyword delimiter per profile (bachelor=',', marxism=';' historically)
        kw_en = re.sub(r"[,;]\s*", f"{delimiter} ", kw_en).rstrip(", ")

        en_out = (
            "\\enabstract\n"
            f"{abs_en_clean}\n"
            f"\\enkeywords{{{kw_en}}}\n"
        )
        with open(os.path.join(misc_dir, "english_abstract.tex"), "w", encoding="utf-8") as f:
            f.write(en_out)


if __name__ == "__main__":
    if len(sys.argv) > 2:
        format_abstract(sys.argv[1], sys.argv[2],
                        {"abstract_keywords_delimiter": ",", "quote_style": "fullwidth_chinese"})
