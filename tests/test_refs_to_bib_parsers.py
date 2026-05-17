"""tests/test_refs_to_bib_parsers.py — Round 7 阶段 B.

回归覆盖本会话 (CASE-A v6→v10) shared 修的 6 个 parser bug:
- D22: template_adapter.escape_latex_specials_in_prose (摘要 % 转义)
- D23: refs_to_bib parse_proceedings ([C]) / parse_standard ([S])
- D-vol: parse_article 优先匹配 volume(number) 模式
- D-vol-no-paren: parse_article m_n 强制要括号 (单数字 → volume 不是 number)
- D-book-pg: parse_book 解析尾部页码
- D-thesis-pg: parse_thesis 解析尾部页码

任何后续修改 refs_to_bib.py 必须保证这些测试通过.
"""
import os
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.normpath(os.path.join(THIS, ".."))
SCRIPTS = os.path.join(SKILL_DIR, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import refs_to_bib  # noqa: E402
import template_adapter  # noqa: E402


# ============================================================
# D22: escape_latex_specials_in_prose (摘要 % 转义)
# ============================================================

def test_d22_escape_percent_basic():
    """0%~3% 中两处 % 都被转义. Round 8 D26: ~ 也变 \\textasciitilde{} 显示字面波浪号."""
    out = template_adapter.escape_latex_specials_in_prose("在 0%~3% 区间")
    assert "0\\%" in out
    assert "3\\%" in out
    assert "\\textasciitilde{}" in out  # D26 升 shared 后


def test_d22_escape_does_not_double():
    """已转义的 \\% 不被再次 escape 成 \\\\%."""
    out = template_adapter.escape_latex_specials_in_prose("已转义 \\% 测试")
    assert "\\\\%" not in out
    assert "\\%" in out


def test_d22_escape_other_specials():
    """% & # $ _ 都转义, ~ 转 \\textasciitilde{} (D26), ^ 保留 (Unicode 上标客户期望)."""
    out = template_adapter.escape_latex_specials_in_prose("a&b #c $d _e ~f ^g")
    assert "\\&" in out
    assert "\\#" in out
    assert "\\$" in out
    assert "\\_" in out
    assert "\\textasciitilde{}" in out  # D26 升 shared
    assert "^g" in out  # ^ 保留


# ============================================================
# D23: parse_proceedings [C] 会议
# ============================================================

def test_d23_parse_proceedings_basic():
    """Tummala R R. Title[C]. Conf, 2005, 3-7. → @inproceedings 含 booktitle/year/pages."""
    text = "Tummala R R. Packaging: Past, present and future[C]. 6th International Conference on Electronic Packaging Technology,2005,3-7."
    bib, warning = refs_to_bib.parse_proceedings(text, "tummalarr2005")
    assert warning is None
    assert "@inproceedings{tummalarr2005" in bib
    assert "booktitle = {6th International Conference on Electronic Packaging Technology}" in bib
    assert "year = {2005}" in bib
    assert "pages = {3-7}" in bib


def test_d23_parse_proceedings_pages_required():
    """BST DissertUESTC-bachelor.bst 强制要 pages, 即使原文没页码也占位 '1'."""
    text = "Some Author. Title[C]. Some Conf, 2020."
    bib, warning = refs_to_bib.parse_proceedings(text, "test_pages")
    assert warning is None
    assert "pages = {1}" in bib  # 占位防 BST "missing not a string"


# ============================================================
# D23: parse_standard [S] 标准
# ============================================================

def test_d23_parse_standard_basic():
    """委员会(SAC/TC 178). GB/T 28209-2023[S]. 北京: 出版社, 2023. → @misc + note."""
    text = "全国玻璃仪器标准化技术委员会(SAC/TC 178). 硼硅酸盐玻璃化学分析方法: GB/T 28209-2023[S]. 北京:中国标准出版社,2023."
    bib, warning = refs_to_bib.parse_standard(text, "r2820")
    assert warning is None
    assert "@misc{r2820" in bib
    assert "note = {[S] 标准}" in bib
    assert "year = {2023}" in bib


# ============================================================
# D-vol: parse_article 优先匹配 volume(number) 模式
# ============================================================

def test_dvol_parse_article_volume_number():
    """Y, V(N): P → volume + number 都正确拆出."""
    text = "Shannon R D. Dielectric polarizabilities of ions in oxides and fluorides[J]. Journal of Applied Physics,1993,73(1):348-366."
    bib, warning = refs_to_bib.parse_article(text, "shannonrd1993")
    assert warning is None
    assert "volume = {73}" in bib
    assert "number = {1}" in bib
    assert "pages = {348-366}" in bib


def test_dvol_parse_article_priority():
    """优先级测试: 期刊 '2022, 33(15): 11847-11865' volume=33 不能被吃成 number=33."""
    text = "Sun Y, et al. Title[J]. Journal,2022,33(15):11847-11865."
    bib, warning = refs_to_bib.parse_article(text, "sun2022")
    assert warning is None
    assert "volume = {33}" in bib
    assert "number = {15}" in bib


# ============================================================
# D-vol-no-paren: 单数字 = volume 不是 number
# ============================================================

def test_dvol_no_paren_single_number_is_volume():
    """1987, 95: 45-60 → volume=95 (无括号 = no number)."""
    text = "Bray P J. NMR studies of the structure of glasses[J]. Journal of Non-Crystalline Solids,1987,95:45-60."
    bib, warning = refs_to_bib.parse_article(text, "braypj1987")
    assert warning is None
    assert "volume = {95}" in bib
    assert "number" not in bib  # 不应有 number 字段


def test_dvol_no_paren_volume_447():
    """2016, 447: 283-289 → volume=447 (常见期刊不连卷格式)."""
    text = "Dhara A, et al. Title[J]. Journal,2016,447:283-289."
    bib, warning = refs_to_bib.parse_article(text, "dhara2016")
    assert warning is None
    assert "volume = {447}" in bib


def test_dvol_no_paren_paren_required_for_number():
    """带括号才认为是 number (期刊有 issue 没卷号, 罕见但允许)."""
    text = "Test. Title[J]. Journal,2020,(15):100-200."
    bib, warning = refs_to_bib.parse_article(text, "test_n_only")
    assert warning is None
    assert "number = {15}" in bib
    assert "volume" not in bib


# ============================================================
# D-book-pg: parse_book 尾部页码
# ============================================================

def test_dbook_pg_parse_book_pages():
    """林宗寿. 无机非金属材料学[M]. 武汉:出版社, 2008, 120-135. → pages 字段."""
    text = "林宗寿. 无机非金属材料学[M]. 武汉:武汉理工大学出版社,2008,120-135."
    bib, warning = refs_to_bib.parse_book(text, "lin2008")
    assert warning is None
    assert "pages = {120-135}" in bib
    assert "year = {2008}" in bib


def test_dbook_pg_no_pages_still_works():
    """没页码的著作仍能解析, 只是无 pages 字段."""
    text = "Shelby J E. Introduction to Glass Science and Technology[M]. Cambridge:Royal Society of Chemistry,2005."
    bib, warning = refs_to_bib.parse_book(text, "shelbyje2005")
    assert warning is None
    assert "year = {2005}" in bib
    assert "pages" not in bib


# ============================================================
# D-thesis-pg: parse_thesis 尾部页码
# ============================================================

def test_dthesis_pg_parse_thesis_single_range():
    """梁天鹏[D]. 成都:电子科技大学, 2021, 1-15. → pages 字段."""
    text = "梁天鹏. 低损耗可光刻玻璃及通孔技术研究[D]. 成都:电子科技大学,2021,1-15."
    bib, warning = refs_to_bib.parse_thesis(text, "liang2021")
    assert warning is None
    assert "pages = {1-15}" in bib


def test_dthesis_pg_parse_thesis_two_ranges():
    """张三[D]. 杭州:浙江大学, 2007, 45-49, 51-56. → 含两段页码."""
    text = "张三. 示例研究主题[D]. 杭州:浙江大学,2007,45-49, 51-56."
    bib, warning = refs_to_bib.parse_thesis(text, "zhangsan2007")
    assert warning is None
    assert "45-49" in bib
    assert "51-56" in bib


# ============================================================
# D-thesis-address: SCHOOL_TO_CITY 自动补 address
# 防 lun51 "缺少出版年, 或者出版者和出版年未用逗号分隔" 严重错误.
# ============================================================

def test_dthesis_address_auto_inject_from_school():
    """[D]. 北京邮电大学,2019. → address={北京} 由 SCHOOL_TO_CITY 推断."""
    text = "李四. 示例研究主题[D]. 北京邮电大学,2019."
    bib, warning = refs_to_bib.parse_thesis(text, "lisi2019")
    assert warning is None
    assert "school = {北京邮电大学}" in bib
    assert "address = {北京}" in bib


def test_dthesis_address_pla_info_eng():
    """解放军信息工程大学 → 郑州 (SCHOOL_TO_CITY fallback)."""
    text = "王五. 示例研究主题[D]. 解放军信息工程大学,2013."
    bib, _ = refs_to_bib.parse_thesis(text, "wangwu2013")
    assert "address = {郑州}" in bib


def test_dthesis_address_explicit_respected():
    """客户显式写出版地 '成都:电子科技大学' → 尊重客户 address, 不查表."""
    text = "赵六. 示例研究主题[D]. 成都:电子科技大学,2018."
    bib, _ = refs_to_bib.parse_thesis(text, "zhaoliu2018")
    assert "address = {成都}" in bib
    assert "school = {电子科技大学}" in bib


def test_dthesis_address_unknown_school_no_inject():
    """未知学校不强造城市, 留空让 BST warn 但不渲染错误地名."""
    text = "某人. 某课题研究[D]. 不存在的虚构大学,2020."
    bib, _ = refs_to_bib.parse_thesis(text, "unknown2020")
    assert "school = {不存在的虚构大学}" in bib
    # 未知学校 → 不应注入 address (避免假城市)
    assert "address" not in bib


def test_dthesis_existing_pg_test_still_passes():
    """回归: 显式 address+pages 形式 (双段页码) 仍正确."""
    text = "张三. 示例研究主题[D]. 杭州:浙江大学,2007,45-49, 51-56."
    bib, _ = refs_to_bib.parse_thesis(text, "zhangsan2007")
    assert "address = {杭州}" in bib
    assert "school = {浙江大学}" in bib
    assert "45-49" in bib
    assert "51-56" in bib


# ============================================================
# CASE-A round 4 lun51 fix — IEEE_FALLBACK 补类型标识 [C]/[J]
# 防 lun51 "没有找到参考文献类型标识" 提醒 (#163, 171, 173, 189, 191).
# 因 IEEE_FALLBACK 不走 parse_*, 这里靠 main() 入口或单独 helper 测.
# 这些测通过把 entry_text 喂 main loop 路径外的 IEEE 启发式片段实现.
# ============================================================

import io
import os
import tempfile


def _run_refs_main(raw_lines: list[str]) -> str:
    """Helper: run refs_to_bib.main on a temp file, return generated .bib content."""
    with tempfile.TemporaryDirectory() as td:
        inp = os.path.join(td, "raw.txt")
        out = os.path.join(td, "out.bib")
        with open(inp, "w", encoding="utf-8") as f:
            f.write("\n".join(raw_lines) + "\n")
        import sys
        old_argv = sys.argv
        sys.argv = ["refs_to_bib.py", "--input", inp, "--output", out]
        try:
            refs_to_bib.main()
        finally:
            sys.argv = old_argv
        with open(out, "r", encoding="utf-8") as f:
            return f.read()


def test_ieee_fallback_conference_gets_C_tag():
    """[4] IEEE Conference 字样 → title 末尾补 [C]."""
    bib = _run_refs_main([
        '[4]A. Zaeemzadeh, M. Joneidi, B. Shahrasbi. "Robust Target Localization Based on Squared Range Iterative Reweighted Least Squares," 2017 IEEE 14th International Conference on Mobile Ad Hoc Sensor Systems, 2017.'
    ])
    assert "[C]" in bib, f"expected [C] tag in:\n{bib}"
    assert "@misc{" in bib  # IEEE_FALLBACK still uses @misc


def test_ieee_fallback_journal_gets_J_tag():
    """[10] IEEE Transactions 字样 → title 末尾补 [J]."""
    bib = _run_refs_main([
        '[10]W. Xiong, S. Mohanty. "Convex Relaxation Approaches to Robust RSS-TOA Based Source Localization," IEEE Transactions on Vehicular Technology, vol. 72, no. 8, 2023.'
    ])
    assert "[J]" in bib, f"expected [J] tag in:\n{bib}"


def test_ieee_fallback_generic_gets_N_tag():
    """无明显期刊/会议线索 → 兜底 [N]."""
    bib = _run_refs_main([
        '[27]K. W. Cheung, W. K. Ma. "Accurateapproximation algorithm for TOA-based maximum likelihood mobile location", Proc. ICASSP, vol. 2, pp. 145-148, 2004.'
    ])
    # ICASSP triggers Conference logic → [C]
    assert "[C]" in bib  # ICASSP 是 conference proceeding


def test_ieee_fallback_strips_trailing_comma_in_title():
    """title 末尾尾随 ',' (lun51 #163 '出现连续标点') 应被 strip."""
    bib = _run_refs_main([
        '[10]Author X. "Some Long Title with trailing comma," IEEE Transactions, 2023.'
    ])
    # title 应不含 ',[J]' 模式 (即 title 被 strip 后再加 tag)
    assert ",[J]" not in bib
    assert ",[C]" not in bib
    assert ", [J]" not in bib
    # title{ ... }[J/C] 前一字符不能是 ','
    import re
    m = re.search(r"title = \{([^}]+)\}", bib)
    assert m, "no title field found"
    title_val = m.group(1)
    # tag 紧跟标题, tag 之前不能是 ','
    assert not re.search(r",\s*\[[CJN]\]$", title_val), f"title still has trailing comma: {title_val}"


# ============================================================
# Round 8 阶段 C — 8 个 D24-D31 升 shared 后的回归 fixture
# ============================================================

import refs_to_bib  # noqa: E402


def test_d25_western_author_normalized():
    """D25 shared: 'Sun Y' 等空格分隔西文作者 → 'Sun, Y.' 让 BST 正确识别."""
    out = refs_to_bib.sanitize_author_list("Sun Y, Peng Y, Zhang Y, et al")
    assert "Sun, Y." in out
    assert "Peng, Y." in out
    assert "Zhang, Y." in out
    assert "others" in out  # et al 转 others


def test_d25_chinese_author_unchanged():
    """中文人名(无括号)不应被改: '梁天鹏' 原样."""
    out = refs_to_bib.sanitize_author_list("梁天鹏")
    assert out == "梁天鹏"


def test_d25_western_double_initial():
    """'Lee Y K' → 'Lee, Y. K.' (双 initial)."""
    out = refs_to_bib.sanitize_author_list("Lee Y K")
    assert "Lee, Y. K." in out


def test_d29_title_protected_from_sentence_case():
    """D29 shared: ref.bib title 整体加 {} 防 BST 小写化化学式."""
    raw = "@article{x,\n  title = {Sb2O3 effect},\n}\n"
    out = refs_to_bib.postprocess_bib_for_render(raw)
    # title 内容应被双花括号包: 输出形如 "title = {{Sb2O3 effect}}"
    assert "{{Sb2O3 effect}}" in out


def test_d29_title_protected_content_preserved():
    """title 包后内容应保留, 不丢字符."""
    raw = "@article{x,\n  title = {Already protected},\n}\n"
    out = refs_to_bib.postprocess_bib_for_render(raw)
    # 内容必须在 (无论包成 {{...}} 还是 {{{...}}}, BST 行为一致)
    assert "Already protected" in out


def test_d30_publisher_amp_escaped():
    """D30 shared: publisher 字段裸 & → \\&"""
    raw = "@book{x,\n  publisher = {John Wiley & Sons},\n}\n"
    out = refs_to_bib.postprocess_bib_for_render(raw)
    assert "John Wiley \\& Sons" in out


def test_d30_journal_amp_escaped():
    """D30: journal 字段同样 & 转义."""
    raw = "@article{x,\n  journal = {Foo & Bar Journal},\n}\n"
    out = refs_to_bib.postprocess_bib_for_render(raw)
    assert "Foo \\& Bar Journal" in out


def test_d30_already_escaped_not_doubled():
    """已 \\& 不应变 \\\\&"""
    raw = "@book{x,\n  publisher = {Already \\& Escaped},\n}\n"
    out = refs_to_bib.postprocess_bib_for_render(raw)
    assert "\\\\&" not in out


def test_d31_chinese_org_with_paren_wrapped():
    """D31 shared: 中文机构含 () 自动加 {} 防 BST 拆为 first/last 名."""
    out = refs_to_bib.sanitize_author_list("全国玻璃仪器标准化技术委员会(SAC/TC 178)")
    assert out.startswith("{") and out.endswith("}")
    assert "全国玻璃" in out


def test_d31_chinese_person_no_paren_unchanged():
    """中文人名不含 () 不动."""
    out = refs_to_bib.sanitize_author_list("张三")
    assert out == "张三"


# ============================================================
# CASE-A — D23 expansion + D34 + D35
# ============================================================

def test_d23_expansion_proceedings_double_slash():
    """D23 expansion (CASE-A): GB/T 7714 标准会议格式 [C]//<Conf>. <Year>: <Pages>.

    7/9 references in CASE-A use this form (CVPR/ICCV/IAPR/...).
    Old D23 fix only covered '[C].' bare-dot form.
    """
    text = "Li D, Chen X, Huang K. Multi-attribute Learning for Pedestrian Attribute Recognition[C]//2015 3rd IAPR Asian Conference on Pattern Recognition. 2015: 111-115."
    bib, warning = refs_to_bib.parse_proceedings(text, "lidchenxhuangk2015")
    assert warning is None
    assert "@inproceedings{lidchenxhuangk2015" in bib
    assert "booktitle = {2015 3rd IAPR Asian Conference on Pattern Recognition}" in bib
    assert "year = {2015}" in bib
    assert "pages = {111-115}" in bib


def test_d23_expansion_proceedings_year_only():
    """[C]//Conf. 2011. — 末尾仅 year 无 pages → pages 占位 1."""
    text = "Bourdev L, Maji S. Title[C]//Proceedings of the IEEE International Conference on Computer Vision. 2011."
    bib, warning = refs_to_bib.parse_proceedings(text, "bourdev2011")
    assert warning is None
    assert "year = {2011}" in bib
    assert "pages = {1}" in bib  # 占位


def test_d23_expansion_proceedings_falls_back_to_dot():
    """[C]. bare-dot form (D23 原版) 仍工作 — 兜底未破坏."""
    text = "Tummala R R. Title[C]. 6th International Conference, 2005, 3-7."
    bib, warning = refs_to_bib.parse_proceedings(text, "tummala2005")
    assert warning is None
    assert "@inproceedings{tummala2005" in bib
    assert "year = {2005}" in bib
    assert "pages = {3-7}" in bib


# ============================================================
# D34 — parse_electronic [EB/OL]
# ============================================================

def test_d34_parse_electronic_no_url():
    """[EB/OL] 不含 URL — 仍生成 @misc, [EB/OL] inline 进 title (CASE-A)."""
    text = "ULTRALYTICS. YOLOv8: Ultralytics YOLO Documentation[EB/OL]. 2023."
    bib, warning = refs_to_bib.parse_electronic(text, "ultralytics2023")
    assert warning is None
    assert "@misc{ultralytics2023" in bib
    # CASE-A: [EB/OL] inlined into title (was a trailing note before).
    assert "title = {YOLOv8: Ultralytics YOLO Documentation[EB/OL]}" in bib
    assert "year = {2023}" in bib
    # No "电子资源" trailing gloss (CASE-A): keep refs aligned with docx.
    assert "电子资源" not in bib


def test_d34_parse_electronic_with_url():
    """[EB/OL] 含 URL — 提取到 howpublished=\\url{...}."""
    text = "Author. Title[EB/OL]. 2024. https://example.com/page.html."
    bib, warning = refs_to_bib.parse_electronic(text, "author2024")
    assert warning is None
    assert "year = {2024}" in bib
    assert "\\url{https://example.com/page.html}" in bib


# CASE-A: arxiv ID / DOI digits in URL must not be picked up as year
def test_case_anon_arxiv_id_not_year():
    """arxiv URL 'abs/2207.02696' contains 4-digit substring '2207' which
    must NOT override the real year that follows the URL."""
    text = ("C.-Y.Wang.YOLOv7[EB/OL].https://arxiv.org/abs/2207.02696,"
            "July 6,2022")
    bib, warning = refs_to_bib.parse_electronic(text, "wang2022")
    assert warning is None
    assert "year = {2022}" in bib
    assert "year = {2207}" not in bib


def test_case_anon_doi_digits_not_year():
    """DOI URL '10.48550/arXiv.1704.04861' contains '4855' / '1704' / '0486'
    4-digit substrings (not year-shaped). Real year '2017' from trailing date."""
    text = ("A.G.Howard.MobileNets[EB/OL].https://doi.org/10.48550/"
            "arXiv.1704.04861,April 17,2017")
    bib, warning = refs_to_bib.parse_electronic(text, "howard2017")
    assert warning is None
    assert "year = {2017}" in bib
    assert "year = {4855}" not in bib
    assert "year = {1704}" not in bib


def test_case_anon_arxiv_2004_id_not_year():
    """arxiv URL 'abs/2004.10934' has '2004' which IS year-shaped — but the
    real year is in the trailing date. Stripping URL ensures we read the
    trailing date, not the arxiv ID."""
    text = ("A.Bochkovskiy.YOLOv4[EB/OL].https://arxiv.org/abs/2004.10934,"
            "April 23,2020")
    bib, warning = refs_to_bib.parse_electronic(text, "bochkovskiy2020")
    assert warning is None
    assert "year = {2020}" in bib
    # 2004 is year-shaped, so stripping the URL is essential to avoid it.
    assert "year = {2004}" not in bib


# ============================================================
# D35 — bracket-prefix whitespace tolerance
# ============================================================

def test_d35_bracket_prefix_inner_space(tmp_path):
    """'[ 7] entry' 与 '[7] entry' 等价 — 容忍内部空格."""
    raw = "[ 7] ULTRALYTICS. YOLOv8 Documentation[EB/OL]. 2023.\n"
    in_path = tmp_path / "refs.txt"
    out_path = tmp_path / "refs.bib"
    in_path.write_text(raw, encoding='utf-8')
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, 'refs_to_bib.py'),
                        '--input', str(in_path), '--output', str(out_path)],
                       capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 0, r.stderr
    bib = out_path.read_text(encoding='utf-8')
    assert "@misc{" in bib
    # cite_map index = 1 (该 entry 是第一条 non-empty), 而非被吃成 [ 7]
    cite_map_path = tmp_path / "cite_map.json"
    import json
    cm = json.loads(cite_map_path.read_text(encoding='utf-8'))
    assert "1" in cm


