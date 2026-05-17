"""redact.py — PII redaction tool for OSS public release.

Implements the substitution rules from `docs/redaction-spec.md`:
- 13-digit student IDs        → <STUDENT_ID>
- Known real student names    → CASE-A
- Absolute Windows paths      → ./
- Internal CASE-NNN codes     → CASE-A

Usage:
    python tools/redact.py --in-place .
    python tools/redact.py --check .       # exit 1 if any pattern still found

Scope:
    Scans **/*.py, **/*.md, **/*.json, **/*.yaml.
    Skips vendor/, .git/, .github/, .pytest_cache/, __pycache__/, tools/.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b20\d{11}\b"), "<STUDENT_ID>"),
    # Known real names from historical case data; extend when new cases are added.
    (re.compile(r"CASE-A|CASE-A|CASE-A|CASE-A"), "CASE-A"),
    # Real English transliterations of the above (CASE-A / CASE-A), case-insensitive.
    (re.compile(r"\b(CASE-A|CASE-A)\b", re.IGNORECASE), "CASE-A"),
    # Non-greedy character class avoids swallowing trailing string delimiters
    # (e.g. r"D:\open claw\X.pdf" must collapse to r"./" not r"./).
    (re.compile(r"D:[\\/]+[Oo]pen claw[\\/][^\s'\"`,)]+"), "./"),
    (re.compile(r"\bCASE-0\d{2}\b"), "CASE-A"),
]

EXTS = {".py", ".md", ".json", ".yaml", ".yml", ".txt", ".tex"}
SKIP_DIRS = {"vendor", ".git", ".github", ".pytest_cache", "__pycache__", "tools",
             ".agent", ".codex_ipc", ".gemini_ipc"}


def iter_files(root: Path):
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in EXTS:
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        yield p


def redact_text(text: str) -> tuple[str, int]:
    total = 0
    for pat, repl in PATTERNS:
        text, n = pat.subn(repl, text)
        total += n
    return text, total


def cmd_inplace(root: Path) -> int:
    grand_total = 0
    files_changed = 0
    for f in iter_files(root):
        try:
            original = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        new, n = redact_text(original)
        if n:
            f.write_text(new, encoding="utf-8")
            print(f"[redact] {f.relative_to(root)}: {n} replacement(s)")
            grand_total += n
            files_changed += 1
    print(f"\nDone: {grand_total} replacement(s) across {files_changed} file(s)")
    return 0


def cmd_check(root: Path) -> int:
    hits: list[tuple[Path, int, str]] = []
    for f in iter_files(root):
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            for pat, _ in PATTERNS:
                if pat.search(line):
                    hits.append((f.relative_to(root), line_no, line.strip()[:120]))
                    break
    if hits:
        print(f"BLOCKED — {len(hits)} PII hit(s):", file=sys.stderr)
        for path, line_no, snippet in hits:
            print(f"  {path}:{line_no}: {snippet}", file=sys.stderr)
        return 1
    print("CLEAN — no PII patterns found")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", type=Path, help="Root directory to scan")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--in-place", action="store_true", help="Apply replacements")
    grp.add_argument("--check", action="store_true", help="Exit 1 if PII remains")
    args = ap.parse_args()
    if not args.path.is_dir():
        print(f"ERROR: {args.path} is not a directory", file=sys.stderr)
        return 2
    return cmd_inplace(args.path) if args.in_place else cmd_check(args.path)


if __name__ == "__main__":
    sys.exit(main())
