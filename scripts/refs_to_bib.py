#!/usr/bin/env python3
"""
refs_to_bib.py — 中文学术参考文献 (GB/T 7714) → BibTeX

基于 UESTC 实战验证，吸收 Gemini Review 的 7 条异常格式处理建议：
1. 尾部注释剥离
2. 国籍前缀处理 [法]、[德] 等
3. 全局唯一 Citekey (pinyin + year + 去重后缀)
4. 译者分离
5. 全半角标点统一 (NFKC)
6. 不规则空格压缩
7. 按 [M/J/D/N] Strategy Pattern 分类解析

Usage:
    python refs_to_bib.py --input references_raw.txt --output reference.bib
"""

import argparse
import json
import os
import re
import sys
import unicodedata

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


# === 预处理 ===

def normalize(text):
    """全角→半角, 压缩空格"""
    text = unicodedata.normalize('NFKC', text)
    mapping = {
        '：': ':', '，': ',', '；': ';',
        '（': '(', '）': ')', '。': '.',
        '【': '[', '】': ']',
    }
    for k, v in mapping.items():
        text = text.replace(k, v)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def strip_trailing_note(text):
    """剥离尾部注释 (Review #1)"""
    text = re.sub(r'[(](注[:].*?)[)]$', '', text).strip()
    return text


def extract_nationality(author_str):
    """提取国籍前缀: [法]让·鲍德里亚 → ('法', '让·鲍德里亚')"""
    m = re.match(r'^\[([^\]]+)\]\s*', author_str)
    if m:
        return m.group(1), author_str[m.end():].strip()
    return None, author_str


def extract_translator(text):
    """分离译者: '刘成富,全志钢译' → ('刘成富 and 全志钢', rest)"""
    m = re.search(r'\.([^.]+?)译\.', text)
    if m:
        translators = m.group(1).strip()
        translators = re.sub(r'[,，]', ' and ', translators)
        remaining = text[:m.start()] + '.' + text[m.end():]
        return translators, remaining
    return None, text


def sanitize_citekey(key):
    """Force key to BibTeX-legal: [a-zA-Z][a-zA-Z0-9_]*

    Strips all non-alphanumeric/underscore chars, prefixes 'r' if leading digit.
    Empty result becomes 'refX'. CASE-A: prevents 'muta o ,izumi j2023' keys.
    """
    s = re.sub(r'[^a-zA-Z0-9_]', '', key)
    if not s:
        return 'refX'
    if s[0].isdigit():
        s = 'r' + s
    return s


CHINESE_RE = re.compile(r'[一-鿿]')


def _fix_one_author(name: str) -> str:
    """单个作者名归一化.

    D25 (Round 8 shared): 西文 'Sun Y' / 'Lee Y K' → 'Sun, Y.' / 'Lee, Y. K.'
       让 BST 正确识别 last/first, 不再渲染成 'S. Y'.
    D31 (Round 8 shared): 中文机构名含 '(' / '/' → 双花括号包整体, 防 BST 拆 first/last.
    """
    a = name.strip()
    if not a or a == 'others':
        return a
    # 中文人名/机构
    if CHINESE_RE.search(a):
        # D31: 含 () 或 / 的中文机构 (如 SAC/TC 178), 用双花括号包
        if ('(' in a or ')' in a or '/' in a):
            if not (a.startswith('{') and a.endswith('}')):
                return '{' + a + '}'
        return a
    # D25: 西文 'Last F' / 'Last F G' / 'Last-Hyphen F' 格式
    parts = a.split()
    if len(parts) < 2:
        return a
    surname = parts[0]
    initials = []
    for p in parts[1:]:
        if p.isupper() and 1 <= len(p) <= 3:
            # 'YK' → 'Y. K.', 'Y' → 'Y.'
            initials.append(' '.join(c + '.' for c in p))
        else:
            initials.append(p)
    return f"{surname}, {' '.join(initials)}"


def sanitize_author_list(author_str):
    """Convert Chinese-style ',' / '、' / ';' separated author list to BibTeX ' and ' format.

    Trailing '等' / 'et al' becomes 'others'. CASE-A: prevents bibtex
    'Too many commas in name 1' errors.

    D25 + D31 (Round 8 shared): 每个 split 后的 item 也走 _fix_one_author 归一化:
      - 西文 'Sun Y' → 'Sun, Y.' (BST 正确识别 last name)
      - 中文机构含 () 用 {{...}} 包 (BST 不当人名拆)
    """
    if not author_str:
        return author_str
    s = author_str.strip().rstrip(',，；; ')
    parts = re.split(r'[,，、;；]', s)
    cleaned = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if p in ('等', 'et al', 'et al.', 'et. al.', 'et. al'):
            cleaned.append('others')
        else:
            cleaned.append(_fix_one_author(p))
    if len(cleaned) <= 1:
        return _fix_one_author(author_str.strip())
    return ' and '.join(cleaned)


