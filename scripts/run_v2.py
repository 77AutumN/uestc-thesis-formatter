#!/usr/bin/env python3
"""
run_v2.py — Thesis Formatter v2 (DissertationUESTC 引擎)

Migration from thesis-uestc → DissertationUESTC.cls
Uses template_adapter.py for all LaTeX generation (no hardcoded commands).

Usage:
    python run_v2.py thesis.docx --profile uestc-marxism --output-dir ./output/
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

# 确保 scripts 目录在 Python path 中
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPTS_DIR) if os.path.basename(SCRIPTS_DIR) == "scripts" else SCRIPTS_DIR
if os.path.basename(SCRIPTS_DIR) != "scripts":
    SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")

sys.path.insert(0, SCRIPTS_DIR)
from profile_loader import load_profile, get_compile_chain, get_bibliography_mode, get_citation_style
from template_adapter import assemble_main_tex, load_metadata, FORBIDDEN_LEGACY_TOKENS

# Vendor directory for DissertationUESTC template files
VENDOR_DIR = os.path.join(SKILL_DIR, "vendor", "DissertationUESTC")


class ThesisFormatterV2:
    """端到端论文排版编排器 — v2 (DissertationUESTC)"""

    def __init__(self, docx_path: str, profile_name: str, output_dir: str,
                 template_dir: str = None, auto: bool = False):
        self.docx_path = os.path.abspath(docx_path)
        self.profile_name = profile_name
        self.output_dir = os.path.abspath(output_dir)
        self.auto = auto
        self.extracted_dir = os.path.join(self.output_dir, "extracted")

        # 加载 profile
        self.config = load_profile(profile_name)
        self.compile_chain = get_compile_chain(self.config)
        self.bib_mode = get_bibliography_mode(self.config)
        self.cite_style = get_citation_style(self.config)

        # Template working directory — NO LONGER hardcoded to "thesis-uestc"
        if template_dir:
            self.template_dir = os.path.abspath(template_dir)
        else:
            self.template_dir = os.path.join(self.output_dir, "DissertationUESTC")

        self.report = {
            "profile": profile_name,
            "engine": "DissertationUESTC",
            "steps": [],
            "errors": [],
            "warnings": [],
        }

    # =========================================================================
    # Logging helpers (unchanged from v1)
    # =========================================================================

    def log(self, msg: str, level: str = "INFO"):
        icons = {"INFO": "📌", "OK": "✅", "WARN": "⚠️", "ERROR": "❌", "STEP": "🔄"}
        icon = icons.get(level, "")
        print(f"  {icon} {msg}")

    def log_step(self, step_num, title: str):
        print(f"\n{'='*60}")
        print(f"  Step {step_num}: {title}")
        print(f"{'='*60}")

    def run_script(self, script_name: str, args: list, description: str) -> bool:
        script_path = os.path.join(SCRIPTS_DIR, script_name)
        if not os.path.exists(script_path):
            self.log(f"脚本不存在: {script_path}", "ERROR")
            self.report["errors"].append(f"Missing script: {script_name}")
            return False

        cmd = [sys.executable, script_path] + args
        self.log(f"运行: {script_name} {' '.join(args)}")

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
            )
            if result.stdout:
                for line in result.stdout.strip().split("\n"):
                    print(f"    {line}")
            if result.returncode != 0:
                self.log(f"{description} 失败 (exit code: {result.returncode})", "ERROR")
                if result.stderr:
                    for line in result.stderr.strip().split("\n")[:5]:
                        self.log(f"  STDERR: {line}", "WARN")
                self.report["errors"].append(f"{script_name} failed")
                return False
            self.log(f"{description} 完成", "OK")
            self.report["steps"].append({"script": script_name, "status": "success"})
            return True
        except Exception as e:
            self.log(f"运行 {script_name} 异常: {e}", "ERROR")
            self.report["errors"].append(f"{script_name} exception: {str(e)}")
            return False

    # =========================================================================
    # Step 0: Pre-flight (unchanged)
    # =========================================================================

    def step0_preflight(self) -> bool:
        self.log_step(0, "Pre-flight 输入检查")
        try:
            from preflight_check import run_preflight
            report = run_preflight(self.docx_path, self.profile_name)
            print(report.summary())
            preflight_path = os.path.join(self.output_dir, 'preflight_report.json')
            os.makedirs(self.output_dir, exist_ok=True)
            with open(preflight_path, 'w', encoding='utf-8') as f:
                json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
            self.report['steps'].append({'script': 'preflight_check', 'status': 'success' if report.ok else 'failed'})
            if not report.ok:
                self.log(f"Pre-flight 检查未通过 ({report.failed} 个阻塞项)", "ERROR")
                return False
            self.log(f"Pre-flight 通过 ({report.passed}/{report.passed + report.warnings} 项)", "OK")
            return True
        except ImportError:
            self.log("preflight_check.py 不可用，跳过预检", "WARN")
            return True
        except Exception as e:
            self.log(f"Pre-flight 异常: {e}", "WARN")
            return True

    # =========================================================================
    # Step 1: Extract (unchanged)
    # =========================================================================

    def step1_extract(self) -> bool:
        self.log_step(1, "提取 Word 文档内容 [AST Engine]")
        if not os.path.exists(self.docx_path):
            self.log(f"文件不存在: {self.docx_path}", "ERROR")
            return False
        os.makedirs(self.extracted_dir, exist_ok=True)
        return self.run_script(
            "pandoc_ast_extract.py",
            ["--input", self.docx_path, "--output-dir", self.extracted_dir],
            "文档提取 (AST)"
        )

    # =========================================================================
    # Step 2: Confirm outline (unchanged)
    # =========================================================================

    def step2_confirm_outline(self) -> bool:
        self.log_step(2, "确认章节结构")
        outline_path = os.path.join(self.extracted_dir, "outline.json")
        if not os.path.exists(outline_path):
            self.log("outline.json 未生成", "ERROR")
            return False
        with open(outline_path, "r", encoding="utf-8") as f:
            outline = json.load(f)
        print("\n  📋 章节结构:")
        for ch in outline.get("chapters", []):
            print(f"    {ch['filename']}: {ch['title']}")
        print(f"\n  特殊部分: {list(outline.get('special_sections', {}).keys())}")
        if not self.auto:
            confirm = input("\n  结构是否正确? (Y/n): ").strip().lower()
            if confirm == "n":
                self.log("用户取消", "WARN")
                return False
        self.log("结构已确认", "OK")
        return True

    # =========================================================================
    # Step 2.5: Hooks (unchanged)
    # =========================================================================

    def step_run_hooks(self) -> bool:
        self.log_step(2.5, "运行提取后置钩子 (Hooks)")
        self.run_script("hooks/extract_hidden_sections.py",
                        [self.extracted_dir, self.template_dir], "隐藏章节提取 (结语/成果页)")
        self.run_script("hooks/format_abstract.py",
                        [self.extracted_dir, self.template_dir], "摘要格式化")
        self.run_script("hooks/format_punctuation.py",
                        [self.template_dir], "标点符号规范化")
        return True

    # =========================================================================
    # Step 3: Generate BibTeX (unchanged)
    # =========================================================================

    def step3_generate_bib(self) -> bool:
        self.log_step(3, "生成 BibTeX 参考文献")
        raw_path = os.path.join(self.extracted_dir, "references_raw.txt")
        if not os.path.exists(raw_path):
            self.log("references_raw.txt 未找到，跳过参考文献处理", "WARN")
            self.report["warnings"].append("No references_raw.txt found")
            return True
        bib_path = os.path.join(self.template_dir, "ref.bib")
        return self.run_script(
            "refs_to_bib.py",
            ["--input", raw_path, "--output", bib_path],
            "BibTeX 生成"
        )

    # =========================================================================
    # Step 3.5: Assemble — COMPLETELY REWRITTEN for DissertationUESTC
    # =========================================================================

    def step3_5_assemble(self) -> bool:
        """Step 3.5: 组装 LaTeX 模板与章节 (DissertUESTC adapter)"""
        self.log_step(3.5, "组装 LaTeX 模板与章节 [DissertUESTC]")

        # --- 1. Copy vendored template to working directory ---
        if os.path.exists(VENDOR_DIR) and VENDOR_DIR != self.template_dir:
            self.log(f"复制 Vendor 模板到 {self.template_dir}")
            try:
                shutil.copytree(
                    VENDOR_DIR, self.template_dir,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('.git', '__pycache__'),
                )
            except Exception as e:
                self.log(f"复制模板失败: {e}", "ERROR")
                return False

        # --- 2. Copy extracted chapters to template/chapter/ ---
        src_chap_dir = os.path.join(self.extracted_dir, "chapters")
        dst_chap_dir = os.path.join(self.template_dir, "chapter")
        os.makedirs(dst_chap_dir, exist_ok=True)

        ch_files = sorted(glob.glob(os.path.join(src_chap_dir, "ch*.tex")))
        if ch_files:
            for f in ch_files:
                shutil.copy(f, dst_chap_dir)
            self.log(f"复制了 {len(ch_files)} 个章节文件", "OK")

        # --- 2.5: Copy extracted images to template/media/ ---
        src_media_dir = os.path.join(self.extracted_dir, "media")
        if os.path.exists(src_media_dir):
            dst_media_dir = os.path.join(self.template_dir, "media")
            os.makedirs(dst_media_dir, exist_ok=True)
            img_count = 0
            for root, dirs, files in os.walk(src_media_dir):
                for fname in files:
                    if fname.lower().endswith(('.png', '.jpg', '.jpeg', '.pdf', '.eps', '.svg')):
                        shutil.copy(os.path.join(root, fname), dst_media_dir)
                        img_count += 1
            if img_count > 0:
                self.log(f"复制了 {img_count} 个图片到 media/", "OK")

        # --- 3. Prepare misc/ directory ---
        misc_dir = os.path.join(self.template_dir, "misc")
        os.makedirs(misc_dir, exist_ok=True)

        # 3.1 Chinese abstract → misc/chinese_abstract.tex (BODY ONLY, no wrapper)
        abstract_zh_body = ""
        abstract_zh_keywords = ""
        zh_txt = os.path.join(self.extracted_dir, "abstract_zh.txt")
        if os.path.exists(zh_txt):
            with open(zh_txt, "r", encoding="utf-8") as f:
                content = f.read().strip()
            match = re.search(r'(?:关键词|Keywords)[:：]\s*(.+)', content,
                              flags=re.IGNORECASE | re.MULTILINE)
            if match:
                abstract_zh_keywords = match.group(1).strip()
                content = content[:match.start()].strip()
            abstract_zh_body = content

        # 3.2 English abstract
        abstract_en_body = ""
        abstract_en_keywords = ""
        en_txt = os.path.join(self.extracted_dir, "abstract_en.txt")
        if os.path.exists(en_txt):
            with open(en_txt, "r", encoding="utf-8") as f:
                content = f.read().strip()
            match = re.search(r'(?:关键词|Keywords)[:：]\s*(.+)', content,
                              flags=re.IGNORECASE | re.MULTILINE)
            if match:
                abstract_en_keywords = match.group(1).strip()
                content = content[:match.start()].strip()
            abstract_en_body = content

        # 3.3 Acknowledgement → misc/acknowledgement.tex (BODY ONLY)
        ack_txt = os.path.join(self.extracted_dir, "acknowledgement.txt")
        if os.path.exists(ack_txt):
            with open(ack_txt, "r", encoding="utf-8") as f:
                ack_body = f.read().strip()
            with open(os.path.join(misc_dir, "acknowledgement.tex"), "w", encoding="utf-8") as f:
                f.write(ack_body + "\n")

        # 3.4 Accomplishments → misc/accomplishments.tex (BODY ONLY)
        # The \achievement macro in CLS handles chapter*/toc/markboth
        has_accomplishments = False
        acc_tex = os.path.join(misc_dir, "accomplishments.tex")
        if os.path.exists(acc_tex) and os.path.getsize(acc_tex) > 10:
            # Hook already generated it — strip old chapter* wrapper if present
            with open(acc_tex, "r", encoding="utf-8") as f:
                acc_content = f.read()
            # Remove legacy chapter*/addcontentsline/markboth wrappers
            acc_content = re.sub(r'\\chapter\*\{[^}]*\}\s*\n?', '', acc_content)
            acc_content = re.sub(r'\\addcontentsline\{[^}]*\}\{[^}]*\}\{[^}]*\}\s*\n?', '', acc_content)
            acc_content = re.sub(r'\\markboth\{[^}]*\}\{[^}]*\}\s*\n?', '', acc_content)
            with open(acc_tex, "w", encoding="utf-8") as f:
                f.write(acc_content.strip() + "\n")
            has_accomplishments = True
        else:
            # Check raw extracted
            acc_txt = os.path.join(self.extracted_dir, "accomplishment.txt")
            if os.path.exists(acc_txt) and os.path.getsize(acc_txt) > 10:
                with open(acc_txt, "r", encoding="utf-8") as f:
                    raw = f.read().strip()
                with open(acc_tex, "w", encoding="utf-8") as f:
                    f.write(raw + "\n")
                has_accomplishments = True

        # 3.5 Conclusion
        has_conclusion = os.path.exists(os.path.join(misc_dir, "conclusion.tex"))

        # --- 4. Load metadata and generate main.tex via adapter ---
        cover_meta_path = os.path.join(self.extracted_dir, "cover_metadata.json")
        if os.path.exists(cover_meta_path):
            meta = load_metadata(cover_meta_path)
            self.log(f"封面元数据已加载 ({len(meta)} 个字段)", "OK")
        else:
            self.log("未找到 cover_metadata.json，使用全 fallback 元数据", "WARN")
            meta = {}

        # Build chapter file list
        chapter_names = sorted([
            f"chapter/{os.path.basename(f).replace('.tex', '')}"
            for f in ch_files
        ])

        # Assemble main.tex via adapter
        main_tex_content = assemble_main_tex(
            meta=meta,
            chapter_files=chapter_names,
            abstract_zh_body=abstract_zh_body,
            abstract_zh_keywords=abstract_zh_keywords,
            abstract_en_body=abstract_en_body,
            abstract_en_keywords=abstract_en_keywords,
            has_conclusion=has_conclusion,
            has_accomplishments=has_accomplishments,
            bib_mode=self.bib_mode,
            print_mode="nonprint",
        )

        main_tex_path = os.path.join(self.template_dir, "main.tex")
        with open(main_tex_path, "w", encoding="utf-8") as f:
            f.write(main_tex_content)

        self.log("成功通过 DissertUESTC adapter 生成 main.tex", "OK")

        # --- 5. Handle overrides ---
        override_dir = os.path.join(os.path.dirname(self.docx_path), "overrides")
        if os.path.exists(override_dir):
            for f_name in os.listdir(override_dir):
                if f_name.endswith(".tex"):
                    override_path = os.path.join(override_dir, f_name)
                    with open(override_path, "r", encoding="utf-8") as ov_f:
                        ov_content = ov_f.read()
                    match = re.search(r'table_(\d+)\.tex', f_name)
                    if match:
                        table_id = match.group(1)
                        for ch_file in glob.glob(os.path.join(self.template_dir, "chapter", "ch*.tex")):
                            with open(ch_file, "r", encoding="utf-8") as cf:
                                ch_content = cf.read()
                            pattern = rf"% \[TABLE-{table_id}\].*?% \[/TABLE-{table_id}\]"
                            if re.search(pattern, ch_content, re.DOTALL):
                                new_ch = re.sub(pattern, ov_content, ch_content, flags=re.DOTALL)
                                with open(ch_file, "w", encoding="utf-8") as cf:
                                    cf.write(new_ch)
                                self.log(f"已应用 {f_name} 到 {os.path.basename(ch_file)}", "OK")

        # --- 6. Final sanity: no legacy tokens in generated main.tex ---
        with open(main_tex_path, "r", encoding="utf-8") as f:
            final = f.read()
        for token in FORBIDDEN_LEGACY_TOKENS:
            if token in final:
                self.log(f"❌ LEGACY TOKEN 残留: '{token}' in main.tex", "ERROR")
                return False

        self.report["steps"].append({"script": "assemble_v2", "status": "success"})
        return True

    # =========================================================================
    # Step 3.7: Normalize citations (unchanged logic, no early-exit)
    # =========================================================================

    def step3_7_normalize_citations(self) -> bool:
        self.log_step(3.7, "引用标记转换")

        chapters_dir = os.path.join(self.template_dir, "chapter")
        ch_files = glob.glob(os.path.join(chapters_dir, "ch*.tex"))
        if not ch_files:
            self.log("无章节文件，跳过引用转换", "INFO")
            self._skip_footnote_conversion = True
            return True

        has_citations = False
        for ch_file in ch_files:
            with open(ch_file, "r", encoding="utf-8") as f:
                if re.search(r'\[\d+\]', f.read()):
                    has_citations = True
                    break

        if not has_citations:
            self.log("章节中未发现 [数字] 引用标记，跳过引用转换", "INFO")
            self._skip_footnote_conversion = True
            return True

        cite_map_path = os.path.join(self.extracted_dir, "cite_map.json")
        if not os.path.exists(cite_map_path):
            self.log(f"cite_map.json 不存在: {cite_map_path}", "ERROR")
            return False

        return self.run_script(
            "normalize_citations.py",
            [cite_map_path, chapters_dir],
            "引用标记转换"
        )

    # =========================================================================
    # Step 4 [marxism]: Footnote conversion (unchanged)
    # =========================================================================

    def step4_marxism_footnotes(self) -> bool:
        if self.cite_style != "footnote-per-page":
            self.log("标准引用模式，跳过脚注转换", "INFO")
            return True
        if getattr(self, '_skip_footnote_conversion', False):
            self.log_step(4, "[马院] 引用 → 脚注转换")
            self.log("无 [数字] 引用标记，跳过脚注转换", "INFO")
            return True

        self.log_step(4, "[马院] 引用 → 脚注转换")
        raw_path = os.path.join(self.extracted_dir, "references_raw.txt")
        chapters_dir = os.path.join(self.template_dir, "chapter")
        if not os.path.exists(raw_path):
            self.log("references_raw.txt 不存在", "ERROR")
            return False
        return self.run_script(
            "refs_to_footnotes.py",
            [self.extracted_dir, chapters_dir],
            "脚注生成"
        )

    # =========================================================================
    # Step 5 [marxism]: Categorized bibliography (unchanged)
    # =========================================================================

    def step5_marxism_categorize(self) -> bool:
        if self.bib_mode != "categorized":
            self.log("标准文献模式，跳过分类处理", "INFO")
            return True
        self.log_step(5, "[马院] 生成分类参考文献")
        raw_path = os.path.join(self.extracted_dir, "references_raw.txt")
        output_path = os.path.join(self.template_dir, "bibliography_categorized.tex")
        return self.run_script(
            "categorize_refs.py",
            [raw_path, output_path],
            "分类文献生成"
        )

    # =========================================================================
    # Step 6: Compile (updated for DissertationUESTC)
    # =========================================================================

    def step6_compile(self) -> bool:
        self.log_step(6, "编译 LaTeX → PDF [DissertUESTC]")

        compile_script = (
            "export OSFONTDIR=/thesis/fonts:/thesis/font && cd /thesis && "
            "latexmk -f -xelatex -quiet -interaction=nonstopmode main.tex"
        )
        self.log("编译引擎: latexmk -xelatex (DissertUESTC)")

        docker_image = self.config.get("docker_image", "ghcr.io/xu-cheng/texlive-full:20240101")
        font_dir = r"C:\Windows\Fonts"

        cmd = [
            "docker", "run", "--rm",
            "-v", f"{self.template_dir}:/thesis",
            "-v", f"{font_dir}:/thesis/fonts:ro",
            "-w", "/thesis",
            docker_image,
            "bash", "-c", compile_script
        ]

        self.log(f"Docker 编译中... (可能需要 1-2 分钟)")

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=300
            )

            pdf_path = os.path.join(self.template_dir, "main.pdf")
            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 10000:
                pdf_size_mb = os.path.getsize(pdf_path) / 1024 / 1024
                self.log(f"编译成功！PDF 大小: {pdf_size_mb:.1f} MB", "OK")

                # Check build log for fatal errors (Codex gate)
                log_path = os.path.join(self.template_dir, "main.log")
                if os.path.exists(log_path):
                    with open(log_path, "r", encoding="utf-8", errors="replace") as lf:
                        log_content = lf.read()
                    pages = re.findall(r"Output written on .+\((\d+) pages", log_content)
                    if pages:
                        self.log(f"PDF 共 {pages[-1]} 页", "OK")

                    # Build log gate (Codex Q2 required)
                    fatal_patterns = [
                        "Undefined control sequence",
                        "! LaTeX Error",
                        "File `.*' not found",
                    ]
                    for pat in fatal_patterns:
                        if re.search(pat, log_content):
                            self.log(f"⚠️ Build log 包含: {pat}", "WARN")
                            self.report["warnings"].append(f"Build log: {pat}")

                self.report["steps"].append({"script": "compile", "status": "success"})
                return True
            else:
                self.log(f"编译失败 (exit code: {result.returncode})", "ERROR")
                errors = [l for l in result.stdout.split("\n") if l.startswith("!")]
                for err in errors[:5]:
                    self.log(f"  {err}", "WARN")
                self.report["errors"].append(f"Compile failed: {'; '.join(errors[:3])}")
                return False

        except subprocess.TimeoutExpired:
            self.log("编译超时（5 分钟）", "ERROR")
            return False
        except FileNotFoundError:
            self.log("Docker 未安装或不可用", "ERROR")
            return False

    # =========================================================================
    # Step 6b: Postflight (unchanged)
    # =========================================================================

    def step6b_postflight(self) -> bool:
        self.log_step("6b", "Post-flight PDF 质量检查")
        pdf_path = os.path.join(self.template_dir, "main.pdf")
        if not os.path.exists(pdf_path):
            self.log("PDF 未生成，跳过 Post-flight", "WARN")
            return True
        try:
            from postflight_check import run_postflight
            report = run_postflight(pdf_path)
            print(report.summary())
            postflight_path = os.path.join(self.output_dir, 'postflight_report.json')
            with open(postflight_path, 'w', encoding='utf-8') as f:
                json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
            self.report['steps'].append({
                'script': 'postflight_check',
                'status': 'success' if report.ok else 'warnings'
            })
            if not report.ok:
                self.log(f"Post-flight 发现 {report.failed} 个问题", "WARN")
            else:
                self.log(f"Post-flight 通过 ({report.passed} 项全绿)", "OK")
            return True
        except ImportError:
            self.log("postflight_check.py 不可用，跳过后检", "WARN")
            return True
        except Exception as e:
            self.log(f"Post-flight 异常: {e}", "WARN")
            return True

    # =========================================================================
    # Step 7: Report (unchanged)
    # =========================================================================

    def step7_report(self):
        self.log_step(7, "完成报告")
        pdf_path = os.path.join(self.template_dir, "main.pdf")
        if os.path.exists(pdf_path):
            size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
            self.log(f"📄 PDF 输出: {pdf_path} ({size_mb:.1f} MB)", "OK")
        else:
            self.log("⚠️ PDF 文件未生成", "WARN")
        if self.report["errors"]:
            print(f"\n  ❌ 错误: {len(self.report['errors'])} 个")
            for err in self.report["errors"]:
                print(f"    - {err}")
        if self.report["warnings"]:
            print(f"\n  ⚠️ 警告: {len(self.report['warnings'])} 个")
            for warn in self.report["warnings"]:
                print(f"    - {warn}")
        report_path = os.path.join(self.output_dir, "run_report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(self.report, f, ensure_ascii=False, indent=2)
        self.log(f"报告已保存: {report_path}", "OK")

    # =========================================================================
    # Pipeline orchestration
    # =========================================================================

    def run(self) -> bool:
        print(f"\n{'#'*60}")
        print(f"  Thesis Formatter v2.0 (DissertUESTC Engine)")
        print(f"  Profile: {self.profile_name}")
        print(f"  Citation: {self.cite_style} | Bibliography: {self.bib_mode}")
        print(f"  Compile: latexmk -xelatex")
        print(f"{'#'*60}")

        # NOTE: step3_6_patch_cls is REMOVED — new template needs no CLS patching
        steps = [
            self.step0_preflight,
            self.step1_extract,
            self.step2_confirm_outline,
            self.step_run_hooks,
            self.step3_generate_bib,
            self.step3_5_assemble,
            self.step3_7_normalize_citations,
        ]

        if self.bib_mode == "categorized":
            steps.append(self.step5_marxism_categorize)
        if self.cite_style == "footnote-per-page":
            steps.append(self.step4_marxism_footnotes)

        steps.extend([
            self.step6_compile,
            self.step6b_postflight,
        ])

        for step_fn in steps:
            success = step_fn()
            if not success:
                self.log(f"流程在 {step_fn.__name__} 中断", "ERROR")
                self.step7_report()
                return False

        self.step7_report()
        return True


def main():
    parser = argparse.ArgumentParser(
        description="Thesis Formatter v2 — DissertationUESTC Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_v2.py thesis.docx --profile uestc-marxism
  python run_v2.py thesis.docx --profile uestc --auto
        """
    )
    parser.add_argument("docx", help="输入 .docx 文件路径")
    parser.add_argument("--profile", required=True, help="Profile 名称 (uestc, uestc-marxism)")
    parser.add_argument("--output-dir", default="./output", help="输出目录 (默认: ./output)")
    parser.add_argument("--template-dir", default=None, help="LaTeX 模板目录 (已有则复用)")
    parser.add_argument("--auto", action="store_true", help="自动模式：跳过人工确认")

    args = parser.parse_args()

    formatter = ThesisFormatterV2(
        docx_path=args.docx,
        profile_name=args.profile,
        output_dir=args.output_dir,
        template_dir=args.template_dir,
        auto=args.auto,
    )

    success = formatter.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
