"""tests/test_product_audit.py — Round 6 product_audit.py fixture suite.

四个 fixture 验证 Check 1/2/3 的边界 + 全绿场景.
"""
import os
import sys

# Resolve scripts/ path
THIS = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(THIS, "..", "scripts"))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import product_audit  # noqa: E402


# ============================================================
# Fixture builders
# ============================================================

def _build_workdir(tmp_path, *, media_files=(), chapters=None, misc=None, log_text=""):
    """构造一个 mock DissertationUESTC workdir."""
    work = tmp_path / "DissertationUESTC"
    work.mkdir()
    (work / "media").mkdir()
    (work / "chapter").mkdir()
    (work / "misc").mkdir()

    for fname in media_files:
        (work / "media" / fname).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    for fname, content in (chapters or {}).items():
        (work / "chapter" / fname).write_text(content, encoding="utf-8")

    for fname, content in (misc or {}).items():
        (work / "misc" / fname).write_text(content, encoding="utf-8")

    (work / "main.log").write_text(log_text, encoding="utf-8")
    return str(work)


# ============================================================
# Fixture 1: 媒体未引用 → P0 hard fail
# ============================================================

def test_fixture1_unreferenced_media_fails(tmp_path):
    """media/ 5 张, chapter 只引 image2 → unreferenced 含 image3/4/5 (image1 在白名单)"""
    workdir = _build_workdir(
        tmp_path,
        media_files=["image1.png", "image2.png", "image3.png", "image4.png", "image5.png"],
        chapters={"ch01.tex": r"\includegraphics[width=0.7\textwidth]{media/image2.png}"},
    )
    passed, lines = product_audit.check_media_integrity(workdir, "")
    assert not passed, "应当因 unreferenced > 1 失败"
    text = "\n".join(lines)
    assert "image3.png" in text
    assert "image4.png" in text
    assert "image5.png" in text
    # image1 被允许集吸收, 不应在 ❌ 行
    assert "❌" in text


# ============================================================
# Fixture 2: LaTeX log multiply defined → P0 hard fail
# ============================================================

def test_fixture2_multiply_defined_fails(tmp_path):
    log = (
        "Some preamble\n"
        "LaTeX Warning: Label `fig:3.4' multiply defined.\n"
        "More text\n"
        "LaTeX Warning: Label `fig:3.5' multiply defined.\n"
    )
    workdir = _build_workdir(tmp_path, log_text=log)
    passed, lines = product_audit.check_latex_log(workdir)
    assert not passed
    text = "\n".join(lines)
    assert "multiply-defined labels" in text
    assert "fig:3.4" in text
    assert "fig:3.5" in text


def test_fixture2_undefined_cite_fails(tmp_path):
    log = (
        "Package natbib Warning: Citation `tummalarr2005' on page 1 undefined on input line 7.\n"
        "Package natbib Warning: Citation `ipc1998' on page 25 undefined on input line 179.\n"
    )
    workdir = _build_workdir(tmp_path, log_text=log)
    passed, lines = product_audit.check_latex_log(workdir)
    assert not passed
    text = "\n".join(lines)
    assert "undefined citations" in text
    assert "tummalarr2005" in text


# ============================================================
# Fixture 3: 占位符 → P1 warn (不阻断)
# ============================================================

def test_fixture3_placeholders_warn_not_block(tmp_path):
    workdir = _build_workdir(
        tmp_path,
        misc={
            "acknowledgement.tex": "本论文的工作是在我的导师XX老师指导下完成的，……",
            "conclusion.tex": "本研究的下一步TODO待补充",
        },
    )
    passed, lines = product_audit.check_placeholders(workdir)
    # Check3 永远 passed=True (不阻断)
    assert passed
    text = "\n".join(lines)
    assert "XX老师" in text or "XX占位" in text
    assert "TODO" in text or "占位短词" in text
    # 至少 3 处命中 (XX老师 / …… / TODO)
    assert text.count("⚠️") >= 3


# ============================================================
# Fixture 4: 全绿 case
# ============================================================

def test_fixture4_clean_case_passes(tmp_path):
    """所有 media 都被引用, main.log 无 warning, 无占位符"""
    workdir = _build_workdir(
        tmp_path,
        media_files=["image1.png", "image2.png", "image3.png"],
        chapters={
            "ch01.tex": (
                r"\includegraphics{media/image2.png}" "\n"
                r"\includegraphics{media/image3.png}" "\n"
            ),
        },
        misc={"acknowledgement.tex": "感谢导师陈教授的悉心指导。"},
        log_text="LaTeX Font Info: Some normal info.\nNo errors.\n",
    )
    overall, report = product_audit.run_product_audit(workdir, "")
    assert overall, f"clean fixture should pass; got:\n{report}"
    assert "✅ 产物审计通过" in report