def generate_citekey(author, year, used_keys):
    """生成全局唯一 Citekey: author_year[a/b/c]"""
    _, clean_author = extract_nationality(author)

    if re.search(r'[\u4e00-\u9fff]', clean_author):
        surname = clean_author[0]
        pinyin_map = {
            '马': 'ma', '蓝': 'lan', '陈': 'chen', '王': 'wang', '孙': 'sun',
            '孟': 'meng', '刘': 'liu', '杨': 'yang', '喻': 'yu', '张': 'zhang',
            '李': 'li', '郭': 'guo', '胡': 'hu', '曹': 'cao', '丁': 'ding',
            '董': 'dong', '吴': 'wu', '彭': 'peng', '蒋': 'jiang', '汪': 'wang2',
            '陶': 'tao', '姚': 'yao', '赵': 'zhao', '罗': 'luo', '黄': 'huang',
            '徐': 'xu', '周': 'zhou', '高': 'gao', '宋': 'song', '许': 'xu2',
            '钱': 'qian', '郑': 'zheng', '习': 'xi', '毛': 'mao', '邓': 'deng',
            '林': 'lin', '叶': 'ye', '梁': 'liang', '韩': 'han', '唐': 'tang',
            '冯': 'feng', '贺': 'he', '夏': 'xia', '田': 'tian', '任': 'ren',
        }
        key_base = pinyin_map.get(surname, surname)
    else:
        parts = clean_author.split('·')
        key_base = parts[-1].lower() if parts else clean_author[:4].lower()

    key = f"{key_base}{year}"
    if key in used_keys:
        for suffix in 'abcdefghij':
            candidate = f"{key}{suffix}"
            if candidate not in used_keys:
                key = candidate
                break

    key = sanitize_citekey(key)
    # Re-check uniqueness after sanitization (sanitize may collapse distinct keys)
    if key in used_keys:
        for suffix in 'abcdefghij':
            candidate = sanitize_citekey(f"{key}{suffix}")
            if candidate not in used_keys:
                key = candidate
                break
    used_keys.add(key)
    return key


# === 条目解析器 (Strategy Pattern) ===

def parse_book(text, citekey):
    """解析 [M] 著作"""
    translator, text = extract_translator(text)
    parts = text.split('[M].')
    if len(parts) < 2:
        return None, f"无法解析著作: {text[:60]}"

    author_title = parts[0].strip()
    pub_info = parts[1].strip()

    dot_pos = author_title.find('.')
    author = author_title[:dot_pos].strip() if dot_pos != -1 else author_title
    title = author_title[dot_pos+1:].strip() if dot_pos != -1 else ""

    publisher, address, year, pages = "", "", "", ""
    # 优先匹配带页码: "address: publisher, year, pages"
    m_full = re.search(r'(.+?):(.+?),\s*(\d{4})\s*,\s*([\d\-,\s]+)\s*\.?\s*$', pub_info)
    if m_full:
        address, publisher, year, pages = m_full.group(1).strip(), m_full.group(2).strip(), m_full.group(3), m_full.group(4).strip().rstrip('.,')
    else:
        m = re.search(r'(.+?):(.+?),(\d{4})', pub_info)
        if m:
            address, publisher, year = m.group(1).strip(), m.group(2).strip(), m.group(3)
        else:
            m2 = re.search(r'(\d{4})', pub_info)
            year = m2.group(1) if m2 else "0000"
            publisher = pub_info

    _, clean_author = extract_nationality(author)

    bib = f"@book{{{citekey},\n"
    bib += f"  author = {{{sanitize_author_list(clean_author)}}},\n"
    bib += f"  title = {{{title}}},\n"
    if translator:
        bib += f"  translator = {{{translator}}},\n"
    bib += f"  publisher = {{{publisher}}},\n"
    if address:
        bib += f"  address = {{{address}}},\n"
    bib += f"  year = {{{year}}},\n"
    if pages:
        bib += f"  pages = {{{pages}}},\n"
    bib += f"}}\n\n"
    return bib, None


