#!/usr/bin/env python3
"""preflight_risk_router.py — Round 7 阶段 D, 元层 workflow 5a.

新 docx 进流水线前 (Step 0), 静态扫描触发条件, 输出 D 缺陷风险预警表.

设计思路:
  - dashboard.json 的 detect_signature 字段是**事后诊断**描述 (产物级)
  - 本 router 用 hardcoded RULE_REGISTRY (input-side 触发) 检测 docx
  - 命中后查 dashboard 拿 status/fix_location 做分类输出:
      ✅ shared_code_fixed   = 已修, 不影响产物
      ⚠️  case_private        = candidate, 修法见卡片, 当前 case 需手动干预
      ❌ pending              = 未修, 需立即手动干预
      📝 (无 D 对应)          = 仅提示客户原稿瑕疵 (如关键词超 5)

与 5b/5d 的衔接:
  - 5b dashboard.json 提供 D 卡片元数据 (status/title/fix_location)
  - 5d Phase 7 wrap-up 产新 candidate → router 自动覆盖更多 trigger (扩 RULE_REGISTRY)
  - 形成闭环: 新 case → 新 candidate → router 下次 case 自动预警

Usage:
    python preflight_risk_router.py <docx_path> [--dashboard <path>] [--json]
    # exit 0 总是 (router 不阻断, 仅信息提供)
"""

from __future__ import annotations
import argparse
import json
import os
import re
import sys
import zipfile
from typing import Callable, Dict, List, Tuple

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

try:
    from xml.etree import ElementTree as ET
except ImportError:
    ET = None  # type: ignore

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


# ============================================================
# DocxFacts: 单次解压后给 RULES 复用的 facts 容器
# ============================================================

