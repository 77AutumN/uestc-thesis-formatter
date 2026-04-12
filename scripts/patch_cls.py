#!/usr/bin/env python3
"""
patch_cls.py — 对 thesis-uestc.cls 应用马院定制补丁

补丁内容:
  1. 修复脚注 \ding 语法错误 (\ding{180\or\ding{181}} → \ding{180}\or\ding{181})
  2. 扩展脚注编号范围: ①-⑩ → ①-⑳ (支持每页 >10 条脚注)

用法:
  python patch_cls.py <thesis-uestc.cls 路径>
"""

import argparse
import os
import re
import sys


# 原始的 buggy 脚注定义 (仅支持 ①-⑩，且可能有 \ding{180 少 } 的问题)
ORIGINAL_FOOTNOTE_BUGGY = (
    r"\renewcommand{\thefootnote}{\ifcase\value{footnote}\or\ding{172}\or"
    "\n"
    r"\ding{173}\or\ding{174}\or\ding{175}\or\ding{176}\or\ding{177}\or"
    "\n"
    r"\ding{178}\or\ding{179}\or\ding{180\or\ding{181}}\fi}"
)

# 另一种原始模式 (语法正确但仅 ①-⑩)
ORIGINAL_FOOTNOTE_SHORT = (
    r"\renewcommand{\thefootnote}{\ifcase\value{footnote}\or\ding{172}\or"
    "\n"
    r"\ding{173}\or\ding{174}\or\ding{175}\or\ding{176}\or\ding{177}\or"
    "\n"
    r"\ding{178}\or\ding{179}\or\ding{180}\or\ding{181}\fi}"
)

# 修复后的脚注定义 (支持 ①-⑳)
PATCHED_FOOTNOTE = (
    r"\renewcommand{\thefootnote}{\ifcase\value{footnote}\or\ding{172}\or"
    "\n"
    r"\ding{173}\or\ding{174}\or\ding{175}\or\ding{176}\or\ding{177}\or"
    "\n"
    r"\ding{178}\or\ding{179}\or\ding{180}\or\ding{181}\or"
    "\n"
    r"\ding{192}\or\ding{193}\or\ding{194}\or\ding{195}\or\ding{196}\or"
    "\n"
    r"\ding{197}\or\ding{198}\or\ding{199}\or\ding{200}\or\ding{201}\fi}"
)