def parse_article(text, citekey):
    """解析 [J] 期刊"""
    parts = text.split('[J].')
    if len(parts) < 2:
        return None, f"无法解析期刊: {text[:60]}"

    author_title = parts[0].strip()
    journal_info = parts[1].strip()

    dot_pos = author_title.find('.')
    author = author_title[:dot_pos].strip() if dot_pos != -1 else author_title
    title = author_title[dot_pos+1:].strip() if dot_pos != -1 else ""

    journal, year, volume, number, pages = "", "", "", "", ""
    # GB/T 7714 期刊格式优先级:
    #   1. "Y, V(N): P" → volume + number  (e.g. "1993, 73(1): 348-366")
    #   2. "Y, (N): P" → number only       (强制括号, 极罕见)
    #   3. "Y, V: P"   → volume only       (e.g. "1987, 95: 45-60", "2016, 447: 283-289")
    m_vn = re.match(r'(.+?),\s*(\d{4})\s*,?\s*(\d+)\s*\((\d+)\)\s*:\s*([\d\-+]+)', journal_info)
    if m_vn:
        journal, year, volume, number, pages = m_vn.group(1).strip(), m_vn.group(2), m_vn.group(3), m_vn.group(4), m_vn.group(5)
    else:
        m_n = re.match(r'(.+?),\s*(\d{4})\s*,?\s*\((\d+)\)\s*:\s*([\d\-+]+)', journal_info)
        if m_n:
            # CASE-A: "Y (N):P" 没年-括号间逗号 (公管学科常见). 也兼容 "Y, (N):P".
            journal, year, number, pages = m_n.group(1).strip(), m_n.group(2), m_n.group(3), m_n.group(4)
        else:
            m_vp = re.match(r'(.+?),\s*(\d{4})\s*,\s*(\d+)\s*:\s*([\d\-+]+)', journal_info)
            if m_vp:
                journal, year, volume, pages = m_vp.group(1).strip(), m_vp.group(2), m_vp.group(3), m_vp.group(4)
            else:
                m3 = re.search(r'(\d{4})', journal_info)
                year = m3.group(1) if m3 else "0000"
                journal = journal_info

    # CASE-A round 2: journal 字段如残留 ",年份..." (上面 fallback 分支或 source 杂数据)
    # 应剥离, 否则 BST 会渲染重复年份 (e.g. "中国社会科学,2018 (5):..., 2018." 双 year).
    journal = re.sub(r'\s*,\s*\d{4}\b.*$', '', journal).rstrip(',. ').strip()

    bib = f"@article{{{citekey},\n"
    bib += f"  author = {{{sanitize_author_list(author)}}},\n"
    bib += f"  title = {{{title}}},\n"
    bib += f"  journal = {{{journal}}},\n"
    bib += f"  year = {{{year}}},\n"
    if volume:
        bib += f"  volume = {{{volume}}},\n"
    if number:
        bib += f"  number = {{{number}}},\n"
    if pages:
        bib += f"  pages = {{{pages}}},\n"
    bib += f"}}\n\n"
    return bib, None


# D-thesis-address (CASE-A round 4 lun51 fix): GB/T 7714 §8.4 学位论文应有出版地.
# 客户原稿常省略出版地, lun51 检测 "缺少出版年, 或者出版者和出版年未用逗号分隔" 严重错误.
# 按学校名映射回所在城市自动补 address 字段, .bst 已支持 "address: school" 渲染.
SCHOOL_TO_CITY = {
    # ===== 985/211 与常见综合大学 =====
    '电子科技大学': '成都', '清华大学': '北京', '北京大学': '北京',
    '浙江大学': '杭州', '复旦大学': '上海', '上海交通大学': '上海',
    '中国科学技术大学': '合肥', '南京大学': '南京', '华中科技大学': '武汉',
    '西安交通大学': '西安', '哈尔滨工业大学': '哈尔滨', '同济大学': '上海',
    '武汉大学': '武汉', '中山大学': '广州', '北京航空航天大学': '北京',
    '北京理工大学': '北京', '东南大学': '南京', '西北工业大学': '西安',
    '天津大学': '天津', '大连理工大学': '大连', '华南理工大学': '广州',
    '北京邮电大学': '北京', '北京交通大学': '北京', '北京科技大学': '北京',
    '南京航空航天大学': '南京', '南京理工大学': '南京', '南京财经大学': '南京',
    '南京邮电大学': '南京', '南京信息工程大学': '南京',
    '宁波大学': '宁波', '江苏科技大学': '镇江', '太原科技大学': '太原',
    '沈阳工业大学': '沈阳', '解放军信息工程大学': '郑州', '信息工程大学': '郑州',
    '国防科技大学': '长沙', '国防科学技术大学': '长沙',
    # ===== 其它常见 =====
    '中国海洋大学': '青岛', '青岛大学': '青岛', '湖南大学': '长沙',
    '中南大学': '长沙', '吉林大学': '长春', '山东大学': '济南',
    '兰州大学': '兰州', '重庆大学': '重庆', '四川大学': '成都',
    '西南交通大学': '成都', '西南大学': '重庆', '云南大学': '昆明',
    '华北电力大学': '北京', '中国人民大学': '北京', '中央民族大学': '北京',
    '北京师范大学': '北京', '华东师范大学': '上海', '华中师范大学': '武汉',
    '杭州电子科技大学': '杭州', '西安电子科技大学': '西安',
    '河海大学': '南京', '苏州大学': '苏州', '郑州大学': '郑州',
    '华东理工大学': '上海', '北京工业大学': '北京', '东北大学': '沈阳',
}


