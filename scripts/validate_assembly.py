#!/usr/bin/env python3
"""
validate_assembly.py — Pre-compilation assembly validation gate

在 LaTeX 组装完成、编译之前执行五项 P0 级检查。
任何一项失败 → 阻断编译（除非传入 --force）。

五项检查:
  1. Unicode 引号: 检测 LaTeX backtick quote ligature 在中文上下文中
  2. 文本保真: 对比 extracted/ 源文件 vs .tex 文件（strip LaTeX 后）
  3. 参考文献分类: bibliography_categorized.tex 不得含"其他"分类
  4. Caption-footnote 安全: \\caption{...\\footnote{...}} 必须使用保护语法
  5. 英文摘要无中文污染: 英文摘要 .tex 不含连续中文字符

Usage:
    python validate_assembly.py <project_dir> [--force] [--verbose]
    
Exit codes:
    0 = ALL PASS
    1 = FAIL (blocked)
    2 = PASS with warnings
"""

import argparse
import glob
import os
import re
import sys
from typing import NamedTuple

# Fix Windows GBK terminal encoding for emoji output
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


class CheckResult(NamedTuple):
    name: str
    passed: bool
    message: str
    details: list  # list of strings


# =============================================================================
# Check 1: Unicode Quotes (LaTeX backtick quotes in CJK context)
# =============================================================================

