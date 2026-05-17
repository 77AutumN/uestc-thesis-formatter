"""redact.py — PII redaction tool for OSS public release.

Implements the substitution rules from `docs/redaction-spec.md`:
- 13-digit student IDs        → <STUDENT_ID>
- Private real names          → CASE-A   (list loaded at runtime, see below)
- Absolute Windows paths      → ./
- Internal CASE-NNN codes     → CASE-A

Usage:
    python tools/redact.py --in-place .
    python tools/redact.py --check .       # exit 1 if any pattern still found

Configuration — private name list:
    Real student/advisor names are NOT hardcoded in this file. They live in
    `.redact-names.local.txt` at the repo root, which is gitignored and never
    committed. Format: one CJK or ASCII name per line; lines starting with `#`
    are ignored.

    On a clean OSS clone the file is absent and the name-replacement pass is a
    no-op (high-entropy patterns like student IDs / paths still run). In CI,
    the workflow re-creates the file from the `REDACT_NAMES` repo secret.

Scope:
    Scans **/*.py, **/*.md, **/*.json, **/*.yaml, **/*.yml, **/*.txt, **/*.tex.
    Skips vendor/, .git/, .github/, .pytest_cache/, __pycache__/, tools/.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_PRIVATE_NAMES_FILE = Path(__file__).resolve().parent.parent / ".redact-names.local.txt"


def _load_private_names() -> list[str]:
    """Read the gitignored private-name list. Returns [] if the file is absent."""
    if not _PRIVATE_NAMES_FILE.is_file():
        return []
    names: list[str] = []
    for raw in _PRIVATE_NAMES_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            names.append(line)
    return names


def _build_patterns() -> list[tuple[re.Pattern[str], str]]:
    pats: list[tuple[re.Pattern[str], str]] = [
        (re.compile(r"\b20\d{11}\b"), "<STUDENT_ID>"),
    ]
    names = _load_private_names()
    cjk_names = [n for n in names if re.search(r"[一-鿿]", n)]
    ascii_names = [n for n in names if n not in cjk_names]
    if cjk_names:
        pats.append((re.compile("|".join(re.escape(n) for n in cjk_names)), "CASE-A"))
    if ascii_names:
        pats.append((
            re.compile(r"\b(?:" + "|".join(re.escape(n) for n in ascii_names) + r")\b",
                       re.IGNORECASE),
            "CASE-A",
        ))
    pats.extend([
        # Collapse CASE-NNN/NNN/NNN sequences first so partial-redacts don't leave dangling.
        (re.compile(r"\bCASE-0\d{2}(?:[/,\s]+0\d{2})+\b"), "CASE-A"),
        (re.compile(r"\bCASE-A[/,\s]+0\d{2}(?:[/,\s]+0\d{2})*\b"), "CASE-A"),
        # Drive-letter path (case-insensitive D:/d:; non-greedy class avoids eating delimiters).
        (re.compile(r"[Dd]:[\\/]+[Oo]pen claw[\\/][^\s'\"`,)]+"), "./"),
        # Bare project-name reference (no drive prefix) — collapse to ./ as well.
        (re.compile(r"\b[Oo]pen claw\b[\\/]?[^\s'\"`,)]*"), "./"),
        # Internal case codes: numeric CASE-NNN, alpha CASE-LETTERS (exclude CASE-A/B sentinels).
        (re.compile(r"\bCASE-(?!A\b|B\b)[A-Z]{2,}\b"), "CASE-A"),
        (re.compile(r"\bCASE-0\d{2}\b"), "CASE-A"),
        # Lowercase case-id forms (case011, _case015_round1_fixN_*) that bypass upper-case PATTERN.
        # `_` is a word-char so \b fails inside identifiers; use negative digit-boundaries.
        (re.compile(r"_case\d{3}_round\d+_[a-zA-Z0-9_]+"), "_case_anon"),
        (re.compile(r"(?<!\d)case0\d{2,3}(?!\d)"), "case_anon"),
    ])
    return pats


PATTERNS = _build_patterns()

EXTS = {".py", ".md", ".json", ".yaml", ".yml", ".txt", ".tex"}
# Narrowed: only skip directories that genuinely contain pattern literals or are
# git/cache scaffolding. We DO want to scan .github/*.md (e.g. copilot-instructions.md).
SKIP_DIRS = {"vendor", ".git", ".pytest_cache", "__pycache__", "tools",
             ".agent", ".codex_ipc", ".gemini_ipc"}
# File-level skip: the workflow + redaction-spec themselves contain pattern literals.
SKIP_FILES = {
    ".github/workflows/redact-check.yml",
    "docs/redaction-spec.md",
    ".redact-names.local.txt",
}


def _is_skipped_file(p: Path, root: Path) -> bool:
    try:
        rel = p.relative_to(root).as_posix()
    except ValueError:
        return False
    return rel in SKIP_FILES


def iter_files(root: Path):
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in EXTS:
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if _is_skipped_file(p, root):
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
