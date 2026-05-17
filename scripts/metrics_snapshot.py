"""Compute 北极星 rolling-window metrics + reverse stopping-criteria.

Reads `docs/thesis_registry.md` (case ledger) and `work/output_*/` (live signals)
for heuristic estimates, then overrides them with `docs/case_adjudication/CASE-XXX.yaml`
(ground truth) when available.

Outputs JSON snapshot with:

**Forward metrics** (北极星):
- `first_run_delivery_pass_rate`
- `B_P0_leakage_count_total`
- `manual_intervention_rate`

**Reverse stopping criteria** (Codex Round 2 提出):
- `new_shared_P0_family_rate`
- `new_D_card_rate`
- `regression_count` (requires --regression-failures arg or pytest report; default 0)
- `case_private_script_rate`

**Threshold check vs L2 / L3**: see `docs/tdd_stopping_criteria_2026-05-16.md`.

Usage:
    python metrics_snapshot.py \\
        [--registry <path>] [--work-root <path>] \\
        [--adjudication-dir <path>] \\
        [--window 10] [--output <path>] [--all]

Without `--output`, snapshot is written to stdout as pretty JSON.

`adjudication_dir` defaults to `docs/case_adjudication/`. If a `CASE-XXX.yaml`
exists there, its `round_1` values override heuristic estimates and the case
is marked `source: "adjudicated"`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None  # adjudication will be skipped with warning

DEFAULT_REGISTRY = None
DEFAULT_WORK_ROOT = None
DEFAULT_ADJUDICATION_DIR = None
CASE_HEADER_RE = re.compile(r"^#{2,4}\s+(CASE-[\w-]+)([^\n]*)", re.MULTILINE)
FIELD_BULLET_RE = re.compile(r"^\s*-\s*\*\*([^*]+?)\*\*\s*[:：]\s*(.*)", re.MULTILINE)
FIELD_TABLE_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|", re.MULTILINE)
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

B_P0_LEAK_KEYWORDS = [
    "客户视觉抽查发现",
    "客户视觉抽查砸场",
    "audit 全绿但客户",
    "lun51 检测发现",
    "B 类 P0",
    "B类 P0",
    "客户反馈 P0",
]


def split_cases(text: str) -> list[tuple[str, str, str]]:
    """Return [(case_id, header_tail, body), ...].

    Skips the template entry "CASE-XXX". `header_tail` is the remainder of
    the header line after the case_id (typically " : name (school, degree)").
    """
    matches = list(CASE_HEADER_RE.finditer(text))
    out = []
    for i, m in enumerate(matches):
        case_id = m.group(1)
        if case_id == "CASE-XXX":
            continue
        head_tail = m.group(2)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        out.append((case_id, head_tail, body))
    return out


def extract_fields(body: str) -> dict[str, str]:
    """Extract fields from both bullet (`- **k**: v`) and table (`| k | v |`) formats."""
    fields = {}
    for fm in FIELD_BULLET_RE.finditer(body):
        key = fm.group(1).strip()
        val = fm.group(2).strip()
        if key not in fields:
            fields[key] = val
    for fm in FIELD_TABLE_RE.finditer(body):
        key = fm.group(1).strip()
        val = fm.group(2).strip()
        if not key or set(key) <= {"-", ":"} or key in ("字段",):
            continue
        if key not in fields:
            fields[key] = val
    return fields


def dedupe_by_case_id(cases: list[dict]) -> list[dict]:
    """Keep earliest-date entry per case_id.

    Registry has multiple entries per case (rounds, returns), but
    'first_run_pass' should reflect the round-1 state.
    """
    by_id = {}
    for c in cases:
        cid = c["case_id"]
        if cid not in by_id:
            by_id[cid] = c
            continue
        existing = by_id[cid]
        new_date = c.get("date") or ""
        old_date = existing.get("date") or ""
        if new_date and (not old_date or new_date < old_date):
            by_id[cid] = c
    return list(by_id.values())


def parse_date(text: str) -> str | None:
    m = DATE_RE.search(text or "")
    return m.group(1) if m else None


def case_id_to_dir_tokens(case_id: str) -> list[str]:
    base = case_id.lower().replace("case-", "case")
    return [base, base.replace("case", "case_"), base.lstrip("0")]


def find_work_dirs(case_id: str, work_root: Path) -> list[Path]:
    tokens = case_id_to_dir_tokens(case_id)
    out = []
    if not work_root.is_dir():
        return out
    for sub in work_root.glob("output_*"):
        name = sub.name.lower()
        if any(tok in name for tok in tokens):
            out.append(sub)
    return out


def detect_manual_intervention(fields: dict, body: str, work_dirs: list[Path]) -> tuple[bool, list[str]]:
    """Returns (is_manual, evidence_list)."""
    evidence = []
    fix = fields.get("修复记录", "")
    if fix and fix.strip() not in ("", "无", "none", "-", "N/A"):
        evidence.append("registry: 修复记录 字段非空")
    for d in work_dirs:
        scripts = sorted(d.glob("_*round*.py")) + sorted(d.glob("_*fix*.py")) + sorted(d.glob("_case*.py"))
        if scripts:
            evidence.append(f"work scripts in {d.name}: {len(scripts)} files")
    return (bool(evidence), evidence)


def detect_b_p0_leakage_count(body: str) -> tuple[int, list[str]]:
    hits = []
    for kw in B_P0_LEAK_KEYWORDS:
        n = body.count(kw)
        if n:
            hits.append(f"'{kw}' x{n}")
    return (sum(int(h.split('x')[-1]) for h in hits) if hits else 0, hits)


def detect_result(fields: dict) -> str:
    raw = fields.get("结果", "")
    if "✅" in raw:
        return "success"
    if "⚠️" in raw:
        return "partial"
    if "❌" in raw:
        return "failed"
    return "unknown"


def derive_first_run_pass(result: str, manual: bool, leak: int) -> bool:
    return result == "success" and not manual and leak == 0


def detect_result_fallback(body: str) -> str:
    """Fallback when fields['结果'] absent: look for north_star §5 markers."""
    if "first_run_pass=Y" in body or "✅ **first_run_pass" in body:
        return "success"
    if "first_run_pass=N" in body:
        return "partial"
    return "unknown"


def load_adjudication(case_id: str, adj_dir: Path) -> dict | None:
    """Load `<adj_dir>/<case_id>.yaml` if present and PyYAML available."""
    if yaml is None or not adj_dir.is_dir():
        return None
    f = adj_dir / f"{case_id}.yaml"
    if not f.exists():
        return None
    try:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def build_case_snapshot(
    case_id: str, head_tail: str, body: str, work_root: Path, adj_dir: Path
) -> dict:
    fields = extract_fields(body)
    date = parse_date(fields.get("日期", "")) or parse_date(head_tail) or parse_date(body[:500])
    work_dirs = find_work_dirs(case_id, work_root)
    h_manual, manual_ev = detect_manual_intervention(fields, body, work_dirs)
    h_leak, leak_ev = detect_b_p0_leakage_count(body)
    result = detect_result(fields)
    if result == "unknown":
        result = detect_result_fallback(body)
    h_first_run = derive_first_run_pass(result, h_manual, h_leak)

    # Count case-private scripts for reverse metric (always heuristic from work/)
    case_private_count = 0
    for d in work_dirs:
        case_private_count += len(list(d.glob("_*round*.py"))) + len(list(d.glob("_*fix*.py"))) + len(list(d.glob("_case*.py")))

    # Ground-truth override
    adj = load_adjudication(case_id, adj_dir)
    new_p0_families: list[str] = []
    new_d_cards: list[str] = []
    family_variants: list[str] = []
    if adj:
        r1 = adj.get("round_1") or {}
        first_run = bool(r1.get("first_run_pass", h_first_run))
        leak = int(r1.get("B_P0_leakage_count", h_leak))
        manual = bool(r1.get("manual_intervention", h_manual))
        source = "adjudicated"
        adj_date = r1.get("date") or date
        # PyYAML parses ISO dates as datetime.date; normalize to ISO string
        if hasattr(adj_date, "isoformat"):
            adj_date = adj_date.isoformat()
        date = adj_date
        cls = adj.get("defect_classification") or {}
        new_p0_families = list(cls.get("new_shared_P0_families") or [])
        new_d_cards = list(cls.get("new_D_cards") or [])
        family_variants = list(cls.get("family_variants") or [])
    else:
        first_run = h_first_run
        leak = h_leak
        manual = h_manual
        source = "heuristic"

    return {
        "case_id": case_id,
        "header_tail": head_tail.strip(),
        "date": date,
        "profile": fields.get("Profile") or fields.get("profile") or "",
        "degree": fields.get("Degree") or fields.get("degree") or "",
        "result": result,
        "source": source,
        "first_run_pass": first_run,
        "manual_intervention": manual,
        "manual_intervention_evidence": manual_ev,
        "b_p0_leakage_count": leak,
        "b_p0_leakage_evidence": leak_ev,
        "case_private_script_count": case_private_count,
        "new_shared_P0_families": new_p0_families,
        "new_D_cards": new_d_cards,
        "family_variants": family_variants,
        "work_dirs": [d.name for d in work_dirs],
    }


def compute_rolling_metrics(cases: list[dict], window: int, regression_count: int = 0) -> dict:
    dated = [c for c in cases if c.get("date")]
    dated.sort(key=lambda c: c["date"], reverse=True)
    win = dated[:window]
    n = len(win)
    pass_n = sum(1 for c in win if c["first_run_pass"])
    leak_total = sum(c["b_p0_leakage_count"] for c in win)
    leak_case_n = sum(1 for c in win if c["b_p0_leakage_count"] > 0)
    manual_n = sum(1 for c in win if c["manual_intervention"])
    # Reverse stopping criteria
    new_p0_family_n = sum(len(c.get("new_shared_P0_families") or []) for c in win)
    new_d_card_n = sum(len(c.get("new_D_cards") or []) for c in win)
    case_private_script_n = sum(1 for c in win if c.get("case_private_script_count", 0) > 0)
    adjudicated_n = sum(1 for c in win if c.get("source") == "adjudicated")
    return {
        "window_size": n,
        "rolling_window_cases": [c["case_id"] for c in win],
        "adjudicated_count": adjudicated_n,
        "adjudication_coverage_pct": round(adjudicated_n * 100 / n, 1) if n else None,
        # Forward (北极星)
        "first_run_delivery_pass_rate": f"{pass_n}/{n}" if n else "N/A",
        "first_run_delivery_pass_ratio_pct": round(pass_n * 100 / n, 1) if n else None,
        "B_P0_leakage_cases_rate": f"{leak_case_n}/{n}" if n else "N/A",
        "B_P0_leakage_cases_ratio_pct": round(leak_case_n * 100 / n, 1) if n else None,
        "B_P0_leakage_count_total": leak_total,
        "manual_intervention_rate": f"{manual_n}/{n}" if n else "N/A",
        "manual_intervention_ratio_pct": round(manual_n * 100 / n, 1) if n else None,
        # Reverse (stopping criteria, Codex Round 2)
        "new_shared_P0_family_count": new_p0_family_n,
        "new_D_card_count": new_d_card_n,
        "regression_count": regression_count,
        "case_private_script_rate": f"{case_private_script_n}/{n}" if n else "N/A",
        "case_private_script_count": case_private_script_n,
    }


L2_THRESHOLDS = {
    "first_run_delivery_pass_rate_min_ratio": 0.80,  # ≥ 4/5
    "B_P0_leakage_cases_max": 0,  # = 0 cases with any leak
    "manual_intervention_rate_max_ratio": 0.20,  # ≤ 1/5
    "window_min": 5,
}

L3_THRESHOLDS = {
    "first_run_delivery_pass_rate_min_ratio": 0.90,  # ≥ 9/10
    "B_P0_leakage_cases_max": 1,  # ≤ 1 case with any leak
    "manual_intervention_rate_max_ratio": 0.10,  # ≤ 1/10
    "window_min": 10,
    "new_shared_P0_family_max_ratio": 0.10,  # ≤ 1/10
    "new_D_card_max_ratio": 0.30,  # ≤ 3/10
    "regression_count_max": 0,
    "case_private_script_max_ratio": 0.10,  # ≤ 1/10
    "non_overlapping_windows_required": 2,
}


def check_thresholds(metrics: dict, thresholds: dict, label: str) -> dict:
    n = metrics["window_size"]
    if n < thresholds.get("window_min", 1):
        return {"label": label, "ok": False, "reason": f"window {n} < required {thresholds.get('window_min')}", "failures": []}
    failures = []
    pass_ratio = (metrics["first_run_delivery_pass_ratio_pct"] or 0) / 100
    if pass_ratio < thresholds["first_run_delivery_pass_rate_min_ratio"]:
        failures.append(f"first_run_pass {pass_ratio:.2f} < {thresholds['first_run_delivery_pass_rate_min_ratio']}")
    leak_cases = int(metrics["B_P0_leakage_cases_rate"].split("/")[0]) if "/" in metrics["B_P0_leakage_cases_rate"] else 0
    if leak_cases > thresholds["B_P0_leakage_cases_max"]:
        failures.append(f"leak_cases {leak_cases} > {thresholds['B_P0_leakage_cases_max']}")
    manual_ratio = (metrics["manual_intervention_ratio_pct"] or 0) / 100
    if manual_ratio > thresholds["manual_intervention_rate_max_ratio"]:
        failures.append(f"manual {manual_ratio:.2f} > {thresholds['manual_intervention_rate_max_ratio']}")
    # Reverse (L3 only)
    if "new_shared_P0_family_max_ratio" in thresholds:
        rev_pf = metrics["new_shared_P0_family_count"] / max(n, 1)
        if rev_pf > thresholds["new_shared_P0_family_max_ratio"]:
            failures.append(f"new_P0_family {rev_pf:.2f} > {thresholds['new_shared_P0_family_max_ratio']}")
        rev_dc = metrics["new_D_card_count"] / max(n, 1)
        if rev_dc > thresholds["new_D_card_max_ratio"]:
            failures.append(f"new_D_card {rev_dc:.2f} > {thresholds['new_D_card_max_ratio']}")
        if metrics["regression_count"] > thresholds["regression_count_max"]:
            failures.append(f"regression {metrics['regression_count']} > {thresholds['regression_count_max']}")
        cp_count = metrics["case_private_script_count"]
        cp_ratio = cp_count / max(n, 1)
        if cp_ratio > thresholds["case_private_script_max_ratio"]:
            failures.append(f"case_private_script {cp_ratio:.2f} > {thresholds['case_private_script_max_ratio']}")
    return {"label": label, "ok": not failures, "failures": failures}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry", default=DEFAULT_REGISTRY)
    ap.add_argument("--work-root", default=DEFAULT_WORK_ROOT)
    ap.add_argument("--adjudication-dir", default=DEFAULT_ADJUDICATION_DIR)
    ap.add_argument("--window", type=int, default=10)
    ap.add_argument(
        "--regression-failures",
        type=int,
        default=0,
        help="Number of failing regression tests (from pytest report; default 0)",
    )
    ap.add_argument(
        "--output",
        default=None,
        help="Write JSON snapshot here (default: stdout)",
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="Include all parsed cases in JSON (default: only rolling window)",
    )
    args = ap.parse_args(argv)

    registry = Path(args.registry)
    if not registry.exists():
        print(f"ERROR: registry not found at {registry}", file=sys.stderr)
        return 2

    work_root = Path(args.work_root)
    adj_dir = Path(args.adjudication_dir)
    text = registry.read_text(encoding="utf-8")
    raw_cases = split_cases(text)
    all_entries = [
        build_case_snapshot(cid, ht, body, work_root, adj_dir)
        for cid, ht, body in raw_cases
    ]
    cases = dedupe_by_case_id(all_entries)

    metrics = compute_rolling_metrics(cases, args.window, args.regression_failures)

    # Threshold checks
    l2_check = check_thresholds(metrics, L2_THRESHOLDS, "L2 wave-exit")
    l3_check = check_thresholds(metrics, L3_THRESHOLDS, "L3 project-stop")

    snapshot = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "registry_path": str(registry),
        "work_root": str(work_root),
        "adjudication_dir": str(adj_dir),
        "yaml_available": yaml is not None,
        "total_entries_parsed": len(all_entries),
        "total_cases_after_dedupe": len(cases),
        "metrics": metrics,
        "thresholds": {
            "L2": l2_check,
            "L3": l3_check,
            "spec": "docs/tdd_stopping_criteria_2026-05-16.md",
        },
        "cases": cases if args.all else [
            c for c in cases if c["case_id"] in metrics["rolling_window_cases"]
        ],
    }

    out_text = json.dumps(snapshot, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(out_text, encoding="utf-8")
        print(f"Snapshot written to {args.output} ({len(cases)} cases parsed)")
    else:
        print(out_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