def check_unicode_quotes(project_dir: str) -> CheckResult:
    """Detect LaTeX-style backtick/tick quotes that should be Unicode CJK quotes."""
    name = "Unicode 引号检查"
    chapter_dir = os.path.join(project_dir, "chapter")
    misc_dir = os.path.join(project_dir, "misc")
    
    tex_files = []
    if os.path.isdir(chapter_dir):
        tex_files += glob.glob(os.path.join(chapter_dir, "*.tex"))
    if os.path.isdir(misc_dir):
        tex_files += glob.glob(os.path.join(misc_dir, "*.tex"))
    
    if not tex_files:
        return CheckResult(name, True, "无 .tex 文件可检查", [])
    
    # Pattern: backtick open quote `` or single ` followed by CJK, or '' after CJK
    # LaTeX quote ligatures: `` → " (open), '' → " (close)
    backtick_pattern = re.compile(r"``[^\n]{0,50}''")
    
    violations = []
    for tf in tex_files:
        with open(tf, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                # Skip comments
                if line.strip().startswith("%"):
                    continue
                matches = backtick_pattern.findall(line)
                if matches:
                    fname = os.path.basename(tf)
                    for m in matches:
                        # Check if content between quotes contains CJK
                        if re.search(r"[\u4e00-\u9fff]", m):
                            violations.append(f"  {fname}:{i}: {m[:80]}")
    
    if violations:
        return CheckResult(
            name, False,
            f"发现 {len(violations)} 处 LaTeX 引号包含中文内容（应使用 Unicode 全角引号）",
            violations[:20]  # cap output
        )
    return CheckResult(name, True, "未检测到 backtick 引号包含中文", [])


# =============================================================================
# Check 2: Text Integrity (extracted/ vs .tex diff)
# =============================================================================

def _strip_latex_commands(text: str) -> str:
    """Remove LaTeX commands to get pure text for comparison."""
    # Remove \command{...} but keep content inside braces
    text = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", text)
    # Remove \command without braces
    text = re.sub(r"\\[a-zA-Z]+", "", text)
    # Remove remaining braces
    text = text.replace("{", "").replace("}", "")
    # Remove comments
    text = re.sub(r"%.*$", "", text, flags=re.MULTILINE)
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def check_text_integrity(project_dir: str) -> CheckResult:
    """Compare extracted source files vs generated .tex files."""
    name = "文本保真检查"
    extracted_dir = os.path.join(project_dir, "extracted")
    
    if not os.path.isdir(extracted_dir):
        return CheckResult(name, True, "无 extracted/ 目录，跳过保真校验", [])
    
    # Map extracted files to their .tex counterparts
    mappings = [
        ("abstract_zh.txt", os.path.join("misc", "chinese_abstract.tex")),
        ("abstract_en.txt", os.path.join("misc", "english_abstract.tex")),
        ("acknowledgement.txt", os.path.join("misc", "acknowledgement.tex")),
    ]
    
    warnings = []
    for src_name, tex_rel in mappings:
        src_path = os.path.join(extracted_dir, src_name)
        tex_path = os.path.join(project_dir, tex_rel)
        
        if not os.path.exists(src_path) or not os.path.exists(tex_path):
            continue
        
        with open(src_path, "r", encoding="utf-8") as f:
            src_text = _strip_latex_commands(f.read())
        with open(tex_path, "r", encoding="utf-8") as f:
            tex_text = _strip_latex_commands(f.read())
        
        # Simple length-based divergence check
        if len(src_text) == 0:
            continue
        
        len_ratio = len(tex_text) / len(src_text)
        if len_ratio > 1.15 or len_ratio < 0.85:
            warnings.append(
                f"  {src_name} vs {tex_rel}: 长度比 {len_ratio:.2f} "
                f"(src={len(src_text)}, tex={len(tex_text)}) — 可能存在内容篡改"
            )
    
    if warnings:
        return CheckResult(
            name, False,
            f"发现 {len(warnings)} 处文本保真偏差（超过 ±15%）",
            warnings
        )
    return CheckResult(name, True, "文本保真检查通过", [])


# =============================================================================
# Check 3: Bibliography categorization (no "其他" category)
# =============================================================================

def check_bibliography_categories(project_dir: str) -> CheckResult:
    """Verify categorized bibliography has no '其他' catch-all category."""
    name = "参考文献分类检查"
    bib_path = os.path.join(project_dir, "bibliography_categorized.tex")
    
    if not os.path.exists(bib_path):
        return CheckResult(name, True, "无分类参考文献文件，跳过", [])
    
    with open(bib_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    violations = []
    
    # Check for "其他" category
    if re.search(r"其他", content):
        violations.append("  发现「其他」分类 — 马院标准不允许此分类，请手动归入正确类别")
    
    # Check for empty enumerate environments
    empty_enum = re.findall(r"\\begin\{enumerate\}.*?\\end\{enumerate\}", content, re.DOTALL)
    for i, enum in enumerate(empty_enum):
        if "\\item" not in enum:
            violations.append(f"  第 {i+1} 个 enumerate 环境为空")
    
    if violations:
        return CheckResult(name, False, f"参考文献分类存在 {len(violations)} 个问题", violations)
    return CheckResult(name, True, "参考文献分类检查通过", [])


# =============================================================================
# Check 4: Caption-footnote safety
# =============================================================================

def check_caption_footnote(project_dir: str) -> CheckResult:
    """Detect \\caption{...\\footnote{...}} without protective \\caption[short]{long} syntax."""
    name = "Caption-Footnote 安全检查"
    chapter_dir = os.path.join(project_dir, "chapter")
    
    if not os.path.isdir(chapter_dir):
        return CheckResult(name, True, "无 chapter/ 目录", [])
    
    tex_files = glob.glob(os.path.join(chapter_dir, "*.tex"))
    violations = []
    
    # Unsafe pattern: \caption{...text...\footnote{...}...} WITHOUT \caption[...]{...}
    # Safe pattern: \caption[short]{long\footnote{...}}
    for tf in tex_files:
        with open(tf, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Find all \caption{...} that contain \footnote
        # Unsafe: \caption{text\footnote{...}}
        # Safe: \caption[text]{text\footnote{...}}
        for m in re.finditer(r"\\caption\{([^}]*\\footnote)", content):
            # Check if preceded by \caption[
            start = m.start()
            prefix = content[max(0, start-2):start+8]
            if "\\caption[" not in content[max(0, start-10):start+9]:
                line_num = content[:start].count("\n") + 1
                fname = os.path.basename(tf)
                violations.append(
                    f"  {fname}:{line_num}: \\caption{{...\\footnote{{...}}}} 缺少 [短标题] 保护"
                )
    
    if violations:
        return CheckResult(
            name, False,
            f"发现 {len(violations)} 处不安全的 caption-footnote 嵌套",
            violations
        )
    return CheckResult(name, True, "Caption-Footnote 安全检查通过", [])


# =============================================================================
# Check 5: English abstract CJK pollution
# =============================================================================

def check_en_abstract_pollution(project_dir: str) -> CheckResult:
    """Detect CJK characters in English abstract .tex files."""
    name = "英文摘要中文污染检查"
    
    candidates = [
        os.path.join(project_dir, "misc", "english_abstract.tex"),
        os.path.join(project_dir, "misc", "abstract_en.tex"),
    ]
    
    target = None
    for c in candidates:
        if os.path.exists(c):
            target = c
            break
    
    if target is None:
        return CheckResult(name, True, "未找到英文摘要文件，跳过", [])
    
    with open(target, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    violations = []
    # Pattern: 3+ consecutive CJK characters (excludes single chars in \enkeywords{})
    cjk_run = re.compile(r"[\u4e00-\u9fff]{3,}")
    
    for i, line in enumerate(lines, 1):
        # Skip LaTeX commands that legitimately contain CJK (e.g., \enkeywords)
        stripped = re.sub(r"\\[a-zA-Z]+\{[^}]*\}", "", line)
        # Also skip comment lines
        if stripped.strip().startswith("%"):
            continue
        matches = cjk_run.findall(stripped)
        if matches:
            for m in matches:
                violations.append(f"  L{i}: \"{m}\"")
    
    if violations:
        return CheckResult(
            name, False,
            f"英文摘要中检测到 {len(violations)} 处中文文本污染",
            violations[:10]
        )
    return CheckResult(name, True, "英文摘要无中文污染", [])


# =============================================================================
# Main
# =============================================================================

ALL_CHECKS = [
    check_unicode_quotes,
    check_text_integrity,
    check_bibliography_categories,
    check_caption_footnote,
    check_en_abstract_pollution,
]


def run_all_checks(project_dir: str, verbose: bool = False) -> list:
    """Run all validation checks and return results."""
    results = []
    for check_fn in ALL_CHECKS:
        result = check_fn(project_dir)
        results.append(result)
    return results


def print_report(results: list, verbose: bool = False):
    """Print formatted validation report."""
    print("\n" + "=" * 60)
    print("validate_assembly.py — Pre-compilation Assembly Validation")
    print("=" * 60)
    
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    
    for r in results:
        icon = "✅" if r.passed else "❌"
        print(f"\n{icon} [{r.name}] {r.message}")
        if not r.passed or verbose:
            for detail in r.details:
                print(detail)
    
    print("\n" + "-" * 60)
    print(f"结果: {passed}/{len(results)} 通过, {failed} 失败")
    
    if failed > 0:
        print("⛔ VALIDATION FAILED — 编译已阻断")
        print("   使用 --force 跳过校验（不推荐）")
    else:
        print("✅ VALIDATION PASSED — 可以继续编译")
    
    print("=" * 60)
    return failed == 0


def main():
    parser = argparse.ArgumentParser(
        description="Pre-compilation assembly validation gate (5 P0 checks)"
    )
    parser.add_argument("project_dir", help="LaTeX project directory (contains chapter/, misc/, etc.)")
    parser.add_argument("--force", action="store_true", help="Continue even if checks fail")
    parser.add_argument("--verbose", action="store_true", help="Show details for passed checks too")
    args = parser.parse_args()
    
    if not os.path.isdir(args.project_dir):
        print(f"❌ 目录不存在: {args.project_dir}")
        sys.exit(1)
    
    results = run_all_checks(args.project_dir, args.verbose)
    all_passed = print_report(results, args.verbose)
    
    if not all_passed and not args.force:
        sys.exit(1)
    elif not all_passed and args.force:
        print("\n⚠️ --force 模式: 跳过校验失败，继续执行")
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