class DocxFacts:
    """对 docx 一次解压, 抽出常用 input-side facts 给 RULE_REGISTRY 共用."""
    def __init__(self, docx_path: str):
        self.docx_path = docx_path
        self.paragraphs: List[str] = []
        self.abstract_zh: str = ""
        self.abstract_en: str = ""
        self.references: List[str] = []
        self.acknowledgement: str = ""
        self.media_count: int = 0
        self.textbox_caption_count: int = 0
        self._load()

    def _load(self):
        try:
            with zipfile.ZipFile(self.docx_path) as z:
                names = z.namelist()
                self.media_count = sum(
                    1 for n in names if n.startswith("word/media/") and not n.endswith("/")
                )
                if "word/document.xml" not in names:
                    return
                doc_raw = z.read("word/document.xml").decode("utf-8", errors="replace")
                # D39: textbox caption 计数 (按 "图X-Y" 前缀匹配, 去重)
                tx_label_pat = re.compile(r"^(图\s*\d+\s*[-－.]\s*\d+)")
                seen = set()
                for tx in re.findall(r"<w:txbxContent>(.*?)</w:txbxContent>", doc_raw, re.DOTALL):
                    text = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", tx)).strip()
                    m = tx_label_pat.match(text)
                    if m:
                        label = re.sub(r"\s+", "", m.group(1)).replace("－", "-").replace(".", "-")
                        seen.add(label)
                self.textbox_caption_count = len(seen)
                with z.open("word/document.xml") as f:
                    tree = ET.parse(f)
        except (FileNotFoundError, zipfile.BadZipFile, ET.ParseError):
            return

        for p in tree.getroot().iter(W_NS + "p"):
            text = "".join((t.text or "") for t in p.iter(W_NS + "t"))
            if text.strip():
                self.paragraphs.append(text)

        # 中英文摘要 zone (近似切分)
        self.abstract_zh = self._slice_zone("摘要", "ABSTRACT")
        self.abstract_en = self._slice_zone("ABSTRACT", "目录")
        self.references = self._slice_references()
        self.acknowledgement = self._slice_acknowledgement()

    @staticmethod
    def _norm(text: str) -> str:
        """压缩全部空白后比较 (覆盖 '摘  要' / '致 谢' 全角空格)."""
        return re.sub(r"\s+", "", text)

    def _slice_zone(self, start_marker: str, end_marker: str) -> str:
        """Slice paragraphs[start..end] where start/end are short title paragraphs.

        匹配规则: 段长 < 12 + norm 后 == marker (兼容 '摘  要', '致 谢').
        """
        start_idx = end_idx = -1
        for i, p in enumerate(self.paragraphs):
            ps = p.strip()
            if len(ps) > 12:
                continue  # 不是短标题
            norm = self._norm(ps)
            if start_idx < 0 and norm == start_marker:
                start_idx = i
            elif start_idx >= 0 and norm == end_marker:
                end_idx = i
                break
        if start_idx < 0:
            return ""
        end_idx = end_idx if end_idx > 0 else min(start_idx + 30, len(self.paragraphs))
        return "\n".join(self.paragraphs[start_idx + 1:end_idx])

    def _slice_references(self) -> List[str]:
        """找**最后一个** "参考文献" 短标题段 (排除 TOC 中的 '参考文献6' 这种带页码), 后面读引用条目.

        引用条目识别: 以 '[N]' / 'N.' / 'N、' 或 西文 'Last F' 形式开头.
        """
        # 找所有候选, 取最后一个 (TOC 在前, 真参考文献在后)
        candidates = []
        for i, p in enumerate(self.paragraphs):
            ps = p.strip()
            if len(ps) > 12:
                continue
            if self._norm(ps) == "参考文献":
                candidates.append(i)
        if not candidates:
            return []
        start_idx = candidates[-1] + 1

        out = []
        for p in self.paragraphs[start_idx:]:
            ps = p.strip()
            if not ps:
                continue
            # 终止条件
            norm = self._norm(ps)
            if len(ps) < 12 and norm in ("致谢", "攻读硕士学位期间取得的成果",
                                          "攻读博士学位期间取得的成果", "外文资料原文",
                                          "外文资料译文", "附录"):
                break
            # 引用条目 — 多种格式
            if re.match(r"^\s*\[\d+\]", p):
                out.append(p)
            elif re.match(r"^\s*\d+[.\.、]\s*[A-Z一-鿿]", p):
                out.append(p)
            elif re.match(r"^[A-Z][a-z]+(?:\s+[A-Z]){1,3}[,.\s]", p):  # 西文 'Last F G'
                out.append(p)
            elif re.match(r"^[一-鿿][一-鿿]+", p) and re.search(r"\[[A-Z]\]", p):
                out.append(p)  # 中文人名/机构 + 含 [M]/[J]/[D]/[S] 类型标
        return out

    def _slice_acknowledgement(self) -> str:
        """找'致谢'短标题段, 后面读致谢正文 (一般 docx '致谢' 出现在参考文献之前 1 次)."""
        # 致谢通常在参考文献之前. 取**第一个** 短标题 '致谢' (而非最后一个 — 参考文献条目里
        # 含 '致谢' 词的可能性极低, 但 docx 顺序里致谢一般是第一次单独出现的)
        for i, p in enumerate(self.paragraphs):
            ps = p.strip()
            if len(ps) > 8:
                continue
            if self._norm(ps) == "致谢":
                start_idx = i + 1
                break
        else:
            return ""
        out = []
        for p in self.paragraphs[start_idx:]:
            ps = p.strip()
            if not ps:
                continue
            # 终止: 任何下一章/段标题
            if len(ps) < 12 and self._norm(ps) in (
                "参考文献",
                "攻读硕士学位期间取得的成果", "攻读博士学位期间取得的成果",
                "外文资料原文", "外文资料译文", "附录",
            ):
                break
            out.append(p)
            if len("\n".join(out)) > 2000:
                break
        return "\n".join(out)


# ============================================================
# RULE_REGISTRY: D_id → (description, callable(facts) → trigger_evidence_or_None)
# ============================================================

