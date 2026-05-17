"""Shared text filters used across hooks (format_abstract, format_punctuation)."""
import re

_BACKTICK_PAIR = re.compile(r"``")
_APOSTROPHE_PAIR = re.compile(r"''")


def _pair_straight_quotes(text: str) -> str:
    """Replace ASCII `"` with paired curly `“`/`”` in alternating order.

    Even-indexed occurrences (0,2,…) → `“`, odd-indexed (1,3,…) → `”`.
    If the total count is odd, the final unmatched quote is left as ASCII —
    we don't guess a direction.
    """
    if '"' not in text:
        return text
    parts = text.split('"')
    n = len(parts) - 1
    out = [parts[0]]
    for i, segment in enumerate(parts[1:]):
        if n % 2 == 1 and i == n - 1:
            out.append('"')
        elif i % 2 == 0:
            out.append("“")
        else:
            out.append("”")
        out.append(segment)
    return "".join(out)


def fix_quotes(text: str, quote_style: str) -> str:
    """Convert LaTeX ``...'' and straight `"` to fullwidth Chinese quotes.

    No-op unless quote_style == 'fullwidth_chinese'.

    LaTeX-style `` and '' carry open/close intent in the source itself, so
    they map literally. Straight `"` quotes have no direction marker, so
    they're paired by occurrence order.
    """
    if quote_style != "fullwidth_chinese":
        return text
    text = _BACKTICK_PAIR.sub("“", text)
    text = _APOSTROPHE_PAIR.sub("”", text)
    return _pair_straight_quotes(text)