# ============================================================
# Sanity: dangling reference detection
# ============================================================

def test_dangling_reference_fails(tmp_path):
    """\\includegraphics 指向不存在的 media 文件 → ❌"""
    workdir = _build_workdir(
        tmp_path,
        media_files=["image1.png"],
        chapters={"ch01.tex": r"\includegraphics{media/nonexistent.png}"},
    )
    passed, lines = product_audit.check_media_integrity(workdir, "")
    assert not passed
    text = "\n".join(lines)
    assert "dangling" in text.lower() or "nonexistent.png" in text


# ============================================================
# Round 7-C: Check 4-7 fixture
# ============================================================

import json


def _build_extracted(tmp_path, *, abstract_zh="", abstract_en="", cite_map=None):
    """构造 mock extracted/ 目录."""
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    if abstract_zh:
        (extracted / "abstract_zh.txt").write_text(abstract_zh, encoding="utf-8")
    if abstract_en:
        (extracted / "abstract_en.txt").write_text(abstract_en, encoding="utf-8")
    if cite_map is not None:
        (extracted / "cite_map.json").write_text(
            json.dumps(cite_map, ensure_ascii=False), encoding="utf-8"
        )
    return str(extracted)


# ============================================================
# Check 4: 摘要长度 parity helper
# ============================================================

def test_check4_extracted_abstract_strips_keywords(tmp_path):
    """_read_extracted_abstract 应去掉关键词段."""
    extracted = _build_extracted(
        tmp_path,
        abstract_zh="这是摘要正文。\n\n关键词:玻璃，介电性能",
    )
    body = product_audit._read_extracted_abstract(extracted, "zh")
    assert "摘要正文" in body
    assert "关键词" not in body


def test_check4_extracted_abstract_handles_missing(tmp_path):
    """文件不存在 → 返回空串, 不崩."""
    extracted = str(tmp_path / "no_extracted")
    body = product_audit._read_extracted_abstract(extracted, "zh")
    assert body == ""


# ============================================================
# Check 5: bbl 顺序 vs cite_map
# ============================================================

def test_check5_bbl_order_match(tmp_path):
    """bbl 顺序 = cite_map 1..N → ✅"""
    workdir = _build_workdir(tmp_path)
    bbl_text = (
        "\\begin{thebibliography}{10}\n"
        "\\bibitem{tummalarr2005}\nFirst entry.\n"
        "\\bibitem{sunypengyzhangyetal2022}\nSecond entry.\n"
        "\\bibitem{kimjmparksyleehs2021}\nThird entry.\n"
        "\\end{thebibliography}\n"
    )
    (tmp_path / "DissertationUESTC" / "main.bbl").write_text(bbl_text, encoding="utf-8")
    extracted = _build_extracted(
        tmp_path,
        cite_map={
            "1": "tummalarr2005",
            "2": "sunypengyzhangyetal2022",
            "3": "kimjmparksyleehs2021",
        },
    )
    passed, lines = product_audit.check_bbl_order(workdir, extracted)
    assert passed, f"应通过, 实际: {lines}"


def test_check5_bbl_order_mismatch(tmp_path):
    """bbl 顺序 ≠ cite_map (D24 \\nocite{*} 字典序) → ❌"""
    workdir = _build_workdir(tmp_path)
    bbl_text = (
        "\\bibitem{ipc1998}\n"
        "\\bibitem{tummalarr2005}\n"
        "\\bibitem{sunypengyzhangyetal2022}\n"
    )
    (tmp_path / "DissertationUESTC" / "main.bbl").write_text(bbl_text, encoding="utf-8")
    extracted = _build_extracted(
        tmp_path,
        cite_map={
            "1": "tummalarr2005",
            "2": "sunypengyzhangyetal2022",
            "3": "ipc1998",
        },
    )
    passed, lines = product_audit.check_bbl_order(workdir, extracted)
    assert not passed
    text = "\n".join(lines)
    assert "顺序错位" in text
    assert "D24" in text