def _infer_address_from_school(school: str) -> str:
    """学校名 → 城市. 完全匹配优先, 否则按子串后缀启发式 (大学结尾)."""
    if not school:
        return ""
    s = school.strip().rstrip('，,。.、 ')
    if s in SCHOOL_TO_CITY:
        return SCHOOL_TO_CITY[s]
    # 子串包含: 客户偶尔写 "XX大学计算机学院" 整串
    for k, v in SCHOOL_TO_CITY.items():
        if k in s:
            return v
    return ""


def parse_thesis(text, citekey):
    """解析 [D] 学位论文.

    CASE-A round 4: 自动补 address (出版地), 解决 lun51 "缺少出版地" 严重错误.
    """
    parts = text.split('[D].')
    if len(parts) < 2:
        return None, f"无法解析学位论文: {text[:60]}"

    author_title = parts[0].strip()
    school_info = parts[1].strip()

    dot_pos = author_title.find('.')
    author = author_title[:dot_pos].strip() if dot_pos != -1 else author_title
    title = author_title[dot_pos+1:].strip() if dot_pos != -1 else ""

    school, year, pages, address = "", "", "", ""
    # 客户偶尔显式写出版地 "<city>: <school>, <year>" — 优先尊重
    m_addr = re.match(r'(.+?)[:：]\s*(.+?),\s*(\d{4})\s*(?:,\s*([\d\-,\s]+))?\s*\.?\s*$', school_info)
    if m_addr:
        address = m_addr.group(1).strip()
        school = m_addr.group(2).strip()
        year = m_addr.group(3)
        pages = (m_addr.group(4) or "").strip().rstrip('.,')
    else:
        # D-thesis-pages: 解析尾部页码 (e.g. "...大学, 2007, 45-49, 51-56")
        m_full = re.match(r'(.+?),\s*(\d{4})\s*,\s*([\d\-,\s]+)\s*\.?\s*$', school_info)
        if m_full:
            school, year, pages = m_full.group(1).strip(), m_full.group(2), m_full.group(3).strip().rstrip('.,')
        else:
            m = re.match(r'(.+?),\s*(\d{4})', school_info)
            if m:
                school, year = m.group(1).strip(), m.group(2)
        if not address:
            address = _infer_address_from_school(school)

    bib = f"@mastersthesis{{{citekey},\n"
    bib += f"  author = {{{sanitize_author_list(author)}}},\n"
    bib += f"  title = {{{title}}},\n"
    bib += f"  school = {{{school}}},\n"
    if address:
        bib += f"  address = {{{address}}},\n"
    bib += f"  year = {{{year}}},\n"
    if pages:
        bib += f"  pages = {{{pages}}},\n"
    bib += f"  type = {{硕士学位论文}},\n"
    bib += f"}}\n\n"
    return bib, None


def parse_proceedings(text, citekey):
    """解析 [C] 会议论文.

    D23 原版只支持 '[C].' 形式 (CASE-A [1] Tummala / [5] Lee Y K).
    D23 expansion (CASE-A): GB/T 7714 标准会议格式是 '[C]//<会议名>. <year>: <pp>.'
       (// 双斜杠分隔, 远比 '[C].' 常见 — IEEE/ACM/CVPR/ICCV/CVPR-W 全用此式).
    优先 split '[C]//', 兜底 '[C].'.
    """
    if '[C]//' in text:
        parts = text.split('[C]//', 1)
    else:
        parts = text.split('[C].')
    if len(parts) < 2:
        return None, f"无法解析会议论文: {text[:60]}"
    author_title = parts[0].strip()
    conf_info = parts[1].strip()

    dot_pos = author_title.find('.')
    author = author_title[:dot_pos].strip() if dot_pos != -1 else author_title
    title = author_title[dot_pos+1:].strip() if dot_pos != -1 else ""

    # 会议名, year, pages — 容忍尾部 . 或空白
    # D23 expansion (CASE-A): GB/T 7714 实战常用 '<Year>: <Pages>' (冒号分隔, 非逗号)
    conf_info = conf_info.rstrip(' .。')
    booktitle, year, pages, address = "", "", "", ""
    m = re.search(r'(\d{4})\s*[:,：，]\s*([\d\-+]+)\s*$', conf_info)
    if m:
        year, pages = m.group(1), m.group(2)
        booktitle = conf_info[:m.start()].rstrip(' ,，:.：').strip()
    else:
        # 末尾仅有 year (无 pages, 如 '...Conference. 2011') — 取最右 4 位为 year
        m_yr = re.search(r'(\d{4})\s*\.?\s*$', conf_info)
        if m_yr:
            year = m_yr.group(1)
            booktitle = conf_info[:m_yr.start()].rstrip(' ,，:.：').strip()
        else:
            ym = re.search(r'(\d{4})', conf_info)
            year = ym.group(1) if ym else "0000"
            booktitle = conf_info
    if not pages:
        pages = "1"  # BST DissertUESTC-bachelor.bst 强制要 pages 字段, 占位

    bib = f"@inproceedings{{{citekey},\n"
    bib += f"  author = {{{sanitize_author_list(author)}}},\n"
    bib += f"  title = {{{title}}},\n"
    bib += f"  booktitle = {{{booktitle}}},\n"
    bib += f"  year = {{{year}}},\n"
    if pages:
        bib += f"  pages = {{{pages}}},\n"
    bib += f"}}\n\n"
    return bib, None