def _rule_d22(facts: DocxFacts) -> str | None:
    """D22: 摘要含 % 字符 (会被 LaTeX 当注释吞段)"""
    for zone, name in [(facts.abstract_zh, "中文摘要"), (facts.abstract_en, "英文摘要")]:
        if "%" in zone:
            sample = next((line for line in zone.split("\n") if "%" in line), "")[:60]
            return f"{name}含 %: {sample!r}"
    return None


def _rule_d23(facts: DocxFacts) -> str | None:
    """D23: 参考文献含 [C]/[S]/[R]/[P]/[Z] 类型"""
    extra_types = {"[C]", "[S]", "[R]", "[P]", "[Z]"}
    refs_text = "\n".join(facts.references)
    hits = sorted(t for t in extra_types if t in refs_text)
    if hits:
        return f"参考文献含 {hits} 类型 (refs_to_bib parse_proceedings/standard/report)"
    return None


def _rule_d24(facts: DocxFacts) -> str | None:
    """D24: 任何 case 都会触发 (\\nocite{*} 是默认行为) — 标记为通用 candidate"""
    if facts.references:
        return f"参考文献 {len(facts.references)} 条 — 默认 \\nocite{{*}} 顺序按字典而非 docx 原序"
    return None


def _rule_d25(facts: DocxFacts) -> str | None:
    """D25: 参考文献含西文人名 'Last F' / 'Last F G' 格式 (空格分姓+名)"""
    # 兼容有/无 [N] 前缀
    pat = re.compile(r"(?:^|^\s*\[\d+\]\s*)([A-Z][a-z]+(?:-[A-Z][a-z]+)?)\s+[A-Z](?:\s+[A-Z])?\b")
    for r in facts.references[:30]:
        if pat.match(r.strip()):
            return f"含西文 'Last F' 格式作者 (refs_to_bib 需改 'Last, F.' 防 BST 错位)"
    return None


def _rule_d26(facts: DocxFacts) -> str | None:
    """D26: 摘要/正文含 ~ 字符 (中文论文常用范围号, 会被 LaTeX 当不间断空格吞)"""
    for zone, name in [(facts.abstract_zh, "中文摘要"), (facts.abstract_en, "英文摘要")]:
        if "~" in zone:
            sample = next((line for line in zone.split("\n") if "~" in line), "")[:60]
            return f"{name}含 ~ 范围号: {sample!r}"
    return None


def _rule_d27(facts: DocxFacts) -> str | None:
    """D27: 任何含引用的本科 case 都会触发 (\\cite 默认行内不上标)"""
    refs_text = "\n".join(facts.paragraphs)
    if re.search(r"\[\d+(?:[,\-\s]+\d+)*\]", refs_text):
        return "正文含 [N] 引用 — 默认 \\cite 行内不上标 (本科 spec L346 要求上标)"
    return None


def _rule_d28(facts: DocxFacts) -> str | None:
    """D28: 任何 case 都触发 (CLS reminder 默认开)"""
    return "documentclass 缺 noreminder → 摘要/致谢超 1 页时红字泄漏 (默认风险, 通用 fix)"


def _rule_d29(facts: DocxFacts) -> str | None:
    """D29: 参考文献 title 含化学式/缩写 (BST sentence-case 会破坏)"""
    refs_text = "\n".join(facts.references)
    chem_tokens = ["BaO", "SiO2", "Sb2O3", "B2O3", "Al2O3", "Na2O", "Li2O", "K2O", "CO2",
                   "NMR", "IPC", "IEEE", "CTE", "LTCC", "FR-4"]
    hits = sorted({t for t in chem_tokens if t in refs_text})
    if hits:
        return f"参考文献 title 含化学式/缩写 {hits[:5]} (BST sentence-case 会小写化)"
    return None


def _rule_d30(facts: DocxFacts) -> str | None:
    """D30: 参考文献含 publisher/journal 含 & 字符"""
    refs_text = "\n".join(facts.references)
    if "&" in refs_text:
        sample = next((r for r in facts.references if "&" in r), "")[:80]
        return f"参考文献含 & (BibTeX 编译会吞字符): {sample!r}"
    return None