def test_check5_bbl_count_mismatch(tmp_path):
    """bbl 条数 ≠ cite_map 条数 → ❌ (refs_to_bib 漏条目)"""
    workdir = _build_workdir(tmp_path)
    (tmp_path / "DissertationUESTC" / "main.bbl").write_text(
        "\\bibitem{a}\n\\bibitem{b}\n", encoding="utf-8"
    )
    extracted = _build_extracted(
        tmp_path, cite_map={"1": "a", "2": "b", "3": "c"}
    )
    passed, lines = product_audit.check_bbl_order(workdir, extracted)
    assert not passed
    text = "\n".join(lines)
    assert "条数不一致" in text


# ============================================================
# Check 7: PDF 残留字样 (regex 直接测)
# ============================================================

def test_check7_artifact_pattern_cls_reminder():
    """CLS reminder 字样应被检测."""
    sample = "Some text\nThe length of the Chinese Abstract has exceeded the maximum limit of 1 page(s).\nMore."
    for name, pat, is_hard in product_audit.PDF_ARTIFACT_PATTERNS:
        if name == "CLS reminder":
            assert pat.search(sample), f"{name} 应命中"
            assert is_hard


def test_check7_artifact_pattern_latex_command_residue():
    """\\textsuperscript{ 字面残留应被检测."""
    sample = "Result is \\textsuperscript{[15]} which is wrong"
    for name, pat, is_hard in product_audit.PDF_ARTIFACT_PATTERNS:
        if name == "LaTeX 残留":
            assert pat.search(sample), f"{name} 应命中"


def test_check7_artifact_pattern_clean():
    """正常 PDF 文本不应触发任何 pattern."""
    sample = "本研究在第三章提出了新方法[15], 实验验证了其有效性。"
    hit = False
    for name, pat, is_hard in product_audit.PDF_ARTIFACT_PATTERNS:
        if pat.search(sample):
            hit = True
            print(f"unexpected hit: {name}")
    assert not hit


# ============================================================
# D38 (CASE-A): Check 8 figure-order parity
# ============================================================

def test_d38_pdf_order_helper(tmp_path):
    """_pdf_includegraphics_order 按 chapter 文件名字典序遍历 + tex 出现顺序."""
    work = tmp_path / "DissertationUESTC"
    chap = work / "chapter"
    chap.mkdir(parents=True)
    (chap / "ch01.tex").write_text(
        r"\includegraphics[width=0.7\textwidth]{media/imageA.png}" + "\n"
        r"\includegraphics{media/imageB.jpeg}" + "\n",
        encoding="utf-8",
    )
    (chap / "ch02.tex").write_text(
        r"\includegraphics[width=0.5\textwidth]{media/imageC.png}" + "\n",
        encoding="utf-8",
    )
    out = product_audit._pdf_includegraphics_order(str(work))
    assert out == ["imageA.png", "imageB.jpeg", "imageC.png"]


def test_d38_check_figure_order_skips_when_no_docx(tmp_path):
    """无 --docx 时 skip, 不阻断."""
    work = tmp_path / "DissertationUESTC"
    (work / "chapter").mkdir(parents=True)
    ok, lines = product_audit.check_figure_order(str(work), "")
    assert ok
    assert any("跳过" in l for l in lines)


def test_d38_check_figure_order_skips_when_no_includegraphics(tmp_path):
    """chapter 无 \\includegraphics → skip, 不阻断."""
    work = tmp_path / "DissertationUESTC"
    chap = work / "chapter"
    chap.mkdir(parents=True)
    (chap / "ch01.tex").write_text(r"\section{Empty}", encoding="utf-8")
    # docx_path 给个空文件 (parse 失败), 也走 skip 分支
    fake_docx = tmp_path / "x.docx"
    fake_docx.write_bytes(b"")
    ok, lines = product_audit.check_figure_order(str(work), str(fake_docx))
    assert ok