def parse_standard(text, citekey):
    """解析 [S] 标准 (D23: 客户漏 [S]/[C]/[R] 等非 MJDN 类型).

    GB/T 7714 §8.4.3 标准格式: 责任者. 标准名称: 标准编号[S]. 出版地: 出版者, 出版年.
    """
    parts = text.split('[S].')
    if len(parts) < 2:
        return None, f"无法解析标准: {text[:60]}"
    author_title = parts[0].strip()
    pub_info = parts[1].strip()

    # 责任者. 标准名称: 标准号 形式 — 取第一个 '. ' 拆作者/标题
    dot_pos = author_title.find('.')
    author = author_title[:dot_pos].strip() if dot_pos != -1 else author_title
    title_with_no = author_title[dot_pos+1:].strip() if dot_pos != -1 else ""

    address, publisher, year = "", "", ""
    m = re.search(r'(.+?):(.+?),\s*(\d{4})', pub_info)
    if m:
        address, publisher, year = m.group(1).strip(), m.group(2).strip(), m.group(3)
    else:
        ym = re.search(r'(\d{4})', pub_info)
        year = ym.group(1) if ym else "0000"
        publisher = pub_info

    bib = f"@misc{{{citekey},\n"
    bib += f"  author = {{{sanitize_author_list(author)}}},\n"
    bib += f"  title = {{{title_with_no}}},\n"
    if publisher:
        bib += f"  howpublished = {{{publisher}}},\n"
    if address:
        bib += f"  address = {{{address}}},\n"
    bib += f"  year = {{{year}}},\n"
    bib += f"  note = {{[S] 标准}},\n"
    bib += f"}}\n\n"
    return bib, None


def parse_report(text, citekey, type_marker='R'):
    """解析 [R] 报告 / [P] 专利 / [Z] 其它 — 通用 fallback."""
    marker = f'[{type_marker}].'
    parts = text.split(marker)
    if len(parts) < 2:
        return None, f"无法解析[{type_marker}]: {text[:60]}"
    author_title = parts[0].strip()
    pub_info = parts[1].strip()

    dot_pos = author_title.find('.')
    author = author_title[:dot_pos].strip() if dot_pos != -1 else author_title
    title = author_title[dot_pos+1:].strip() if dot_pos != -1 else ""
    ym = re.search(r'(\d{4})', pub_info)
    year = ym.group(1) if ym else "0000"

    # CASE-A round 2: [Z] 其它 不做 note 标签 (BST 会字面渲染 "[Z] 其它." 致 PDF 出现垃圾后缀).
    # [R] 报告 / [P] 专利 保留 note (语义有用).
    type_note = {'R': '报告', 'P': '专利'}.get(type_marker, '')

    # CASE-A round 2: pub_info 若仅含年份 (或 "year." / "year, year." 形式),
    # year 字段已捕获, howpublished 重复年份会致 BST 渲染 "2013., 2013." 双 year. 清空.
    pub_info_norm = pub_info.strip().rstrip('.,').strip()
    if re.match(r'^\d{4}(\s*[,.]\s*\d{4})*\.?$', pub_info_norm):
        howpublished = ""
    else:
        howpublished = pub_info

    bib = f"@misc{{{citekey},\n"
    bib += f"  author = {{{sanitize_author_list(author)}}},\n"
    bib += f"  title = {{{title}}},\n"
    if howpublished:
        bib += f"  howpublished = {{{howpublished}}},\n"
    bib += f"  year = {{{year}}},\n"
    if type_note:
        bib += f"  note = {{{type_note}}},\n"
    bib += f"}}\n\n"
    return bib, None


