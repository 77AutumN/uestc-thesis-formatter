#!/usr/bin/env python3
"""
postflight_check.py — PDF 输出质量校验模块

在 pipeline 编译完成后，校验生成的 PDF 是否满足 UESTC 论文格式要求。
借鉴 webapp-testing 的 Visual Regression 模式，对 PDF 进行结构化检查。

Usage:
    python postflight_check.py --pdf main.pdf [--reference ref.pdf] [--output report.json]
"""

import argparse
import json
import os
import re
import sys


class PostflightReport:
    """后检报告收集器"""

    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.checks = []
        self.passed = 0
        self.failed = 0
        self.warnings = 0

    def check(self, name: str, passed: bool, detail: str = "", severity: str = "ERROR"):
        status = "PASS" if passed else severity
        self.checks.append({"name": name, "status": status, "detail": detail})
        if passed:
            self.passed += 1
        elif severity == "ERROR":
            self.failed += 1
        else:
            self.warnings += 1

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def summary(self) -> str:
        lines = [
            f"\n{'='*60}",
            f"  📋 Post-flight 检查报告",
            f"{'='*60}",
            f"  文件: {os.path.basename(self.pdf_path)}",
            f"  结果: {'✅ 全部通过' if self.ok else '❌ 存在问题'}",
            f"  通过: {self.passed}  失败: {self.failed}  警告: {self.warnings}",
            f"{'='*60}",
        ]
        for c in self.checks:
            icon = "✅" if c["status"] == "PASS" else ("❌" if c["status"] == "ERROR" else "⚠️")
            lines.append(f"  {icon} {c['name']}")
            if c["detail"]:
                lines.append(f"     → {c['detail']}")
        lines.append(f"{'='*60}\n")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "pdf_path": self.pdf_path,
            "passed": self.passed,
            "failed": self.failed,
            "warnings": self.warnings,
            "ok": self.ok,
            "checks": self.checks
        }