def test_d38_recover_figures_in_place_preserves_order(tmp_path):
    """recover_figures 应在 caption-only 行原位插图块, 保留 docx 体内顺序."""
    sys.path.insert(0, SCRIPTS)
    import recover_figures as rf

    chapter_path = tmp_path / "ch03.tex"
    chapter_path.write_text(
        "\\section{Intro}\n"
        "首段文字, 介绍背景.\n"
        "图3-1 第一张图\n"
        "中间段落 A.\n"
        "图3-2 第二张图\n"
        "中间段落 B.\n"
        "图3-9 第九张图\n"
        "结尾.\n",
        encoding="utf-8",
    )
    records = [
        {"drawing_para": 0, "image_filenames": ["image2.png"],
         "caption_para": 1, "caption_text": "第一张图",
         "caption_chapter": 3, "caption_subnum": 1, "chapter": 3},
        {"drawing_para": 2, "image_filenames": ["image3.png"],
         "caption_para": 3, "caption_text": "第二张图",
         "caption_chapter": 3, "caption_subnum": 2, "chapter": 3},
        {"drawing_para": 4, "image_filenames": ["image10.png"],
         "caption_para": 5, "caption_text": "第九张图",
         "caption_chapter": 3, "caption_subnum": 9, "chapter": 3},
    ]
    report = {"matched": [], "unreferenced": [], "warnings": []}
    n = rf.inject_into_chapter(str(chapter_path), records, report)
    assert n == 3
    out = chapter_path.read_text(encoding="utf-8")
    # 顺序应是 image2 → image3 → image10 (与 caption_subnum 一致)
    p2 = out.find("media/image2.png")
    p3 = out.find("media/image3.png")
    p10 = out.find("media/image10.png")
    assert p2 != -1 and p3 != -1 and p10 != -1
    assert p2 < p3 < p10, (
        f"图序错乱: image2@{p2} image3@{p3} image10@{p10}"
    )
    # caption-only 行已被替换 (不应再剩裸 "图3-1" 段落)
    assert "\n图3-1 第一张图\n" not in out
    assert "\n图3-2 第二张图\n" not in out
    assert "\n图3-9 第九张图\n" not in out


def test_d38_recover_figures_fallback_when_no_caption_anchor(tmp_path):
    """若 chapter .tex 中无 caption-only 行 → fallback (inline ref / append at end), 按 subnum 排序."""
    sys.path.insert(0, SCRIPTS)
    import recover_figures as rf

    chapter_path = tmp_path / "ch04.tex"
    chapter_path.write_text(
        "\\section{Intro}\n"
        "完整段落, 无 caption-only 行.\n"
        "再来一段普通文字.\n",
        encoding="utf-8",
    )
    records = [
        {"drawing_para": 0, "image_filenames": ["image20.png"],
         "caption_para": 1, "caption_text": "图四标题",
         "caption_chapter": 4, "caption_subnum": 1, "chapter": 4},
        {"drawing_para": 2, "image_filenames": ["image21.png"],
         "caption_para": 3, "caption_text": "图五标题",
         "caption_chapter": 4, "caption_subnum": 2, "chapter": 4},
    ]
    report = {"matched": [], "unreferenced": [], "warnings": []}
    n = rf.inject_into_chapter(str(chapter_path), records, report)
    assert n == 2
    out = chapter_path.read_text(encoding="utf-8")
    p20 = out.find("media/image20.png")
    p21 = out.find("media/image21.png")
    assert p20 < p21, "fallback append 必须按 subnum 顺序"


# ============================================================
# Integration: 跑 v10 真实 PDF 全 7 项 (skip if not exist)
# ============================================================

def test_integration_v10_full_audit_passes():
    """CASE-A v10 PDF 存在时, 跑 Check 1-7 期望全绿.

    Check 8 (D38 figure-order, CASE-A 新增) 不强制 v10 通过 — v10 是冻结交付产物,
    含 case-private 手编辑 (v11 救火: 图片宽度调整 + ch03 表3-1 重排) + 旧版
    recover_figures placement bug. 重跑会破坏现状, 仅校验 Check 1-7.
    """
    repo = os.environ.get("THESIS_REPO_ROOT", "")
    workdir = os.path.join(repo, "work", "output_012", "DissertationUESTC")
    docx = os.path.join(repo, "work", "新case.docx")
    extracted = os.path.join(repo, "work", "output_012", "extracted")
    if not os.path.isdir(workdir) or not os.path.isfile(os.path.join(workdir, "main.pdf")):
        import pytest
        pytest.skip("CASE-A v10 PDF 不存在, 跳过集成测试")

    p1, _ = product_audit.check_media_integrity(workdir, docx)
    p2, _ = product_audit.check_latex_log(workdir)
    p4, _ = product_audit.check_abstract_parity(workdir, extracted)
    p5, _ = product_audit.check_bbl_order(workdir, extracted)
    p6, _ = product_audit.check_cite_superscript(workdir)
    p7, _ = product_audit.check_pdf_artifacts(workdir)
    assert all([p1, p2, p4, p5, p6, p7]), (
        f"v10 Check 1-7 应全绿, 实际: 1={p1} 2={p2} 4={p4} 5={p5} 6={p6} 7={p7}"
    )
