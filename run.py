#!/usr/bin/env python3
"""
run.py — Thesis Formatter 端到端编排器

一条命令完成论文排版全流程：
    python run.py <thesis.docx> --profile uestc-marxism --output-dir ./output/

流程:
    1. 加载 Profile（含 parent 继承合并）
    2. extract_docx.py → 提取内容
    3. （暂停）输出 outline 让用户确认（--auto 跳过）
    4. refs_to_bib.py → 生成 .bib
    5. [marxism] refs_to_footnotes.py → cite 转脚注
    6. [marxism] categorize_refs.py → 分类文献
    7. 组装 main.tex
    8. compile → 编译 PDF
"""

import argparse
import json
import os
import subprocess
import re
import sys

# 确保 scripts 目录在 Python path 中
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPTS_DIR) if os.path.basename(SCRIPTS_DIR) == "scripts" else SCRIPTS_DIR
if os.path.basename(SCRIPTS_DIR) != "scripts":
    SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")

sys.path.insert(0, SCRIPTS_DIR)
from profile_loader import load_profile, get_compile_chain, get_bibliography_mode, get_citation_style


class ThesisFormatter:
    """端到端论文排版编排器"""

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

        # 确定 template 工作目录
        if template_dir:
            self.template_dir = os.path.abspath(template_dir)
        else:
            self.template_dir = os.path.join(self.output_dir, "thesis-uestc")

        self.report = {
            "profile": profile_name,
            "steps": [],
            "errors": [],
            "warnings": [],
        }

    def log(self, msg: str, level: str = "INFO"):
        """输出带前缀的日志"""
        icons = {"INFO": "📌", "OK": "✅", "WARN": "⚠️", "ERROR": "❌", "STEP": "🔄"}
        icon = icons.get(level, "")
        print(f"  {icon} {msg}")

    def log_step(self, step_num: int, title: str):
        """输出步骤标题"""
        print(f"\n{'='*60}")
        print(f"  Step {step_num}: {title}")
        print(f"{'='*60}")

    def run_script(self, script_name: str, args: list, description: str) -> bool:
        """运行一个 Python 脚本，返回是否成功"""
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
                self.report["errors"].append(f"{script_name} failed: {result.stderr[:200]}")
                return False
            self.report["steps"].append({"script": script_name, "status": "success"})
            return True
        except Exception as e:
            self.log(f"运行 {script_name} 异常: {e}", "ERROR")
            self.report["errors"].append(f"{script_name} exception: {str(e)}")
            return False

    def step0_preflight(self) -> bool:
        """Step 0: Pre-flight 输入检查"""
        self.log_step(0, "Pre-flight 输入检查")

        try:
            sys.path.insert(0, SCRIPTS_DIR)
            from preflight_check import run_preflight
            report = run_preflight(self.docx_path, self.profile_name)
            print(report.summary())

            # 保存报告
            preflight_path = os.path.join(self.output_dir, 'preflight_report.json')
            os.makedirs(self.output_dir, exist_ok=True)
            with open(preflight_path, 'w', encoding='utf-8') as f:
                json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)

            self.report['steps'].append({'script': 'preflight_check', 'status': 'success' if report.ok else 'failed'})

            if not report.ok:
                self.log(f"Pre-flight 检查未通过 ({report.failed} 个阻塞项)", "ERROR")
                self.report['errors'].append(f"Preflight failed: {report.failed} blocking issues")
                return False

            if report.warnings > 0:
                self.log(f"Pre-flight 通过，但有 {report.warnings} 个警告", "WARN")
                self.report['warnings'].append(f"Preflight: {report.warnings} warnings")

            self.log(f"Pre-flight 通过 ({report.passed}/{report.passed + report.warnings} 项)", "OK")
            return True

        except ImportError:
            self.log("preflight_check.py 不可用，跳过预检", "WARN")
            return True
        except Exception as e:
            self.log(f"Pre-flight 异常: {e}", "WARN")
            return True  # 预检异常不阻塞 pipeline

    def step1_extract(self) -> bool:
        """Step 1: 提取 .docx 内容（Pandoc AST 引擎）"""
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

    def step2_confirm_outline(self) -> bool:
        """Step 2: 确认章节结构"""
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
                self.log("用户取消，请手动修正后重试", "WARN")
                return False

        self.log("结构已确认", "OK")
        return True


    def step_run_hooks(self) -> bool:
        self.log_step(2.5, "运行提取后置钩子 (Hooks)")
        self.run_script("hooks/extract_hidden_sections.py", [self.extracted_dir, self.template_dir], "隐藏章节提取 (结语/成果页)")
        self.run_script("hooks/format_abstract.py", [self.extracted_dir, self.template_dir], "摘要格式化")
        self.run_script("hooks/format_punctuation.py", [self.template_dir], "标点符号规范化")
        return True

    def step3_generate_bib(self) -> bool:

        """Step 3: 生成 BibTeX"""
        self.log_step(3, "生成 BibTeX 参考文献")

        raw_path = os.path.join(self.extracted_dir, "references_raw.txt")
        if not os.path.exists(raw_path):
            self.log("references_raw.txt 未找到，跳过参考文献处理", "WARN")
            self.report["warnings"].append("No references_raw.txt found")
            return True  # 非致命

        bib_path = os.path.join(self.template_dir, "reference.bib")

        return self.run_script(
            "refs_to_bib.py",
            ["--input", raw_path, "--output", bib_path],
            "BibTeX 生成"
        )

    def step3_5_assemble(self) -> bool:
        """Step 3.5: 组装模板和章节"""
        self.log_step(3.5, "组装 LaTeX 模板与章节")
        
        import shutil
        import glob
        import re
        
        # 1. 拷贝基础模板（排除 .git 目录避免权限锁定）
        src_template = os.path.abspath("thesis-uestc")
        if os.path.exists(src_template) and src_template != self.template_dir:
            self.log(f"复制基础模板到 {self.template_dir}")
            try:
                shutil.copytree(
                    src_template, self.template_dir,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('.git', '__pycache__'),
                )
            except Exception as e:
                self.log(f"复制模板失败: {e}", "ERROR")
                return False

        # 2. 拷贝提取的章节 .tex 到 template 的 chapter 目录
        src_chap_dir = os.path.join(self.extracted_dir, "chapters")
        dst_chap_dir = os.path.join(self.template_dir, "chapter")
        os.makedirs(dst_chap_dir, exist_ok=True)
        
        ch_files = glob.glob(os.path.join(src_chap_dir, "ch*.tex"))
        if ch_files:
            for f in ch_files:
                shutil.copy(f, dst_chap_dir)
            self.log(f"复制了 {len(ch_files)} 个章节文件", "OK")

        # 2.5 拷贝提取的图片到 template 的 media 目录（Phase 2: STEM 论文图片）
        src_media_dir = os.path.join(self.extracted_dir, "media")
        if os.path.exists(src_media_dir):
            dst_media_dir = os.path.join(self.template_dir, "media")
            # media/ 下可能有子目录 (Pandoc 输出到 media/media/)
            # 扫描所有图片文件，平铺复制到 dst_media_dir/
            os.makedirs(dst_media_dir, exist_ok=True)
            img_count = 0
            for root, dirs, files in os.walk(src_media_dir):
                for fname in files:
                    if fname.lower().endswith(('.png', '.jpg', '.jpeg', '.pdf', '.eps', '.svg')):
                        src_img = os.path.join(root, fname)
                        shutil.copy(src_img, dst_media_dir)
                        img_count += 1
            if img_count > 0:
                self.log(f"复制了 {img_count} 个图片到 media/", "OK")

        # 3. 处理摘要、致谢到 misc 目录
        misc_dir = os.path.join(self.template_dir, "misc")
        os.makedirs(misc_dir, exist_ok=True)
        
        # 3.1 处理中文摘要
        zh_txt = os.path.join(self.extracted_dir, "abstract_zh.txt")
        if os.path.exists(zh_txt):
            with open(zh_txt, "r", encoding="utf-8") as f:
                content = f.read().strip()
            match = re.search(r'(?:关键词|Keywords)[:：]\s*(.+)', content, flags=re.IGNORECASE|re.MULTILINE)
            keywords = "暂无关键词"
            if match:
                keywords = match.group(1).strip()
                content = content[:match.start()].strip()
            tex_content = f"\\begin{{chineseabstract}}\n{content}\n\n\\chinesekeyword{{{keywords}}}\n\\end{{chineseabstract}}\n\\clearpage\n"
            with open(os.path.join(misc_dir, "chinese_abstract.tex"), "w", encoding="utf-8") as f:
                f.write(tex_content)
                
        # 3.2 处理英文摘要
        en_txt = os.path.join(self.extracted_dir, "abstract_en.txt")
        if os.path.exists(en_txt):
            with open(en_txt, "r", encoding="utf-8") as f:
                content = f.read().strip()
            match = re.search(r'(?:关键词|Keywords)[:：]\s*(.+)', content, flags=re.IGNORECASE|re.MULTILINE)
            keywords = "No keywords"
            if match:
                keywords = match.group(1).strip()
                content = content[:match.start()].strip()
            tex_content = f"\\begin{{englishabstract}}\n{content}\n\n\\englishkeyword{{{keywords}}}\n\\end{{englishabstract}}\n\\clearpage\n"
            with open(os.path.join(misc_dir, "english_abstract.tex"), "w", encoding="utf-8") as f:
                f.write(tex_content)
                
        # 3.3 处理致谢
        ack_txt = os.path.join(self.extracted_dir, "acknowledgement.txt")
        if os.path.exists(ack_txt):
            with open(ack_txt, "r", encoding="utf-8") as f:
                content = f.read().strip()
            tex_content = f"\\thesisacknowledgement\n{content}\n"
            with open(os.path.join(misc_dir, "acknowledgement.tex"), "w", encoding="utf-8") as f:
                f.write(tex_content)
        
        # 3.4 处理攻读成果
        acc_txt = os.path.join(self.extracted_dir, "accomplishment.txt")
        if os.path.exists(acc_txt):
            with open(acc_txt, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                # 马院成果是纯文本，不用 BibTeX，使用 chapter* 手工排版
                tex_content = (
                    "\\chapter*{攻读硕士学位期间取得的成果}\n"
                    "\\addcontentsline{toc}{chapter}{攻读硕士学位期间取得的成果}\n"
                    "\\markboth{攻读硕士学位期间取得的成果}{攻读硕士学位期间取得的成果}\n\n"
                )
                # 每行一条成果
                for line in content.split("\n"):
                    line = line.strip()
                    if line:
                        tex_content += f"{line}\n\n"
                with open(os.path.join(misc_dir, "accomplishment.tex"), "w", encoding="utf-8") as f:
                    f.write(tex_content)
                self.log("已生成 misc/accomplishment.tex", "OK")
        
        self.log(f"成功处理摘要与致谢", "OK")

        # C1: Logo 文件检查
        logo_path = os.path.join(self.template_dir, "logo.pdf")
        if not os.path.exists(logo_path):
            self.log("封面 Logo 文件 logo.pdf 缺失！封面将无校徽", "WARN")
                
        # 4. 基于 main_multifile.tex 动态组装 main.tex
        multifile_path = os.path.join(self.template_dir, "main_multifile.tex")
        main_tex_path = os.path.join(self.template_dir, "main.tex")
        
        if os.path.exists(multifile_path):
            with open(multifile_path, "r", encoding="utf-8") as f:
                content = f.read()
                
            # 替换章节引用
            content = re.sub(r'\\input\{chapter/[^}]+\}\n?', '', content)
            
            # 生成新的 \input
            chapter_inputs = []
            ch_names = sorted([os.path.basename(f).replace('.tex', '') for f in ch_files])
            for ch in ch_names:
                chapter_inputs.append(rf"\input{{chapter/{ch}}}")
            
            # 插入到原来章节的位置
            if r'\thesistableofcontents' in content:
                insert_idx = content.find(r'\thesistableofcontents') + len(r'\thesistableofcontents')
                insert_txt = "\n\n% 自动生成的章节引用\n" + "\n".join(chapter_inputs) + "\n\n"
                content = content[:insert_idx] + insert_txt + content[insert_idx:]
            
            # 替换封面元数据：优先从 Word 提取，fallback 到模板默认值
            cover_meta_path = os.path.join(self.extracted_dir, 'cover_metadata.json')
            cm = {}
            if os.path.exists(cover_meta_path):
                with open(cover_meta_path, 'r', encoding='utf-8') as f:
                    cm = json.load(f)
                self.log(f"封面元数据已加载 ({len(cm)} 个字段)", "OK")
            else:
                self.log("未找到 cover_metadata.json，使用模板默认值", "WARN")
            title_cn = cm.get('title_cn') or '论文标题'
            title_en = cm.get('title_en') or ''
            author_cn = cm.get('author_cn') or '~'
            author_en = cm.get('author_en') or '~'
            major_cn = cm.get('major_cn') or '专业'
            major_en = cm.get('major_en') or ''
            school_cn = cm.get('school_cn') or '学院'
            school_en = cm.get('school_en') or ''
            advisor_name = cm.get('advisor_name_cn') or '~'
            advisor_title = cm.get('advisor_title_cn') or ''
            advisor_en = cm.get('advisor_en') or '~'
            student_id = cm.get('student_id', '')

            # 格式化导师：姓名\chinesespace 职称
            advisor_cn_fmt = f"{advisor_name}\chinesespace {advisor_title}" if advisor_title and advisor_name != '~' else advisor_name      
            
            content = re.sub(r'\\title\{.*?\}\{.*?\}', lambda m: f'\\title{{{title_cn}}}{{{title_en}}}', content, flags=re.DOTALL)
            content = re.sub(r'\\author\{.*?\}\{.*?\}', lambda m: f'\\author{{{author_cn}}}{{{author_en}}}', content, flags=re.DOTALL)
            content = re.sub(r'\\major\{.*?\}\{.*?\}', lambda m: f'\\major{{{major_cn}}}{{{major_en}}}', content, flags=re.DOTALL)
            content = re.sub(r'\\school\{.*?\}\{.*?\}', lambda m: f'\\school{{{school_cn}}}{{{school_en}}}', content, flags=re.DOTALL)
            content = re.sub(r'\\advisor\{.*?\}\{.*?\}', lambda m: f'\\advisor{{{advisor_cn_fmt}}}{{{advisor_en}}}', content, flags=re.DOTALL)
            # 学号注入（STEM 论文特有）
            if student_id:
                content = re.sub(r'\\studentnumber\{.*?\}', lambda m: f'\\studentnumber{{{student_id}}}', content)
            
            # 学位类型注入：自动检测 > 默认 master
            # CLS 支持: bachelor, master, promaster, doctor, engdoctor
            degree_type = cm.get('degree_type', 'master')
            valid_degrees = {'bachelor', 'master', 'promaster', 'doctor', 'engdoctor'}
            if degree_type not in valid_degrees:
                self.log(f"未知学位类型 '{degree_type}'，回退到 master", "WARN")
                degree_type = 'master'
            content = re.sub(
                r'\\documentclass\[(\w+)\]\{thesis-uestc\}',
                lambda m: f'\\documentclass[{degree_type}]{{thesis-uestc}}',
                content
            )
            self.log(f"学位类型: {degree_type} (来源: {'封面自动检测' if cm.get('degree_type') else '默认值'})", "OK")
            
            # 替换马院特定的分类参考文献
            if self.bib_mode == "categorized":
                content = content.replace(r'\thesisbibliography{reference}', r'\input{bibliography_categorized.tex}')
                
            # W4 修复：由于可能存在 0 cite，强制加入 \nocite{*} 兜底
            if r'\thesisbibliography' in content:
                content = content.replace(r'\thesisbibliography', r'\nocite{*}' + '\n' + r'\thesisbibliography')
            # Inject conclusion if exists
            if os.path.exists(os.path.join(self.template_dir, 'misc', 'conclusion.tex')):
                if r'\input{misc/acknowledgement}' in content:
                    content = content.replace(r'\input{misc/acknowledgement}', '\\input{misc/conclusion}\n\\input{misc/acknowledgement}')

            # 马院模式：移除模板自带的附录、翻译等不需要的部分
            if self.cite_style == "footnote-per-page":
                content = re.sub(r'\\input\{misc/appendix\}\s*\n?', '', content)
                content = re.sub(r'\\input\{misc/translate_original\}\s*\n?', '', content)
                content = re.sub(r'\\input\{misc/translate_chinese\}\s*\n?', '', content)
                
                # 处理攻读成果：
                acc_tex = os.path.join(self.template_dir, "misc", "accomplishments.tex")
                acc_txt = os.path.join(self.extracted_dir, "accomplishment.txt")
                
                if os.path.exists(acc_tex):
                    content = re.sub(
                        r'\\thesisaccomplish\{[^}]*\}\s*\n?',
                        r'\\input{misc/accomplishments}' + '\n',
                        content
                    )
                    self.log("成果 section 已替换为 \\input{misc/accomplishments}", "OK")
                elif os.path.exists(acc_txt) and os.path.getsize(acc_txt) > 10:
                    content = re.sub(
                        r'\\thesisaccomplish\{[^}]*\}\s*\n?',
                        r'\\input{misc/accomplishment}' + '\n',
                        content
                    )
                    self.log("成果 section 已替换为 \\input{misc/accomplishment}", "OK")
                else:
                    content = re.sub(r'\\thesisaccomplish\{[^}]*\}\s*\n?', '', content)
                    self.log("无成果内容，已移除占位", "OK")
                self.log("已移除模板附录/翻译占位", "OK")

                

            # 处理覆盖文件 (Overrides)
            override_dir = os.path.join(os.path.dirname(self.docx_path), "overrides")
            if os.path.exists(override_dir):
                for f in os.listdir(override_dir):
                    if f.endswith(".tex"):
                        override_path = os.path.join(override_dir, f)
                        with open(override_path, "r", encoding="utf-8") as ov_f:
                            ov_content = ov_f.read()
                        
                        # Apply override to ch*.tex
                        match = re.search(r'table_(\d+)\.tex', f)
                        if match:
                            table_id = match.group(1)
                            for ch_file in glob.glob(os.path.join(self.template_dir, "chapter", "ch*.tex")):
                                with open(ch_file, "r", encoding="utf-8") as cf:
                                    ch_content = cf.read()
                                pattern = rf"% \[TABLE-{table_id}\].*?% \[/TABLE-{table_id}\]"
                                if re.search(pattern, ch_content, re.DOTALL):
                                    new_ch_content = re.sub(pattern, ov_content, ch_content, flags=re.DOTALL)
                                    with open(ch_file, "w", encoding="utf-8") as cf:
                                        cf.write(new_ch_content)
                                    self.log(f"已应用 {f} 到 {os.path.basename(ch_file)}", "OK")

            # 清理残留的空注释

            content = content.replace("% thesis contents\n%\n% misc", "% misc")
                
            # 写入为 main.tex 覆盖原来的假文档
            with open(main_tex_path, "w", encoding="utf-8") as f:
                f.write(content)
            self.log("成功根据提取章节动态重组 main.tex", "OK")
        else:
            self.log(f"未找到模板文件 {multifile_path}", "WARN")

        return True

    def step3_6_patch_cls(self) -> bool:
        """Step 3.6 [marxism]: 应用马院补丁（混合策略）
        
        策略:
          - 脚注扩展 + 空白页修复 + enumitem → 编译期 .sty 注入（不修改 CLS）
          - 字体路径修复 → 仍需物理修改 CLS（Docker 环境适配，无法通过 LaTeX 覆盖）
        """
        if self.cite_style != "footnote-per-page":
            self.log("标准引用模式，跳过马院补丁", "INFO")
            return True

        self.log_step(3.6, "[马院] 模板补丁（.sty 注入 + 字体修复）")

        # --- Part A: 复制 uestc-patches.sty 到工作目录 ---
        sty_src = os.path.join(SKILL_DIR, "resources", "uestc-patches.sty")
        sty_dst = os.path.join(self.template_dir, "uestc-patches.sty")
        if os.path.exists(sty_src):
            import shutil
            shutil.copy2(sty_src, sty_dst)
            self.log("已复制 uestc-patches.sty 到编译目录", "OK")
        else:
            self.log(f"uestc-patches.sty 不存在: {sty_src}", "WARN")

        # --- Part B: 在 main.tex 中注入 \usepackage{uestc-patches} ---
        main_tex_path = os.path.join(self.template_dir, "main.tex")
        if os.path.exists(main_tex_path):
            with open(main_tex_path, "r", encoding="utf-8") as f:
                content = f.read()

            if "uestc-patches" not in content:
                # 在 \begin{document} 前注入
                content = content.replace(
                    r"\begin{document}",
                    "\\usepackage{uestc-patches}  % 马院运行时补丁\n\\begin{document}"
                )
                with open(main_tex_path, "w", encoding="utf-8") as f:
                    f.write(content)
                self.log("已在 main.tex 注入 uesct-patches.sty 加载", "OK")
            else:
                self.log("main.tex 已包含 uestc-patches，跳过注入", "INFO")

        # --- Part C: 字体路径修复（仍需物理修改 CLS）---
        cls_path = os.path.join(self.template_dir, "thesis-uestc.cls")
        if not os.path.exists(cls_path):
            self.log(f"thesis-uestc.cls 不存在: {cls_path}", "ERROR")
            return False

        # Make sure fonts exist
        import shutil
        src_fonts = os.path.abspath(os.path.join("thesis-uestc", "fonts"))
        dst_fonts = os.path.join(self.template_dir, 'fonts')
        if os.path.exists(src_fonts) and not os.path.exists(dst_fonts):
            shutil.copytree(src_fonts, dst_fonts)
            self.log("复制了 fonts 目录", "OK")


        return self.run_script(
            "patch_cls.py",
            [cls_path],
            "字体路径补丁"
        )

    def _has_citation_markers(self) -> bool:
        """检查 AST 引擎是否在正文中检测到 [数字] 引用标记"""
        meta_path = os.path.join(self.extracted_dir, "thesis_meta.json")
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            return meta.get("citation_markers_in_body", 0) > 0
        return False

    def step3_7_normalize_citations(self) -> bool:
        """Step 3.7 [marxism]: 将 [数字] 引用标记转换为 \\cite{key}"""
        if self.cite_style != "footnote-per-page":
            self.log("标准引用模式，跳过引用标记转换", "INFO")
            return True

        self.log_step(3.7, "[马院] [数字] → \\cite{key} 引用标记转换")

        # 新增：检查论文是否实际包含 [数字] 引用标记
        # 某些马院论文使用叙述内嵌式引用(如「作者（年份）」)，正文无 [N] 标记
        if not self._has_citation_markers():
            self.log("论文正文无 [数字] 引用标记（可能使用叙述内嵌式引用），跳过标记转换", "INFO")
            self.report["warnings"].append("No [N] citation markers found — skipped normalize_citations")
            self._skip_footnote_conversion = True  # 通知 step4 也跳过
            return True

        cite_map_path = os.path.join(self.extracted_dir, "cite_map.json")
        chapters_dir = os.path.join(self.template_dir, "chapter")

        if not os.path.exists(cite_map_path):
            self.log(f"cite_map.json 不存在: {cite_map_path}", "ERROR")
            return False


        return self.run_script(
            "normalize_citations.py",
            [cite_map_path, chapters_dir],
            "引用标记转换"
        )

    def step4_marxism_footnotes(self) -> bool:
        """Step 4 [marxism]: 将 \\cite → \\footnote"""
        if self.cite_style != "footnote-per-page":
            self.log("标准引用模式，跳过脚注转换", "INFO")
            return True

        # 如果 step3_7 因无引用标记而跳过，这里也跳过
        if getattr(self, '_skip_footnote_conversion', False):
            self.log_step(4, "[马院] 引用 → 脚注转换")
            self.log("无 [数字] 引用标记，跳过脚注转换（论文使用叙述内嵌式引用）", "INFO")
            return True

        self.log_step(4, "[马院] 引用 → 脚注转换")

        chapters_dir = os.path.join(self.template_dir, "chapter")
        success = self.run_script(
            "refs_to_footnotes.py",
            [self.extracted_dir, chapters_dir],
            "脚注转换"
        )

        # 自检断言：马院模式必须产生脚注
        if success:
            report_path = os.path.join(self.extracted_dir, "footnote_report.json")
            if os.path.exists(report_path):
                with open(report_path, "r", encoding="utf-8") as f:
                    fn_report = json.load(f)
                total = fn_report.get("total_replaced", 0)
                if total == 0:
                    self.log("⚠️ 严重: 脚注转换后 total_replaced=0, 请检查引用标记格式!", "ERROR")
                    self.report["errors"].append("Footnote replacement count is 0")
                    return False
                else:
                    self.log(f"脚注自检通过: {total} 处引用已转换为脚注", "OK")

        return success

    def step5_marxism_categorize(self) -> bool:
        """Step 5 [marxism]: 生成分类参考文献"""
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

    def step6_compile(self) -> bool:
        """Step 6: 编译 PDF"""
        self.log_step(6, "编译 LaTeX → PDF")

        # 构建编译命令
        main_tex = "main.tex"
        use_latexmk = self.config.get("use_latexmk", True)

        if use_latexmk:
            # latexmk 智能编译：自动判断所需编译次数，通常 2 次即可收敛（原需 4 次）
            has_bibtex = "bibtex" in self.compile_chain
            if has_bibtex:
                compile_script = (
                    "export OSFONTDIR=/thesis/fonts && cd /thesis && "
                    "latexmk -f -xelatex -quiet -interaction=nonstopmode main.tex"
                )
            else:
                # 马院模式：无 bibtex，纯 xelatex（latexmk 仍会自动决定遍数）
                compile_script = (
                    "export OSFONTDIR=/thesis/fonts && cd /thesis && "
                    "latexmk -f -xelatex -quiet -interaction=nonstopmode main.tex"
                )
            self.log("编译引擎: latexmk (智能判断编译次数)")
        else:
            # 回退：使用 profile 定义的固定编译链
            compile_cmds = []
            for step in self.compile_chain:
                if step == "bibtex":
                    compile_cmds.append(f"bibtex {main_tex.replace('.tex', '')} 2>/dev/null")
                else:
                    compile_cmds.append(f"{step} -interaction=nonstopmode {main_tex}")

            compile_script = "export OSFONTDIR=/thesis/fonts && cd /thesis && " + " ; ".join(compile_cmds)
            self.log(f"编译链: {' -> '.join(self.compile_chain)}")

        docker_image = self.config.get("docker_image", "ghcr.io/xu-cheng/texlive-full:latest")
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
                timeout=300  # 5 分钟超时
            )

            # 检查 PDF 是否实际生成（兼容 latexmk 和原始 xelatex）
            pdf_path = os.path.join(self.template_dir, "main.pdf")
            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 10000:
                # PDF 存在且大于 10KB，视为编译成功
                pdf_size_mb = os.path.getsize(pdf_path) / 1024 / 1024
                self.log(f"编译成功！PDF 大小: {pdf_size_mb:.1f} MB", "OK")

                # 尝试从日志中提取页数
                log_path = os.path.join(self.template_dir, "main.log")
                if os.path.exists(log_path):
                    with open(log_path, "r", encoding="utf-8", errors="replace") as lf:
                        log_content = lf.read()
                    import re as re_mod
                    pages = re_mod.findall(r"Output written on .+\((\d+) pages", log_content)
                    if pages:
                        self.log(f"PDF 共 {pages[-1]} 页", "OK")

                self.report["steps"].append({"script": "compile", "status": "success"})
                return True
            else:
                self.log(f"编译失败 (exit code: {result.returncode})", "ERROR")
                # 提取 LaTeX 错误
                errors = [l for l in result.stdout.split("\n") if l.startswith("!")]
                for err in errors[:5]:
                    self.log(f"  {err}", "WARN")
                self.report["errors"].append(f"Compile failed: {'; '.join(errors[:3])}")
                return False

        except subprocess.TimeoutExpired:
            self.log("编译超时（5 分钟），请检查 LaTeX 是否有死循环", "ERROR")
            return False
        except FileNotFoundError:
            self.log("Docker 未安装或不可用", "ERROR")
            return False

    def step6b_postflight(self) -> bool:
        """Step 6b: Post-flight PDF 质量检查"""
        self.log_step("6b", "Post-flight PDF 质量检查")

        pdf_path = os.path.join(self.template_dir, "main.pdf")
        if not os.path.exists(pdf_path):
            self.log("PDF 未生成，跳过 Post-flight", "WARN")
            return True

        try:
            sys.path.insert(0, SCRIPTS_DIR)
            from postflight_check import run_postflight

            # 查找参考 PDF
            reference_pdf = None
            ref_candidates = [
                os.path.join(os.path.dirname(self.docx_path), '新时代高校数字统战的建设问题研究_张文静.pdf'),
            ]
            for ref in ref_candidates:
                if os.path.exists(ref):
                    reference_pdf = ref
                    break

            report = run_postflight(pdf_path, reference_pdf)
            print(report.summary())

            # 保存报告
            postflight_path = os.path.join(self.output_dir, 'postflight_report.json')
            with open(postflight_path, 'w', encoding='utf-8') as f:
                json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)

            self.report['steps'].append({'script': 'postflight_check', 'status': 'success' if report.ok else 'warnings'})

            if not report.ok:
                self.log(f"Post-flight 发现 {report.failed} 个问题", "WARN")
                self.report['warnings'].append(f"Postflight: {report.failed} issues found")
            else:
                self.log(f"Post-flight 通过 ({report.passed} 项全绿)", "OK")

            return True  # Post-flight 不阻塞（仅报告）

        except ImportError:
            self.log("postflight_check.py 不可用，跳过后检", "WARN")
            return True
        except Exception as e:
            self.log(f"Post-flight 异常: {e}", "WARN")
            return True

    def step7_report(self):
        """Step 7: 输出总结报告"""
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

        # 保存报告
        report_path = os.path.join(self.output_dir, "run_report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(self.report, f, ensure_ascii=False, indent=2)
        self.log(f"报告已保存: {report_path}", "OK")

    def run(self) -> bool:
        """执行全流程"""
        print(f"\n{'#'*60}")
        print(f"  Thesis Formatter v1.0")
        print(f"  Profile: {self.profile_name}")
        print(f"  Citation: {self.cite_style} | Bibliography: {self.bib_mode}")
        print(f"  Compile: {' → '.join(self.compile_chain)}")
        print(f"{'#'*60}")

        
        steps = [
            self.step0_preflight,
            self.step1_extract,
            self.step2_confirm_outline,
            self.step_run_hooks, # New step for hooks
            self.step3_generate_bib,
            self.step3_5_assemble,
            self.step3_6_patch_cls,
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
        description="Thesis Formatter — 一条命令完成论文排版",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run.py thesis.docx --profile uestc-marxism
  python run.py thesis.docx --profile uestc --auto
  python run.py thesis.docx --profile uestc-marxism --template-dir ./thesis-uestc/
        """
    )
    parser.add_argument("docx", help="输入 .docx 文件路径")
    parser.add_argument("--profile", required=True, help="Profile 名称 (如 uestc, uestc-marxism)")
    parser.add_argument("--output-dir", default="./output", help="输出目录 (默认: ./output)")
    parser.add_argument("--template-dir", default=None, help="LaTeX 模板目录 (已有则复用，否则自动 clone)")
    parser.add_argument("--auto", action="store_true", help="自动模式：跳过人工确认步骤")

    args = parser.parse_args()

    formatter = ThesisFormatter(
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