def _rule_d31(facts: DocxFacts) -> str | None:
    """D31: 参考文献含中文机构作者 (含 () 或 / 的中文)"""
    pat = re.compile(r"[一-鿿]+(?:\([^)]+\)|/)")
    for r in facts.references[:30]:
        if pat.search(r):
            sample = r[:60]
            return f"含中文机构作者 (BST 会拆为 first/last 名): {sample!r}"
    return None


def _rule_d39_textbox_caption(facts: DocxFacts) -> str | None:
    """D39: 客户用 Word 文本框 (txbxContent) 装图 caption — pandoc 不解析致丢失"""
    if facts.textbox_caption_count > 0:
        return (f"docx 含 {facts.textbox_caption_count} 个 textbox 内 '图X-Y' caption "
                f"— pandoc 不解析, recover_figures 用 textbox_captions.json 兜底 (CASE-A)")
    return None


def _rule_acknowledgement_placeholder(facts: DocxFacts) -> str | None:
    """非 D-编号: 致谢含 XX老师 / …… 占位符"""
    if not facts.acknowledgement:
        return None
    if re.search(r"XX[老教]师|……|…{2,}", facts.acknowledgement):
        return "致谢正文是占位符 — 客户需补真实致谢内容 (P0 不动客户原文, 仅告知)"
    return None


def _rule_keyword_count_exceed(facts: DocxFacts) -> str | None:
    """非 D-编号: 关键词超 5 (GB/T 7714 要求 ≤5)"""
    notes = []
    for zone, name, sep in [
        (facts.abstract_zh, "中文关键词", "，"),
        (facts.abstract_en, "英文关键词", ","),
    ]:
        m = re.search(r"(?:关键词|Keywords)[：:]\s*(.+)", zone)
        if not m:
            continue
        kw_str = m.group(1).strip()
        items = [k.strip() for k in re.split(r"[,，;；]", kw_str) if k.strip()]
        if len(items) > 5:
            notes.append(f"{name} {len(items)} 个 (要求 ≤5): {items}")
    return " / ".join(notes) if notes else None


# (D_id, status_override, description, rule_fn)
# status_override: 若 D 卡片在 dashboard 不存在或想覆盖
RULES: List[Tuple[str, str, str, Callable[[DocxFacts], "str | None"]]] = [
    ("D22", "", "摘要 % 被 LaTeX 注释吞段", _rule_d22),
    ("D23", "", "refs_to_bib 漏 [C][S][R][P][Z] 类型", _rule_d23),
    ("D24", "case_private", "\\nocite{*} bbl 顺序乱", _rule_d24),
    ("D25", "case_private", "BST 英文作者 'Last F' 错位", _rule_d25),
    ("D26", "case_private", "~ 字符被 LaTeX 当 nbsp 吞", _rule_d26),
    ("D27", "case_private", "本科 \\cite 默认行内不上标", _rule_d27),
    ("D28", "case_private", "缺 noreminder 致 CLS 红字泄漏", _rule_d28),
    ("D29", "case_private", "BST sentence-case 破坏化学式", _rule_d29),
    ("D30", "case_private", "publisher/journal & escape", _rule_d30),
    ("D31", "case_private", "中文机构作者 BST 拆名", _rule_d31),
    ("D39", "",              "Word textbox 装 caption 致 pandoc 丢失", _rule_d39_textbox_caption),
    ("",    "client_fix",    "致谢占位符 (客户需补)", _rule_acknowledgement_placeholder),
    ("",    "client_fix",    "关键词超 5 (客户需删)", _rule_keyword_count_exceed),
]


# ============================================================
# 主流程
# ============================================================