def parse_newspaper(text, citekey):
    """解析 [N] 报纸"""
    parts = text.split('[N].')
    if len(parts) < 2:
        return None, f"无法解析报纸: {text[:60]}"

    author_title = parts[0].strip()
    pub_info = parts[1].strip()

    dot_pos = author_title.find('.')
    author = author_title[:dot_pos].strip() if dot_pos != -1 else author_title
    title = author_title[dot_pos+1:].strip() if dot_pos != -1 else ""

    year = ""
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', pub_info)
    if m:
        year = m.group(1)

    journal = re.split(r',', pub_info)[0].strip() if ',' in pub_info else pub_info

    bib = f"@article{{{citekey},\n"
    bib += f"  author = {{{sanitize_author_list(author)}}},\n"
    bib += f"  title = {{{title}}},\n"
    bib += f"  journal = {{{journal}}},\n"
    bib += f"  year = {{{year}}},\n"
    bib += f"  note = {{报纸}},\n"
    bib += f"}}\n\n"
    return bib, None


def parse_electronic(text, citekey):
    """解析 [EB/OL] 电子资源 / 在线资源 (D34 expansion: CASE-A [7] ULTRALYTICS YOLOv8).

    GB/T 7714 §8.4 在线资源: 责任者. 标题[EB/OL]. (年份). [访问日期]. URL.
    部分作者省略 URL/访问日期, 只留 '[EB/OL]. <year>.' — 仍需正确入 ref.bib.
    """
    parts = text.split('[EB/OL]')
    if len(parts) < 2:
        return None, f"无法解析电子资源: {text[:60]}"
    author_title = parts[0].strip().rstrip('.')
    pub_info = parts[1].lstrip('.').strip()

    dot_pos = author_title.find('.')
    author = author_title[:dot_pos].strip() if dot_pos != -1 else author_title
    title = author_title[dot_pos+1:].strip() if dot_pos != -1 else ""

    # CASE-A: URL embedded in pub_info often contains 4-digit substrings
    # (arxiv abs/2207.02696, DOI 10.48550, etc.) that masquerade as years.
    # Strip the URL first, then look for a year-shaped digit run (1900-2099).
    url_m = re.search(r'https?://\S+', pub_info)
    url = url_m.group(0).rstrip('.') if url_m else ""
    pub_no_url = pub_info.replace(url, "") if url else pub_info
    ym = re.search(r'\b(19|20)\d{2}\b', pub_no_url)
    year = ym.group(0) if ym else "0000"

    # CASE-A: GB/T 7714 places [EB/OL] right after the title, not at the
    # tail of the entry. Old code wrote `note = {[EB/OL] 电子资源}` which BST
    # rendered as a trailing "[EB/OL] 电子资源" string disconnected from the
    # title. Inline the type marker into the title field so BST renders it
    # adjacent to the title; drop the note field's redundant Chinese gloss.
    title_with_marker = f"{title}[EB/OL]" if title else "[EB/OL]"
    bib = f"@misc{{{citekey},\n"
    bib += f"  author = {{{sanitize_author_list(author)}}},\n"
    bib += f"  title = {{{title_with_marker}}},\n"
    bib += f"  year = {{{year}}},\n"
    if url:
        bib += f"  howpublished = {{\\url{{{url}}}}},\n"
    bib += f"}}\n\n"
    return bib, None


# === D29 + D30 后处理 (Round 8 shared) ===

_FIELD_PATTERN_CACHE = {}


def _field_pattern(field_name):
    pat = _FIELD_PATTERN_CACHE.get(field_name)
    if pat is None:
        pat = re.compile(r'\b' + field_name + r'\s*=\s*\{', re.MULTILINE)
        _FIELD_PATTERN_CACHE[field_name] = pat
    return pat


