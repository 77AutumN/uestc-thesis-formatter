#!/usr/bin/env python3
"""
thesis_validator.py — UESTC 论文格式合规校验器

三层 Gate 架构：
  Gate 1: 结构校验 (outline.json / thesis_meta.json)
  Gate 2: CLS 数值合规 (thesis-uestc.cls vs thesis_acceptance.json)
  Gate 3: PDF 交叉验证 (复用 postflight_check + 扩展)

设计原则：
  - 「验收官不动手术」：仅校验和报告，不执行任何自动修复
  - 配置外置：所有阈值来自 thesis_acceptance.json
  - 每个 Gate 可独立运行

Usage:
    # 运行所有 Gate
    python thesis_validator.py --cls thesis-uestc.cls --meta thesis_meta.json --pdf main.pdf

    # 仅运行 Gate 2 (CLS 合规)
    python thesis_validator.py --cls thesis-uestc.cls --gate cls

    # 仅运行 Gate 1 (结构校验)
    python thesis_validator.py --meta thesis_meta.json --outline outline.json --gate structure
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class Severity(Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class CheckResult:
    name: str
    severity: Severity
    expected: str = ""
    actual: str = ""
    detail: str = ""

    @property
    def icon(self) -> str:
        return {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}[self.severity.value]

    def __str__(self) -> str:
        base = f" {self.icon} {self.name}"
        if self.expected and self.actual:
            mark = "✓" if self.severity == Severity.PASS else "✗"
            base += f" ......... {self.actual} {'==' if self.severity == Severity.PASS else '!='} {self.expected} {mark}"
        elif self.detail:
            base += f" ......... {self.detail}"
        return base


@dataclass
class GateReport:
    gate_name: str
    checks: list = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.severity == Severity.PASS)

    @property
    def warned(self) -> int:
        return sum(1 for c in self.checks if c.severity == Severity.WARN)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if c.severity == Severity.FAIL)

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def add(self, name: str, severity: Severity, **kwargs):
        self.checks.append(CheckResult(name=name, severity=severity, **kwargs))

    def summary(self) -> str:
        lines = [f"[{self.gate_name}]"]
        for c in self.checks:
            lines.append(str(c))
        return "\n".join(lines)


# ============================================================
# Gate 2: CLS Compliance (Most valuable — can run standalone)
# ============================================================

def extract_setlength(cls_content: str, var_name: str) -> Optional[str]:
    """从 CLS 内容中提取 \\setlength{\\var_name}{value}
    
    Handles multiple CLS patterns:
      1. \\setlength{\\heavyrulewidth}{1.5bp}          — standard form
      2. \\setlength\\heavyrulewidth{\\uestcheavyrulewidth} — DissertUESTC bare form
      3. Indirect resolution: if value is another macro like \\uestcheavyrulewidth,
         resolve it via \\newcommand{\\uestcheavyrulewidth}{1.5bp}
    """
    # Pattern 1: \setlength{\var}{value}
    pattern1 = rf'\\setlength\{{\\{re.escape(var_name)}\}}\{{([^}}]+)\}}'
    # Pattern 2: \setlength\var{value}  (no braces around variable)
    pattern2 = rf'\\setlength\\{re.escape(var_name)}\{{([^}}]+)\}}'
    
    match = re.search(pattern1, cls_content) or re.search(pattern2, cls_content)
    if not match:
        return None
    
    raw_value = match.group(1).strip()
    
    # If the value is an indirect macro reference (e.g. \uestcheavyrulewidth),
    # try to resolve it via \newcommand or \renewcommand
    if raw_value.startswith('\\'):
        macro_name = raw_value.lstrip('\\')
        resolve_pattern = rf'\\(?:new|renew)command\{{\\{re.escape(macro_name)}\}}\{{([^}}]+)\}}'
        # Find ALL definitions, use the last one (renewcommand overrides)
        all_defs = re.findall(resolve_pattern, cls_content)
        if all_defs:
            raw_value = all_defs[0].strip()  # Use first (newcommand) definition as base
    
    return raw_value


def extract_captionsetup(cls_content: str, caption_type: str, param: str) -> Optional[str]:
    """从 CLS 内容中提取 \\captionsetup[type]{...param=value...}"""
    # Match captionsetup[figure]{...} or captionsetup[table]{...}
    pattern = rf'\\captionsetup\[{re.escape(caption_type)}\]\{{([^}}]+)\}}'
    match = re.search(pattern, cls_content)
    if not match:
        return None
    setup_str = match.group(1)
    # Extract specific param value from "aboveskip=6pt, belowskip=12pt"
    param_pattern = rf'{re.escape(param)}\s*=\s*([^,\s}}]+)'
    param_match = re.search(param_pattern, setup_str)
    return param_match.group(1).strip() if param_match else None


def validate_cls(cls_path: str, acceptance: dict) -> GateReport:
    """Gate 2: 从 CLS 文件提取关键数值，与 thesis_acceptance.json 对比"""
    report = GateReport("GATE 2: CLS COMPLIANCE")

    if not os.path.exists(cls_path):
        report.add("CLS file exists", Severity.FAIL, detail=f"File not found: {cls_path}")
        return report

    with open(cls_path, 'r', encoding='utf-8', errors='ignore') as f:
        cls_content = f.read()

    cls_rules = acceptance.get("cls_values", {})

    # Direct \setlength extractions
    setlength_vars = [
        "heavyrulewidth", "lightrulewidth", "cmidrulewidth",
        "abovedisplayskip", "belowdisplayskip",
        "abovedisplayshortskip", "belowdisplayshortskip",
    ]

    for var in setlength_vars:
        if var not in cls_rules:
            continue
        expected = cls_rules[var]["expected"]
        actual = extract_setlength(cls_content, var)
        if actual is None:
            report.add(var, Severity.WARN, expected=expected, detail=f"Not found in CLS")
        elif actual == expected:
            report.add(var, Severity.PASS, expected=expected, actual=actual)
        else:
            report.add(var, Severity.FAIL, expected=expected, actual=actual)

    # Caption setup extractions
    caption_mappings = {
        "figure_aboveskip": ("figure", "aboveskip"),
        "figure_belowskip": ("figure", "belowskip"),
        "table_aboveskip": ("table", "aboveskip"),
        "table_belowskip": ("table", "belowskip"),
    }

    for key, (cap_type, param) in caption_mappings.items():
        if key not in cls_rules:
            continue
        expected = cls_rules[key]["expected"]
        actual = extract_captionsetup(cls_content, cap_type, param)
        if actual is None:
            report.add(key, Severity.WARN, expected=expected, detail=f"Not found in CLS")
        elif actual == expected:
            report.add(key, Severity.PASS, expected=expected, actual=actual)
        else:
            report.add(key, Severity.FAIL, expected=expected, actual=actual)

    return report


# ============================================================
# Gate 1: Structure Validation
# ============================================================

def validate_structure(
    meta_path: str = None,
    outline_path: str = None,
    acceptance: dict = None,
    degree: str = "master"
) -> GateReport:
    """Gate 1: 检查论文结构完整性"""
    report = GateReport("GATE 1: STRUCTURE")
    struct_rules = acceptance.get("structure", {}) if acceptance else {}

    # --- Check outline.json ---
    if outline_path and os.path.exists(outline_path):
        with open(outline_path, 'r', encoding='utf-8') as f:
            outline = json.load(f)

        chapters = outline if isinstance(outline, list) else outline.get("chapters", [])
        chapter_count = len(chapters)

        if chapter_count >= 3:
            report.add("Chapter count", Severity.PASS, detail=f"{chapter_count} chapters detected")
        elif chapter_count > 0:
            report.add("Chapter count", Severity.WARN, detail=f"Only {chapter_count} chapters (expected ≥3)")
        else:
            report.add("Chapter count", Severity.FAIL, detail="No chapters detected")

        # Check heading levels
        max_levels = struct_rules.get("max_heading_levels", 4)
        deep_sections = []
        for ch in chapters:
            if isinstance(ch, dict):
                title = ch.get("title", "")
                # Count dots in section numbers like "1.2.3.4.5"
                num_match = re.match(r'^([\d.]+)', title)
                if num_match:
                    level = num_match.group(1).count('.') + 1
                    if level > max_levels:
                        deep_sections.append(title[:30])
        if deep_sections:
            report.add("Heading depth", Severity.FAIL,
                        detail=f"Found {len(deep_sections)} sections exceeding {max_levels} levels")
        else:
            report.add("Heading depth", Severity.PASS, detail=f"All sections ≤ {max_levels} levels")
    elif outline_path:
        report.add("Outline file", Severity.WARN, detail=f"File not found: {outline_path}")

    # --- Check thesis_meta.json ---
    if meta_path and os.path.exists(meta_path):
        with open(meta_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)

        # Abstract word count
        abstract_words = meta.get("abstract_word_count", meta.get("abstract_zh_length", 0))
        if abstract_words > 0:
            max_words = struct_rules.get(
                f"abstract_max_words_{degree}",
                struct_rules.get("abstract_max_words_master", 800)
            )
            if abstract_words <= max_words:
                report.add("Abstract length", Severity.PASS,
                            detail=f"{abstract_words} words (limit: {max_words})")
            else:
                report.add("Abstract length", Severity.WARN,
                            detail=f"{abstract_words} words exceeds {max_words} limit")

        # Keyword count
        keywords = meta.get("keywords_zh", [])
        if isinstance(keywords, str):
            sep = struct_rules.get("keyword_separator", "；")
            keywords = [k.strip() for k in keywords.split(sep) if k.strip()]
        kw_min = struct_rules.get("keywords_count_min", 3)
        kw_max = struct_rules.get("keywords_count_max", 5)
        kw_count = len(keywords)
        if kw_min <= kw_count <= kw_max:
            report.add("Keywords count", Severity.PASS, detail=f"{kw_count} keywords")
        elif kw_count > 0:
            report.add("Keywords count", Severity.WARN,
                        detail=f"{kw_count} keywords (expected {kw_min}-{kw_max})")
        else:
            report.add("Keywords count", Severity.WARN, detail="No keywords detected in meta")

        # Title length
        title = meta.get("title_zh", meta.get("title", ""))
        title_max = struct_rules.get("title_max_chars", 25)
        if title:
            title_len = len(title)
            if title_len <= title_max:
                report.add("Title length", Severity.PASS,
                            detail=f"{title_len} chars (limit: {title_max})")
            else:
                report.add("Title length", Severity.WARN,
                            detail=f"{title_len} chars (soft limit: {title_max})")

        # Citation markers
        cite_count = meta.get("citation_markers_in_body", -1)
        if cite_count == 0:
            report.add("Citation markers", Severity.WARN,
                        detail="No citation markers found in body text")
        elif cite_count > 0:
            report.add("Citation markers", Severity.PASS,
                        detail=f"{cite_count} citation markers found")

    elif meta_path:
        report.add("Meta file", Severity.WARN, detail=f"File not found: {meta_path}")

    return report


# ============================================================
# Gate 3: PDF Cross-Validation (extends postflight_check)
# ============================================================

def validate_pdf(pdf_path: str, acceptance: dict = None, reference_pdf: str = None) -> GateReport:
    """Gate 3: PDF 交叉验证，复用 postflight_check 并扩展"""
    report = GateReport("GATE 3: PDF VALIDATION")

    if not pdf_path or not os.path.exists(pdf_path):
        report.add("PDF file exists", Severity.FAIL, detail=f"File not found: {pdf_path}")
        return report

    # Try to import and run postflight_check
    try:
        script_dir = Path(__file__).parent
        sys.path.insert(0, str(script_dir))
        from postflight_check import run_postflight

        pf_report = run_postflight(pdf_path, reference_pdf)
        # Map postflight results into our gate report
        for check in pf_report.checks:
            severity = Severity.PASS if check["status"] == "PASS" else (
                Severity.WARN if check["status"] == "WARN" else Severity.FAIL
            )
            report.add(check["name"], severity, detail=check.get("detail", ""))
    except ImportError:
        report.add("postflight_check import", Severity.WARN,
                    detail="Could not import postflight_check.py, running standalone checks")
        _standalone_pdf_checks(pdf_path, acceptance, report)
    except Exception as e:
        report.add("postflight_check execution", Severity.WARN,
                    detail=f"postflight_check failed: {e}")
        _standalone_pdf_checks(pdf_path, acceptance, report)

    # === Additional checks NOT in postflight_check ===
    try:
        import fitz
        doc = fitz.open(pdf_path)

        # Blank page detection (UESTC §3.4: 电子版不得有空白页)
        blank_pages = []
        for pg_idx in range(len(doc)):
            page = doc[pg_idx]
            text = page.get_text().strip()
            # A page with ≤ 5 chars and no images is likely blank
            images = page.get_images()
            if len(text) <= 5 and len(images) == 0:
                blank_pages.append(pg_idx + 1)

        if blank_pages:
            report.add("No blank pages (§3.4)", Severity.FAIL,
                        detail=f"Blank pages detected: {blank_pages[:5]}")
        else:
            report.add("No blank pages (§3.4)", Severity.PASS,
                        detail="0 blank pages")

        # Extended cover metadata check — check for default author strings
        pdf_rules = acceptance.get("pdf_checks", {}) if acceptance else {}
        default_authors = pdf_rules.get("default_author_strings", ["作者", "作者姓名"])
        p1_text = doc[0].get_text() if len(doc) > 0 else ""
        has_default_author = any(da == p1_text.strip() or f"\n{da}\n" in p1_text for da in default_authors)
        if has_default_author:
            report.add("Cover author non-default", Severity.FAIL,
                        detail="Cover page contains default author placeholder")
        else:
            report.add("Cover author non-default", Severity.PASS,
                        detail="Author field appears customized")

        doc.close()
    except ImportError:
        report.add("PyMuPDF available", Severity.WARN,
                    detail="pip install pymupdf for PDF validation")
    except Exception as e:
        report.add("PDF analysis", Severity.WARN, detail=f"Error: {e}")

    return report


def _standalone_pdf_checks(pdf_path: str, acceptance: dict, report: GateReport):
    """Fallback PDF checks when postflight_check is unavailable"""
    try:
        import fitz
        doc = fitz.open(pdf_path)
        report.add("PDF readable", Severity.PASS, detail=f"{len(doc)} pages")
        doc.close()
    except Exception as e:
        report.add("PDF readable", Severity.FAIL, detail=str(e))


# ============================================================
# Main Orchestrator
# ============================================================

def load_acceptance(acceptance_path: str = None) -> dict:
    """Load thesis_acceptance.json"""
    if acceptance_path is None:
        # Default: look in skill root directory
        acceptance_path = str(Path(__file__).parent.parent / "thesis_acceptance.json")

    if not os.path.exists(acceptance_path):
        print(f"⚠️  Acceptance config not found: {acceptance_path}")
        print("   Running with empty config (no thresholds).")
        return {}

    with open(acceptance_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def run_all_gates(
    cls_path: str = None,
    meta_path: str = None,
    outline_path: str = None,
    pdf_path: str = None,
    reference_pdf: str = None,
    acceptance_path: str = None,
    gate_filter: str = None,
    degree: str = "master",
) -> list[GateReport]:
    """Run all (or filtered) gates and return reports"""
    acceptance = load_acceptance(acceptance_path)
    reports = []

    if gate_filter is None or gate_filter == "structure":
        if meta_path or outline_path:
            reports.append(validate_structure(meta_path, outline_path, acceptance, degree))

    if gate_filter is None or gate_filter == "cls":
        if cls_path:
            reports.append(validate_cls(cls_path, acceptance))

    if gate_filter is None or gate_filter == "pdf":
        if pdf_path:
            reports.append(validate_pdf(pdf_path, acceptance, reference_pdf))

    return reports


def print_reports(reports: list[GateReport]):
    """Print formatted validator report"""
    total_pass = sum(r.passed for r in reports)
    total_warn = sum(r.warned for r in reports)
    total_fail = sum(r.failed for r in reports)
    total = total_pass + total_warn + total_fail
    all_ok = all(r.ok for r in reports)

    print(f"\n{'='*60}")
    print(f"  🔍 VALIDATOR REPORT (thesis_validator v1.0)")
    print(f"{'='*60}")

    for report in reports:
        print(report.summary())
        print()

    verdict = "🟢 ALL GATES PASS" if all_ok else "🔴 GATE FAILURE"
    print(f"VERDICT: {verdict} ({total_pass}/{total} ✅", end="")
    if total_warn > 0:
        print(f", {total_warn} ⚠️", end="")
    if total_fail > 0:
        print(f", {total_fail} ❌", end="")
    print(")")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description='UESTC 论文格式合规校验器 (3-Gate Architecture)')
    parser.add_argument('--cls', help='CLS 文件路径 (Gate 2)')
    parser.add_argument('--meta', help='thesis_meta.json 路径 (Gate 1)')
    parser.add_argument('--outline', help='outline.json 路径 (Gate 1)')
    parser.add_argument('--pdf', help='编译后的 PDF 路径 (Gate 3)')
    parser.add_argument('--reference', help='参考 PDF 路径 (Gate 3 可选)')
    parser.add_argument('--acceptance', help='thesis_acceptance.json 路径')
    parser.add_argument('--gate', choices=['structure', 'cls', 'pdf'],
                        help='仅运行指定 Gate')
    parser.add_argument('--degree', default='master',
                        choices=['bachelor', 'master', 'doctor'],
                        help='学位类型 (影响摘要字数限制)')
    parser.add_argument('--output', help='输出 JSON 报告路径')
    args = parser.parse_args()

    reports = run_all_gates(
        cls_path=args.cls,
        meta_path=args.meta,
        outline_path=args.outline,
        pdf_path=args.pdf,
        reference_pdf=args.reference,
        acceptance_path=args.acceptance,
        gate_filter=args.gate,
        degree=args.degree,
    )

    if not reports:
        print("⚠️  No gates executed. Provide --cls, --meta, or --pdf to run validations.")
        sys.exit(1)

    print_reports(reports)

    if args.output:
        output_data = {
            "gates": [
                {
                    "name": r.gate_name,
                    "passed": r.passed,
                    "warned": r.warned,
                    "failed": r.failed,
                    "ok": r.ok,
                    "checks": [
                        {"name": c.name, "severity": c.severity.value,
                         "expected": c.expected, "actual": c.actual, "detail": c.detail}
                        for c in r.checks
                    ]
                }
                for r in reports
            ]
        }
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        print(f"  报告已保存: {args.output}")

    all_ok = all(r.ok for r in reports)
    sys.exit(0 if all_ok else 1)


if __name__ == '__main__':
    main()
