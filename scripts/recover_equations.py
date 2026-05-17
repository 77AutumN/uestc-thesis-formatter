"""recover_equations.py — Word OMath/VML equations → LaTeX equation blocks

Many UESTC theses use Word's legacy equation editor (Equation 3.0 / MathType),
which stores formulas as VML drawings + WMF fallback images instead of OMath.
Pandoc's docx reader misses these entirely — extracted/chapters/*.tex ends up
with naked "(2.1)" "(3.5)" labels and no equation bodies.

This recovery walker:
  1. Walks word/document.xml looking for paragraphs that contain BOTH a WMF
     drawing and an "(X.Y)" equation label
  2. Maps each (chapter, sub) → wmf_filename via rId resolution
  3. Converts all needed WMF → PNG via Dockerised LibreOffice headless
     (one batch call to amortize startup)
  4. Replaces the naked "(X.Y)" line in chapters/chXX.tex with a centered
     \\includegraphics block tagged with \\tag{X.Y}\\label{eq:X.Y}

Requires: docker daemon running, network access to pull
linuxserver/libreoffice:latest if not cached.

Pipeline integration:
    python recover_equations.py \\
        --docx <input.docx> \\
        --extracted <output_dir>/extracted \\
        --chapters <output_dir>/DissertationUESTC/chapter \\
        --media-dir <output_dir>/DissertationUESTC/media

Returns nonzero exit code if Docker conversion fails. Skip flag --no-convert
will reuse existing .png files in media-dir if conversion already done.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from collections import defaultdict
from typing import Optional

# Reuse helpers from recover_figures
from recover_figures import (
    parse_docx,
    find_chapter_boundaries,
    chapter_for_para,
)

EQ_LABEL_PAT = re.compile(r"^\(\s*(\d+)\s*[.\-－]\s*(\d+)\s*\)\s*$")
EQ_LINE_PAT_TMPL = r"^\s*\(\s*{ch}\s*[.\-－]\s*{n}\s*\)\s*$"


def build_equation_records(paras, rid_to_filename, boundaries, body_end=None):
    """Walk paragraphs; collect display-equation records.

    Returns list of dicts:
        {chapter, sub, wmf_filename, drawing_para, label_para}
    Only paragraphs with BOTH a WMF drawing AND an (X.Y) label match.
    Also includes paragraphs where the WMF is in para N and the (X.Y) label
    is in the very next non-empty paragraph (common Word layout).
    """
    records = []
    last_drawing = None  # (para_idx, [filenames])
    for p in paras:
        text = p["text"].strip()
        wmfs = []
        for rid in p["rids"]:
            f = rid_to_filename.get(rid)
            if f and f.lower().endswith(".wmf"):
                wmfs.append(f)

        # Case A: same-paragraph drawing + label
        m = EQ_LABEL_PAT.match(text)
        if wmfs and m:
            ch = int(m.group(1))
            sub = int(m.group(2))
            ch_for_p = chapter_for_para(p["idx"], boundaries, body_end)
            if ch_for_p is None:
                continue
            records.append({
                "chapter": ch,
                "sub": sub,
                "wmf_filename": wmfs[0],
                "drawing_para": p["idx"],
                "label_para": p["idx"],
            })
            last_drawing = None
            continue

        # Case B: drawing-only paragraph (track for next-para label)
        if wmfs and not text:
            last_drawing = (p["idx"], wmfs)
            continue

        # Case C: label-only paragraph immediately after drawing-only para
        if last_drawing and m:
            ch = int(m.group(1))
            sub = int(m.group(2))
            ch_for_p = chapter_for_para(p["idx"], boundaries, body_end)
            if ch_for_p is not None:
                records.append({
                    "chapter": ch,
                    "sub": sub,
                    "wmf_filename": last_drawing[1][0],
                    "drawing_para": last_drawing[0],
                    "label_para": p["idx"],
                })
            last_drawing = None
            continue

        # Reset tracker if any other content intervenes
        if text or wmfs:
            last_drawing = None

    return records


def convert_wmf_batch(wmf_files: set, src_dir: str, dst_dir: str,
                      docker_image: str = "linuxserver/libreoffice:latest") -> dict:
    """Batch-convert WMF files to PNG via Dockerised LibreOffice headless.

    Returns: dict mapping wmf_basename -> png_basename (only successful ones).
    """
    os.makedirs(dst_dir, exist_ok=True)
    todo = []
    result = {}
    for wmf in wmf_files:
        png = wmf[:-4] + ".png"
        out_path = os.path.join(dst_dir, png)
        if os.path.exists(out_path) and os.path.getsize(out_path) > 200:
            result[wmf] = png
            continue
        todo.append(wmf)

    if not todo:
        print(f"   All {len(wmf_files)} WMF→PNG already cached")
        return result

    print(f"   Converting {len(todo)} WMF→PNG via {docker_image} …")
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{src_dir}:/in:ro",
        "-v", f"{dst_dir}:/out",
        docker_image,
        "libreoffice", "--headless", "--convert-to", "png",
        "--outdir", "/out",
    ]
    cmd += [f"/in/{w}" for w in todo]
    env = os.environ.copy()
    env["MSYS_NO_PATHCONV"] = "1"  # Git Bash on Windows path-mangling protection
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env)
    except subprocess.TimeoutExpired:
        print("   ⚠️ Docker conversion timed out")
        return result

    for w in todo:
        png = w[:-4] + ".png"
        if os.path.exists(os.path.join(dst_dir, png)):
            result[w] = png

    failed = len(todo) - (len(result) - sum(1 for w in wmf_files if w in result and w not in todo))
    converted_now = len([w for w in todo if w in result])
    print(f"   ✓ {converted_now}/{len(todo)} converted")

    # CASE-A fix: LibreOffice renders WMF equations into 816x1056 letter-page
    # canvases with the formula occupying only 0.1-0.2% of the area, so a
    # subsequent \includegraphics[height=2em] shrinks the formula to ~1 pixel.
    # Auto-crop every PNG to its non-white bbox.
    try:
        from PIL import Image, ImageOps
        cropped = 0
        for png in result.values():
            p = os.path.join(dst_dir, png)
            if not os.path.exists(p):
                continue
            img = Image.open(p).convert("RGB")
            # full-page-canvas heuristic: ≥ 600x800 with mostly white
            if img.size[0] < 600 or img.size[1] < 600:
                continue  # already a tight image
            bbox = ImageOps.invert(img).getbbox()
            if bbox and (bbox[2] - bbox[0] < img.size[0] * 0.85
                         or bbox[3] - bbox[1] < img.size[1] * 0.85):
                # Add 8 px padding for breathing room
                pad = 8
                W, H = img.size
                bbox = (max(bbox[0] - pad, 0), max(bbox[1] - pad, 0),
                        min(bbox[2] + pad, W), min(bbox[3] + pad, H))
                img.crop(bbox).save(p)
                cropped += 1
        print(f"   ✂  auto-cropped {cropped} oversized canvas PNGs")
    except ImportError:
        print("   ⚠️ Pillow not installed — skipping auto-crop")
    if proc.returncode != 0 and converted_now == 0:
        print(f"   stderr (truncated): {proc.stderr[:500]}")
    return result


def render_equation_block(png_filename: str, ch: int, sub: int,
                          png_path: str = None) -> str:
    """生成 \\begin{equation} 块. D34 fix (2026-05-04): 按 PNG 高宽比自适应高度.

    单行公式 (ratio > 8): height=2em
    一般公式 (ratio 3-8): height=2.6em (历史默认)
    矩阵/多行公式 (ratio 1.5-3): height=4.5em
    很高的多行公式 (ratio < 1.5): height=6em
    始终加 width=\\textwidth + keepaspectratio 兜底, 防止超宽.

    png_path 不传则退回历史 height=2.6em (向后兼容).
    """
    height_em = 2.6
    if png_path:
        try:
            from PIL import Image
            with Image.open(png_path) as im:
                w, h = im.size
                if h > 0:
                    ratio = w / h
                    if ratio < 1.5:
                        height_em = 6.0
                    elif ratio < 3:
                        height_em = 4.5
                    elif ratio < 8:
                        height_em = 2.6
                    else:
                        height_em = 2.0
        except Exception:
            pass
    return (
        "\\begin{equation}\n"
        f"    \\includegraphics[height={height_em}em,width=\\textwidth,keepaspectratio]{{media/{png_filename}}}\n"
        f"    \\tag{{{ch}.{sub}}}\\label{{eq:{ch}.{sub}}}\n"
        "\\end{equation}\n"
    )


def inject_into_chapter(chapter_path: str, records_for_chapter: list,
                        wmf_to_png: dict, report: dict,
                        media_dir: str = None) -> int:
    """注入公式. media_dir 给则 D34 自适应高度按 PNG 实际宽高比."""
    with open(chapter_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    injected = 0
    for rec in records_for_chapter:
        ch = rec["chapter"]
        sub = rec["sub"]
        wmf = rec["wmf_filename"]
        png = wmf_to_png.get(wmf)
        if not png:
            report["skipped_no_png"].append(
                f"  {os.path.basename(chapter_path)}: eq({ch}.{sub}) — WMF→PNG conversion missing")
            continue

        line_re = re.compile(EQ_LINE_PAT_TMPL.format(ch=ch, n=sub))
        replaced = False
        png_path = os.path.join(media_dir, png) if media_dir else None
        for i, line in enumerate(lines):
            if line_re.match(line):
                lines[i] = render_equation_block(png, ch, sub, png_path=png_path)
                injected += 1
                replaced = True
                report["matched"].append(
                    f"  {os.path.basename(chapter_path)}: eq({ch}.{sub}) → line {i+1}")
                break
        if not replaced:
            report["unreferenced"].append(
                f"  {os.path.basename(chapter_path)}: eq({ch}.{sub}) — naked label not found in tex")

    if injected:
        with open(chapter_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    return injected


def main():
    ap = argparse.ArgumentParser(description="Recover Word equations into LaTeX chapters")
    ap.add_argument("--docx", required=True)
    ap.add_argument("--extracted", required=True)
    ap.add_argument("--chapters", required=True)
    ap.add_argument("--media-dir", required=True)
    ap.add_argument("--no-convert", action="store_true",
                    help="Skip Docker WMF→PNG conversion (use cached .png if present)")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    print(f"📖 Reading docx: {args.docx}")
    paras, rid_to_filename = parse_docx(args.docx)
    boundaries, body_end = find_chapter_boundaries(paras)
    print(f"   {len(paras)} paragraphs, {len(boundaries)} chapters detected")

    records = build_equation_records(paras, rid_to_filename, boundaries, body_end)
    print(f"🧮 {len(records)} equation records (WMF + (X.Y) label)")

    if not records:
        print("   No equation records found, nothing to do")
        return 0

    needed_wmf = {r["wmf_filename"] for r in records}
    src_media = os.path.abspath(os.path.join(args.extracted, "media", "media"))
    dst_media = os.path.abspath(args.media_dir)
    print(f"📦 {len(needed_wmf)} unique WMF files needed for equations")

    if args.no_convert:
        wmf_to_png = {}
        for w in needed_wmf:
            png = w[:-4] + ".png"
            if os.path.exists(os.path.join(dst_media, png)):
                wmf_to_png[w] = png
        print(f"   --no-convert: {len(wmf_to_png)}/{len(needed_wmf)} PNGs already cached")
    else:
        wmf_to_png = convert_wmf_batch(needed_wmf, src_media, dst_media)

    by_chapter = defaultdict(list)
    for r in records:
        by_chapter[r["chapter"]].append(r)

    report = {"matched": [], "unreferenced": [], "skipped_no_png": []}
    total_injected = 0
    for ch_num, recs in sorted(by_chapter.items()):
        path = os.path.join(args.chapters, f"ch{ch_num:02d}.tex")
        if not os.path.exists(path):
            continue
        n = inject_into_chapter(path, recs, wmf_to_png, report, media_dir=args.media_dir)
        total_injected += n
        print(f"  ✓ ch{ch_num:02d}.tex: injected {n} equation(s)")

    print()
    print("=" * 60)
    print(f"Result: {total_injected} equations injected, "
          f"{len(report['skipped_no_png'])} skipped (no PNG), "
          f"{len(report['unreferenced'])} unmatched in tex")
    if report["skipped_no_png"]:
        print(f"Skipped (PNG conversion failed):")
        for s in report["skipped_no_png"][:5]:
            print(s)
    if report["unreferenced"]:
        print(f"Unmatched (naked label not found in tex):")
        for u in report["unreferenced"][:5]:
            print(u)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump({
                "total_injected": total_injected,
                "matched": report["matched"],
                "unreferenced": report["unreferenced"],
                "skipped_no_png": report["skipped_no_png"],
            }, f, ensure_ascii=False, indent=2)
        print(f"📝 Report: {args.report}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