def run_postflight(pdf_path: str, reference_pdf: str = None) -> PostflightReport:
    """执行所有后检项"""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("❌ 缺少 PyMuPDF 库 (pip install pymupdf)")
        sys.exit(1)

    report = PostflightReport(pdf_path)

    # === Check 0: 文件存在 ===
    if not os.path.exists(pdf_path):
        report.check("PDF 文件存在", False, f"文件不存在: {pdf_path}")
        return report
    report.check("PDF 文件存在", True)

    # === Check 1: 打开 PDF ===
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        report.check("PDF 可解析", False, f"PyMuPDF 无法打开: {e}")
        return report
    report.check("PDF 可解析", True)

    total_pages = len(doc)

    # === Check 2: 页数合理性 ===
    if total_pages < 30:
        report.check("页数合理", False, f"仅 {total_pages} 页，硕士论文通常 >50 页")
    elif total_pages > 300:
        report.check("页数合理", False, f"{total_pages} 页，可能包含错误", "WARN")
    else:
        report.check("页数合理", True, f"共 {total_pages} 页")

    # === Check 3: 封面标题非默认值 ===
    p1_text = doc[0].get_text().strip()
    default_titles = ["论文标题", "Thesis Title", "请输入论文题目"]
    has_default_title = any(dt in p1_text for dt in default_titles)
    if has_default_title:
        report.check("封面标题", False, "封面包含模板默认标题，元数据未正确注入")
    elif "电子科技大学" in p1_text:
        report.check("封面标题", True, "封面包含校名，非模板默认值")
    else:
        report.check("封面标题", False, "封面未包含「电子科技大学」", "WARN")

    # === Check 4: 目录页存在 ===
    toc_found = False
    for pg in range(min(15, total_pages)):
        text = doc[pg].get_text()
        if "目" in text and "录" in text and ("第" in text and "章" in text):
            toc_found = True
            break
    report.check("目录页存在", toc_found,
                  "" if toc_found else "前 15 页未找到含有「目录」+「第X章」的页面")

    # === Check 5: 章节编号层级检查（不超过 4 级）===
    five_level_pattern = re.compile(r'\d+\.\d+\.\d+\.\d+\.\d+')
    five_level_pages = []
    for pg in range(total_pages):
        text = doc[pg].get_text()
        if five_level_pattern.search(text):
            five_level_pages.append(pg + 1)
    if five_level_pages:
        sample = five_level_pages[:5]
        report.check("章节层级 ≤4", False,
                      f"第 {sample} 页出现 5 级编号 (x.x.x.x.x)，UESTC 仅允许 4 级")
    else:
        report.check("章节层级 ≤4", True)

    # === Check 6: 参考文献页眉检查 ===
    # 从后往前找「参考文献」页面，检查该页文本是否包含"参考文献"（页眉）
    ref_page_idx = None
    for pg in range(total_pages - 1, max(total_pages - 30, 0), -1):
        text = doc[pg].get_text()
        if "参考文献" in text and ("[" in text or "【" in text):
            ref_page_idx = pg
            break
    if ref_page_idx is not None:
        ref_text = doc[ref_page_idx].get_text()
        # 页眉通常在页面文本的前几行
        first_lines = ref_text.strip().split('\n')[:3]
        first_text = ' '.join(first_lines)
        if "参考文献" in first_text:
            report.check("参考文献页眉", True, f"第 {ref_page_idx + 1} 页页眉正确")
        else:
            report.check("参考文献页眉", False,
                          f"第 {ref_page_idx + 1} 页页眉可能不是「参考文献」: {first_text[:50]}", "WARN")
    else:
        report.check("参考文献页眉", False, "未找到参考文献页面", "WARN")

    # === Check 7: 未解析引用检查 (LaTeX 残留 "??") ===
    unresolved_pages = []
    for pg in range(total_pages):
        text = doc[pg].get_text()
        if "??" in text:
            unresolved_pages.append(pg + 1)
    if unresolved_pages:
        sample = unresolved_pages[:5]
        report.check("无未解析引用", False,
                      f"第 {sample} 页存在 \"??\"（未解析的 LaTeX 引用），需增加编译遍数")
    else:
        report.check("无未解析引用", True)

    # === Check 8: 摘要页存在 ===
    abstract_found = False
    for pg in range(min(10, total_pages)):
        text = doc[pg].get_text()
        if "摘" in text and "要" in text and len(text) > 200:
            abstract_found = True
            break
    report.check("摘要页存在", abstract_found,
                  "" if abstract_found else "前 10 页未找到摘要内容")

    # === Check 9: 致谢页存在 ===
    ack_found = False
    for pg in range(max(0, total_pages - 15), total_pages):
        text = doc[pg].get_text()
        if "致" in text and "谢" in text and len(text) > 100:
            ack_found = True
            break
    report.check("致谢页存在", ack_found,
                  "" if ack_found else "最后 15 页未找到致谢内容")

    # === Check 10: 与参考 PDF 页数对比（如提供）===
    if reference_pdf and os.path.exists(reference_pdf):
        try:
            ref_doc = fitz.open(reference_pdf)
            ref_pages = len(ref_doc)
            diff = abs(total_pages - ref_pages)
            if diff > 20:
                report.check("页数偏差", False,
                              f"输出 {total_pages} 页 vs 参考 {ref_pages} 页 (差 {diff} 页)", "WARN")
            else:
                report.check("页数偏差", True,
                              f"输出 {total_pages} 页 vs 参考 {ref_pages} 页 (差 {diff} 页)")
            ref_doc.close()
        except Exception as e:
            report.check("页数偏差", False, f"无法打开参考 PDF: {e}", "WARN")

    doc.close()
    return report


def main():
    parser = argparse.ArgumentParser(description='论文 PDF 输出质量校验工具')
    parser.add_argument('--pdf', required=True, help='待检查的 PDF 文件路径')
    parser.add_argument('--reference', help='参考 PDF 文件路径（可选，用于对比）')
    parser.add_argument('--output', help='输出 JSON 报告路径')
    args = parser.parse_args()

    report = run_postflight(args.pdf, args.reference)
    print(report.summary())

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        print(f"  报告已保存: {args.output}")

    sys.exit(0 if report.ok else 1)


if __name__ == '__main__':
    main()