def load_dashboard(dashboard_path: str) -> Dict:
    if not os.path.isfile(dashboard_path):
        return {}
    try:
        with open(dashboard_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


STATUS_ICON = {
    "shared_code_fixed": ("✅", "已修 (产物不受影响, 流水线自动)"),
    "case_private":      ("⚠️", "candidate (需 case-private 干预或参考卡片修法)"),
    "pending":           ("❌", "未修 (需立即手动干预)"),
    "wontfix":           ("ℹ️", "wontfix (设计选择)"),
    "client_fix":        ("📝", "客户原稿瑕疵 (告知客户调整, 不擅改)"),
}


def run_router(docx_path: str, dashboard: Dict) -> List[Dict]:
    """跑全部 RULES, 返回 hit list."""
    facts = DocxFacts(docx_path)
    hits = []
    for d_id, status_override, desc, fn in RULES:
        evidence = fn(facts)
        if not evidence:
            continue
        if d_id and d_id in dashboard.get("by_defect", {}):
            card = dashboard["by_defect"][d_id]
            status = card.get("status", "pending")
            title = card.get("title", desc)
            fix_loc = card.get("fix_location", "")
            card_path = card.get("card_path", "")
        else:
            status = status_override or "pending"
            title = desc
            fix_loc = ""
            card_path = ""
        hits.append({
            "d_id": d_id or "(无编号)",
            "status": status,
            "title": title,
            "evidence": evidence,
            "fix_location": fix_loc,
            "card_path": card_path,
        })
    return hits


def format_report(hits: List[Dict], docx_path: str) -> str:
    out = []
    out.append("=" * 60)
    out.append(f"preflight_risk_router — input-side 风险预警 (Round 7 阶段 D / 5a)")
    out.append(f"docx: {docx_path}")
    out.append("=" * 60)
    if not hits:
        out.append("✅ 未检测到任何已知风险触发条件")
        out.append("=" * 60)
        return "\n".join(out)

    out.append(f"共扫到 {len(hits)} 项触发条件:\n")
    by_status: Dict[str, List[Dict]] = {}
    for h in hits:
        by_status.setdefault(h["status"], []).append(h)

    for status in ["pending", "client_fix", "case_private", "shared_code_fixed", "wontfix"]:
        items = by_status.get(status, [])
        if not items:
            continue
        icon, label = STATUS_ICON.get(status, ("•", status))
        out.append(f"--- {icon}  {label} ({len(items)} 项) ---")
        for h in items:
            out.append(f"  [{h['d_id']}] {h['title']}")
            out.append(f"      触发: {h['evidence']}")
            if h["fix_location"]:
                out.append(f"      修法: {h['fix_location']}")
            if h["card_path"]:
                out.append(f"      卡片: {h['card_path']}")
            out.append("")

    pending = sum(1 for h in hits if h["status"] in ("pending", "case_private"))
    out.append("-" * 60)
    if pending:
        out.append(
            f"⚠️  {pending} 项需要 case-private 干预 — 请走流水线时关注产物 audit"
        )
    out.append("注: router 不阻断流水线, 仅信息提供. 真正阻断在 product_audit (Step 6c).")
    out.append("=" * 60)
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Preflight risk router (5a)")
    ap.add_argument("docx", help="输入 docx 路径")
    ap.add_argument("--dashboard", default="", help="dashboard.json 路径 (默认推测)")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而非 human-readable")
    args = ap.parse_args()

    if not os.path.isfile(args.docx):
        print(f"❌ docx 不存在: {args.docx}", file=sys.stderr)
        sys.exit(2)

    dashboard_path = args.dashboard
    if not dashboard_path:
        # 默认推测: <repo>/reference/defects/dashboard.json
        cwd_parents = [os.getcwd()]
        for _ in range(4):
            cwd_parents.append(os.path.dirname(cwd_parents[-1]))
        for p in cwd_parents:
            cand = os.path.join(p, "reference", "defects", "dashboard.json")
            if os.path.isfile(cand):
                dashboard_path = cand
                break

    dashboard = load_dashboard(dashboard_path) if dashboard_path else {}
    hits = run_router(args.docx, dashboard)

    if args.json:
        print(json.dumps({"docx": args.docx, "hits": hits}, ensure_ascii=False, indent=2))
    else:
        print(format_report(hits, args.docx))

    sys.exit(0)  # router 永不阻断


if __name__ == "__main__":
    main()