def patch_cls(cls_path: str) -> dict:
    """对 .cls 文件应用补丁，返回报告"""
    report = {"file": cls_path, "patches_applied": [], "already_patched": [], "errors": []}

    if not os.path.exists(cls_path):
        report["errors"].append(f"文件不存在: {cls_path}")
        return report

    with open(cls_path, "r", encoding="utf-8") as f:
        content = f.read()

    original_content = content

    # --- 补丁 1: 修复脚注语法 + 扩展到 ①-⑳ ---
    if PATCHED_FOOTNOTE in content:
        report["already_patched"].append("footnote-range-20: 已是最新版")
    elif ORIGINAL_FOOTNOTE_BUGGY in content:
        content = content.replace(ORIGINAL_FOOTNOTE_BUGGY, PATCHED_FOOTNOTE)
        report["patches_applied"].append("footnote-range-20: 修复语法错误 + 扩展到 ①-⑳")
    elif ORIGINAL_FOOTNOTE_SHORT in content:
        content = content.replace(ORIGINAL_FOOTNOTE_SHORT, PATCHED_FOOTNOTE)
        report["patches_applied"].append("footnote-range-20: ①-⑩ 扩展到 ①-⑳")
    else:
        # 尝试更宽松的匹配 (处理 \r\n 等)
        normalized = content.replace("\r\n", "\n")
        if ORIGINAL_FOOTNOTE_BUGGY in normalized:
            normalized = normalized.replace(ORIGINAL_FOOTNOTE_BUGGY, PATCHED_FOOTNOTE)
            content = normalized
            report["patches_applied"].append("footnote-range-20: 修复语法 + 扩展 (normalized)")
        elif ORIGINAL_FOOTNOTE_SHORT in normalized:
            normalized = normalized.replace(ORIGINAL_FOOTNOTE_SHORT, PATCHED_FOOTNOTE)
            content = normalized
            report["patches_applied"].append("footnote-range-20: 扩展到 ①-⑳ (normalized)")
        elif PATCHED_FOOTNOTE in normalized:
            report["already_patched"].append("footnote-range-20: 已是最新版 (normalized)")
        else:
            report["errors"].append("footnote-range-20: 无法定位原始脚注定义，请手动检查")

    # --- 补丁 2: 修复 Docker (Linux) 环境下的字体加载 ---
    # 因为 compile.ps1 将 Windows 字体挂载到了 Docker 内，我们需要将 Linux 分支的方正字体替换为 SimSun/SimHei
    ORIG_LINUX_FONTS = (
        r"\setCJKmainfont[AutoFakeBold=true]{fzsong.ttf}"
        "\n"
        r"  \newCJKfontfamily{\heiti}{fzhei.ttf}"
        "\n"
        r"  \newfontfamily{\heiti@letter}{fzhei.ttf}"
        "\n"
        r"  \setallmainfonts["
        "\n"
        r"    BoldFont=timesbd.ttf,"
        "\n"
        r"    ItalicFont=timesi.ttf,"
        "\n"
        r"    BoldItalicFont=timesbi.ttf,"
        "\n"
        r"  ]{times.ttf}"
    )
    PATCHED_LINUX_FONTS = (
        r"\setCJKmainfont[Path=fonts/, AutoFakeBold=true]{simsun.ttc}"
        "\n"
        r"  \newCJKfontfamily{\heiti}[Path=fonts/]{simhei.ttf}"
        "\n"
        r"  \newfontfamily{\heiti@letter}[Path=fonts/]{simhei.ttf}"
        "\n"
        r"  \setallmainfonts["
        "\n"
        r"    Path=fonts/,"
        "\n"
        r"    BoldFont=timesbd.ttf,"
        "\n"
        r"    ItalicFont=timesi.ttf,"
        "\n"
        r"    BoldItalicFont=timesbi.ttf,"
        "\n"
        r"  ]{times.ttf}"
    )
    
    if PATCHED_LINUX_FONTS in content:
        report["already_patched"].append("docker-fonts: Linux/Docker 分支字体已替换为 SimSun/SimHei")
    elif ORIG_LINUX_FONTS in content:
        content = content.replace(ORIG_LINUX_FONTS, PATCHED_LINUX_FONTS)
        report["patches_applied"].append("docker-fonts: Linux/Docker 分支字体替换为 SimSun/SimHei")
    else:
        # 宽容模式
        normalized = content.replace("\r\n", "\n")
        if ORIG_LINUX_FONTS in normalized:
            normalized = normalized.replace(ORIG_LINUX_FONTS, PATCHED_LINUX_FONTS)
            content = normalized
            report["patches_applied"].append("docker-fonts: Linux/Docker 分支字体替换为 SimSun/SimHei (normalized)")
        else:
            report["errors"].append("docker-fonts: 无法定位 Linux 字体定义块")

    # --- 写回文件 ---
    if content != original_content:
        with open(cls_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"✅ 已应用 {len(report['patches_applied'])} 个补丁到 {cls_path}")
    else:
        if report["already_patched"]:
            print(f"ℹ️ 所有补丁已是最新，无需修改")
        elif report["errors"]:
            print(f"⚠️ 补丁应用失败: {report['errors']}")

    return report


def main():
    parser = argparse.ArgumentParser(description="对 thesis-uestc.cls 应用马院定制补丁")
    parser.add_argument("cls_path", help=".cls 文件路径")
    args = parser.parse_args()

    report = patch_cls(args.cls_path)

    # 输出摘要
    for p in report["patches_applied"]:
        print(f"  ✅ {p}")
    for p in report["already_patched"]:
        print(f"  ℹ️ {p}")
    for e in report["errors"]:
        print(f"  ❌ {e}")

    if report["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
