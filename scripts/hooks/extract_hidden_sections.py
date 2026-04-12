"""
Hook: extract_hidden_sections — 提取未被 Word Heading 标记的隐藏章节

目前用于检测并分离：
  1. 「结语」— 常常混入最后一章正文中
  2. 「攻读学位期间取得的成果」— 常常混入参考文献中

此 hook 不依赖 profile 配置（所有学院通用），但保留 --profile / --dry-run
接口以保持 hooks 协议一致性。

Usage:
  被 run_v2.py 管线调用:
    extract_hidden_sections(extracted_dir, template_dir)

  独立运行:
    python extract_hidden_sections.py <extracted_dir> <template_dir> --profile <name>

  配置自检 (Smoke Test):
    python extract_hidden_sections.py --profile <name> --dry-run
"""
import argparse
import os
import re
import sys


def extract_hidden_sections(extracted_dir: str, template_dir: str):
    """
    Hooks for extracting hidden sections (like Conclusion and Accomplishments)
    that were not formatted as Headings in Word and got mixed into chapters or references.
    """
    print(f"  [Hook] Running extract_hidden_sections on {extracted_dir}")

    ch_dir = os.path.join(extracted_dir, "chapters")
    if not os.path.exists(ch_dir):
        return

    misc_dir = os.path.join(template_dir, "misc")
    os.makedirs(misc_dir, exist_ok=True)

    # 1. Detect and extract '结语' from the last chapter
    ch_files = sorted([f for f in os.listdir(ch_dir) if f.endswith('.tex')])
    if ch_files:
        last_ch = os.path.join(ch_dir, ch_files[-1])
        with open(last_ch, 'r', encoding='utf-8') as f:
            content = f.read()

        match = re.search(r'\n(结语)\s*\n(.*)', content, re.DOTALL)
        if match:
            print(f"    -> Found '结语' in {ch_files[-1]}, splitting...")
            new_ch_content = content[:match.start()].strip() + '\n'
            conclusion_content = match.group(2).strip()

            with open(last_ch, 'w', encoding='utf-8') as f:
                f.write(new_ch_content)

            conclusion_tex = "\\chapter*{结语}\n\\addcontentsline{toc}{chapter}{结语}\n\\markboth{结语}{结语}\n\n" + conclusion_content + "\n"
            with open(os.path.join(misc_dir, 'conclusion.tex'), 'w', encoding='utf-8') as f:
                f.write(conclusion_tex)

    # 2. Detect and extract '攻读硕士学位期间取得的成果' from references_raw.txt
    refs_file = os.path.join(extracted_dir, "references_raw.txt")
    if os.path.exists(refs_file):
        with open(refs_file, 'r', encoding='utf-8') as f:
            refs_content = f.read()

        match = re.search(r'(攻读[博硕]士学位期间取得的成果)(.*)', refs_content, re.DOTALL)
        if match:
            print(f"    -> Found '攻读学位期间取得的成果' in references_raw.txt, splitting...")
            new_refs_content = refs_content[:match.start()].strip() + '\n'
            acc_content = match.group(2).strip()

            with open(refs_file, 'w', encoding='utf-8') as f:
                f.write(new_refs_content)

            items = re.split(r'\[\d+\]', acc_content)
            acc_tex = "\\chapter*{攻读硕士学位期间取得的成果}\n\\addcontentsline{toc}{chapter}{攻读硕士学位期间取得的成果}\n\\markboth{攻读硕士学位期间取得的成果}{攻读硕士学位期间取得的成果}\n\n\\begin{enumerate}[label={[\\arabic*]}, leftmargin=2.5em, itemsep=0.5em]\n"
            for item in items:
                item = item.strip()
                if item:
                    acc_tex += f"  \\item {item}\n"
            acc_tex += "\\end{enumerate}\n"

            with open(os.path.join(misc_dir, 'accomplishments.tex'), 'w', encoding='utf-8') as f:
                f.write(acc_tex)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract hidden sections hook")
    parser.add_argument("extracted_dir", nargs="?", help="Extracted content directory")
    parser.add_argument("template_dir", nargs="?", help="Template project directory")
    parser.add_argument("--profile", help="Profile name (for protocol consistency)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print hook info and exit without processing files")
    args = parser.parse_args()

    if args.dry_run:
        print(f"[dry-run] profile={args.profile or 'any'}")
        print(f"  hook_type=structure_extraction")
        print(f"  profile_dependent=false")
        print(f"  detects=结语, 攻读学位期间取得的成果")
        sys.exit(0)

    if not args.extracted_dir or not args.template_dir:
        parser.error("extracted_dir and template_dir are required when not using --dry-run")

    extract_hidden_sections(args.extracted_dir, args.template_dir)