def _find_field_value_range(text, field_name, start):
    """找 'field_name = {...}' 的 {...} 范围 (含花括号配对). 返回 (val_start, val_end_exclusive) 或 None."""
    m = _field_pattern(field_name).search(text, start)
    if not m:
        return None
    i = m.end()
    depth = 1
    while i < len(text):
        c = text[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return m.end(), i
        i += 1
    return None


def _replace_field(text, field_name, transform):
    """全文找所有 field_name = {...}, 用 transform(val_str) 替换 val."""
    out = []
    cur = 0
    while True:
        rng = _find_field_value_range(text, field_name, cur)
        if not rng:
            out.append(text[cur:])
            break
        v_start, v_end = rng
        out.append(text[cur:v_start])
        out.append(transform(text[v_start:v_end]))
        cur = v_end
    return ''.join(out)


def _wrap_title_protect_case(val):
    """D29: title 整体加 {} 强制 BST 不动 case (防化学式 Sb2O3 → sb2o3)."""
    s = val.strip()
    # 已是双花括号包则不动
    if s.startswith('{') and s.endswith('}'):
        # 检查是不是单层包 (内部花括号平衡)
        depth = 0
        for ch in s[1:-1]:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth < 0:
                    return '{' + val + '}'
        if depth == 0:
            return '{' + val + '}'  # 单层 → 包成双层
    return '{' + val + '}'


def _escape_amp(val):
    """D30: publisher/journal/howpublished 字段裸 & → \\& (BibTeX 编译要求)."""
    return re.sub(r'(?<!\\)&', r'\\&', val)


def _add_space_after_dot(val: str) -> str:
    """CASE-A lun51 #30/31: 英文中 '.X' (X 字母数字) 应加空格 → '. X', 但人名
    缩写 (单大写字母后 .) 例外. 例:
       'Liao.YOLOv7'  → 'Liao. YOLOv7'  (词尾后接题名)
       'et al.YOLOv5' → 'et al. YOLOv5'
       'C.-Y.Wang'    → 'C.-Y.Wang'      (单大写字母后 . — 缩写)
       'A.Bochkovskiy'→ 'A.Bochkovskiy'  (单大写字母后 . — 缩写)
       'C. -Y.Wang'   → 'C. -Y.Wang'     (已有空格不动)
    """
    return re.sub(r'(?<![A-Z\.])\.(?=[A-Za-z0-9])', '. ', val)


def postprocess_bib_for_render(bib_content: str) -> str:
    """对 ref.bib 全文做 D29 + D30 + CASE-A 后处理.

    - title 整体 {{...}} 包 (防 BST sentence-case 破坏化学式)
    - publisher/journal/howpublished 字段 & → \\&
    - title/howpublished/booktitle/journal: '.X' → '. X' (CASE-A lun51)
    """
    bib_content = _replace_field(bib_content, 'title', _wrap_title_protect_case)
    for fld in ('publisher', 'journal', 'howpublished', 'booktitle'):
        bib_content = _replace_field(bib_content, fld, _escape_amp)
    for fld in ('title', 'howpublished', 'booktitle', 'journal'):
        bib_content = _replace_field(bib_content, fld, _add_space_after_dot)
    return bib_content


# === 主流程 ===

def main():
    parser = argparse.ArgumentParser(description='中文学术参考文献 → BibTeX')
    parser.add_argument('--input', required=True, help='参考文献原文文件')
    parser.add_argument('--output', required=True, help='输出 .bib 文件路径')
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"❌ 文件不存在: {args.input}")
        sys.exit(1)

    with open(args.input, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    used_keys = set()
    bib_entries = []
    report = {'total': 0, 'success': 0, 'warnings': []}
    cite_map = {}
    idx = 0

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        idx += 1
        
        if line.endswith('：') or line.endswith(':'):
            continue  # 跳过分类标题

        line = normalize(line)
        line = strip_trailing_note(line)

        # 可选的 [数字] 前缀 — 有则剥离，无则直接处理
        # D35 (CASE-A): 容忍 '[ 7]' / '[9 ]' 等花括号内/旁空格 (客户原稿手打瑕疵)
        m = re.match(r'^\[\s*(\d+)\s*\]\s*', line)
        if m:
            entry_text = line[m.end():].strip()
        else:
            entry_text = line

        # CASE-A fix: 没有文献类型标记的行,先尝试 IEEE 格式 fallback (Western 期刊/会议)
        # 否则才 SKIP. 例如 [4]A. Zaeemzadeh, M. Joneidi, ... 是 IEEE 会议 paper
        # D34 (CASE-A): [EB/OL] 在线资源也算合法类型, 走 parse_electronic
        if not (re.search(r'\[(M|J|D|N|C|R|S|P|Z)\]', entry_text) or '[EB/OL]' in entry_text):
            # IEEE-style heuristic: contains quoted title + year + journal/conference
            looks_western = (
                re.search(r'"[^"]{10,}"', entry_text)
                or re.search(r'\bIEEE\b|\bACM\b|\bSIAM\b|\bSpringer\b', entry_text)
                or re.search(r'\bConference\b|\bProceedings\b|\bTransactions\b|\bJournal\b', entry_text)
            )
            if looks_western:
                # Treat as @misc fallback so bibtex won't drop it
                year_match = re.search(r'\b(19|20)\d{2}\b', entry_text)
                year = year_match.group(0) if year_match else "0000"
                first_words = re.match(r'^([A-Z][^,.\d]{1,30})', entry_text)
                key_seed = first_words.group(1).strip() if first_words else "western"
                citekey = generate_citekey(key_seed, year, used_keys)
                cite_map[str(idx)] = citekey
                # Try to extract title from quoted string
                title_match = re.search(r'"([^"]{10,200})"', entry_text)
                title = title_match.group(1) if title_match else entry_text[:120]

                # CASE-A round 4 lun51 fix: IEEE_FALLBACK 补类型标识 [C]/[J]
                # lun51 检测 "没有找到参考文献类型标识" → 5 处提醒源自此处.
                # 启发式 (按出现频率排序): 会议优先, 期刊次之, 杂项保底.
                if re.search(r'\b(Conference|Proceedings|Symposium|Workshop|ICASSP|MASS)\b', entry_text):
                    type_tag = '[C]'
                elif re.search(r'\b(Transactions|Journal|IEEE\s+Communications|Letters|Magazine)\b', entry_text):
                    type_tag = '[J]'
                else:
                    type_tag = '[N]'  # 兜底: 通用文献类型
                # title 尾逗号 strip (lun51 #163 "出现连续标点 ,," 触发源)
                title = title.rstrip(',. ').strip()
                # 拼接: "<title>[C]" — BST @misc 渲染 title 时类型标识紧跟标题
                title_with_tag = f"{title}{type_tag}"

                bib_entries.append(
                    f"@misc{{{citekey},\n"
                    f"  title = {{{title_with_tag}}},\n"
                    f"  note = {{{entry_text[:200]}}},\n"
                    f"  year = {{{year}}},\n"
                    f"}}\n\n"
                )
                report['total'] += 1
                report['success'] += 1
                report['warnings'].append({'type': 'IEEE_FALLBACK',
                                           'text': f'[{idx}] → @misc {citekey} ({type_tag})'})
                continue
            report['warnings'].append({'type': 'SKIP', 'text': line[:80]})
            continue

        report['total'] += 1

        year_match = re.search(r'(\d{4})', entry_text)
        year = year_match.group(1) if year_match else "0000"

        dot_pos = entry_text.find('.')
        author_part = entry_text[:dot_pos].strip() if dot_pos != -1 else entry_text[:10]
        citekey = generate_citekey(author_part, year, used_keys)
        
        cite_map[str(idx)] = citekey

        # Strategy Pattern: 按类型分路
        bib, warning = None, None
        if '[M]' in entry_text:
            bib, warning = parse_book(entry_text, citekey)
        elif '[J]' in entry_text:
            bib, warning = parse_article(entry_text, citekey)
        elif '[D]' in entry_text:
            bib, warning = parse_thesis(entry_text, citekey)
        elif '[N]' in entry_text:
            bib, warning = parse_newspaper(entry_text, citekey)
        elif '[C]' in entry_text:
            bib, warning = parse_proceedings(entry_text, citekey)
        elif '[S]' in entry_text:
            bib, warning = parse_standard(entry_text, citekey)
        elif '[R]' in entry_text:
            bib, warning = parse_report(entry_text, citekey, 'R')
        elif '[P]' in entry_text:
            bib, warning = parse_report(entry_text, citekey, 'P')
        elif '[Z]' in entry_text:
            bib, warning = parse_report(entry_text, citekey, 'Z')
        elif '[EB/OL]' in entry_text:
            bib, warning = parse_electronic(entry_text, citekey)
        else:
            warning = f"未知文献类型: {entry_text[:60]}"

        if bib:
            bib_entries.append(bib)
            report['success'] += 1
        if warning:
            report['warnings'].append({'type': 'PARSE_ERROR', 'text': warning})
            bib_entries.append(f"% WARNING: {warning}\n")

    # 写入 .bib (含 D29/D30 后处理: title 双花括号 + publisher/journal & escape)
    output_dir = os.path.dirname(args.output) or '.'
    os.makedirs(output_dir, exist_ok=True)
    raw_bib = ''.join(bib_entries)
    final_bib = postprocess_bib_for_render(raw_bib)
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(f"% 自动生成的 BibTeX 文件\n")
        f.write(f"% 共 {len(bib_entries)} 条文献\n")
        f.write(f"% 生成工具: refs_to_bib.py (thesis-formatter skill, Round 8 D29/D30 后处理)\n\n")
        f.write(final_bib)

    # 写入 cite_map.json
    input_dir = os.path.dirname(args.input) or '.'
    cite_map_path = os.path.join(input_dir, 'cite_map.json')
    with open(cite_map_path, 'w', encoding='utf-8') as f:
        json.dump(cite_map, f, ensure_ascii=False, indent=2)

    # 写入报告
    report_path = os.path.join(output_dir, 'refs_report.json')
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"✅ 生成 {report['success']}/{report['total']} 条 BibTeX → {args.output}")
    if report['warnings']:
        print(f"⚠️ {len(report['warnings'])} 条警告，详见 {report_path}")


if __name__ == '__main__':
    main()