def test_d35_bracket_prefix_trailing_space(tmp_path):
    """'[9 ] entry' 容忍尾部空格."""
    raw = "[9 ] HOWARD A, SANDLER M. MobileNetV3[C]//ICCV. 2019: 1-2.\n"
    in_path = tmp_path / "refs.txt"
    out_path = tmp_path / "refs.bib"
    in_path.write_text(raw, encoding='utf-8')
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, 'refs_to_bib.py'),
                        '--input', str(in_path), '--output', str(out_path)],
                       capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 0, r.stderr
    bib = out_path.read_text(encoding='utf-8')
    assert "@inproceedings{" in bib
    # citekey 不应该含 '9 ' / '[9 ]' 残渣
    assert "[9" not in bib
    assert "9 ]" not in bib


# ============================================================
# 集成 sanity: refs_to_bib 全 pipeline 跑通本会话 30 条
# ============================================================

def test_pipeline_smoke_all_30_types():
    """smoke test: 喂入 5 类条目混合, 全部应解析为对应 entry 类型."""
    raw = """[1] Tummala R R. Test[C]. Conf,2005,3-7.
[2] Sun Y, et al. Test[J]. Journal,2022,33(15):11847-11865.
[3] 林宗寿. 测试[M]. 武汉:出版社,2008,120-135.
[4] 张三. 测试[D]. 杭州:浙江大学,2007,45-56.
[5] 委员会. 标准[S]. 北京:出版社,2023.
"""
    import tempfile
    with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write(raw)
        in_path = f.name
    out_path = in_path + '.bib'
    try:
        # 直接调 main 类似流程
        import subprocess
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, 'refs_to_bib.py'),
             '--input', in_path, '--output', out_path],
            capture_output=True, text=True, encoding='utf-8',
        )
        assert result.returncode == 0, f"refs_to_bib failed: {result.stderr}"
        with open(out_path, encoding='utf-8') as f:
            bib_content = f.read()
        # 每种类型都应出现
        assert "@inproceedings{" in bib_content  # [C]
        assert "@article{" in bib_content        # [J]
        assert "@book{" in bib_content           # [M]
        assert "@mastersthesis{" in bib_content  # [D]
        assert "@misc{" in bib_content           # [S]
    finally:
        os.unlink(in_path)
        if os.path.exists(out_path):
            os.unlink(out_path)
        # cite_map.json 也清
        cm_path = os.path.join(os.path.dirname(in_path), 'cite_map.json')
        if os.path.exists(cm_path):
            os.unlink(cm_path)
        # refs_report.json 也清
        rep_path = os.path.join(os.path.dirname(out_path), 'refs_report.json')
        if os.path.exists(rep_path):
            os.unlink(rep_path)
