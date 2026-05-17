"""Unit tests for auto_repair MVP (Day 7).

Pure-function tests — none of them invoke Docker or run an actual repair
loop. The end-to-end loop is exercised by Day 7's CASE-A sandbox run
and recorded in ``work/_v5_d7_repair_out/``.
"""

from __future__ import annotations
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import auto_repair as ar  # noqa: E402


# ---------------------------------------------------------------------------
# parse_figure_block
# ---------------------------------------------------------------------------


def _write_tex(tmp_path, name="x.tex", content=""):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_parse_figure_block_inside_figure(tmp_path):
    p = _write_tex(tmp_path, content=(
        "preamble\n"
        "\\begin{figure}[htbp]\n"          # line 2
        "    \\centering\n"
        "    \\includegraphics{img.png}\n"  # line 4
        "    \\caption{cap}\n"
        "\\end{figure}\n"                   # line 6
    ))
    result = ar.parse_figure_block(p, line_num=4)
    assert result is not None
    start, end, placement = result
    assert start == 2
    assert end == 6
    assert placement == "[htbp]"


def test_parse_figure_block_returns_none_outside_figure(tmp_path):
    p = _write_tex(tmp_path, content=(
        "Some prose paragraph.\n"           # line 1
        "\\begin{figure}[H]\n"
        "  \\caption{x}\n"
        "\\end{figure}\n"
        "Another paragraph.\n"              # line 5
    ))
    assert ar.parse_figure_block(p, line_num=1) is None
    assert ar.parse_figure_block(p, line_num=5) is None


def test_parse_figure_block_finds_outer_when_two_adjacent(tmp_path):
    """Line in the second figure must locate the second, not the first."""
    p = _write_tex(tmp_path, content=(
        "\\begin{figure}[H]\n"      # 1
        "img1\n"                     # 2
        "\\end{figure}\n"            # 3
        "between\n"                  # 4
        "\\begin{figure}[htbp]\n"    # 5
        "img2\n"                     # 6
        "\\end{figure}\n"            # 7
    ))
    r = ar.parse_figure_block(p, line_num=6)
    assert r == (5, 7, "[htbp]")
    r = ar.parse_figure_block(p, line_num=2)
    assert r == (1, 3, "[H]")
    # Line between two figures → no enclosing block
    assert ar.parse_figure_block(p, line_num=4) is None


def test_parse_figure_block_no_placement_returns_empty_string(tmp_path):
    p = _write_tex(tmp_path, content=(
        "\\begin{figure}\n"          # 1, no [H] / [htbp]
        "  ...\n"
        "\\end{figure}\n"
    ))
    r = ar.parse_figure_block(p, line_num=2)
    assert r is not None
    _, _, placement = r
    assert placement == ""


def test_parse_figure_block_out_of_range(tmp_path):
    p = _write_tex(tmp_path, content="single line\n")
    assert ar.parse_figure_block(p, line_num=99) is None
    assert ar.parse_figure_block(p, line_num=0) is None


# ---------------------------------------------------------------------------
# weighted_score
# ---------------------------------------------------------------------------


def test_weighted_score_sums_severity_weights():
    issues = [{"severity": "P0"}, {"severity": "P0"}, {"severity": "P1"},
              {"severity": "P2"}, {"severity": "?"}]
    assert ar.weighted_score(issues) == 1000 + 1000 + 100 + 10 + 0


def test_weighted_score_empty():
    assert ar.weighted_score([]) == 0


# ---------------------------------------------------------------------------
# float_policy_repair eligibility & no-op cases
# ---------------------------------------------------------------------------


def _issue(code="large_vertical_gap", repairability="deterministic",
           tex_file="chapter/ch01.tex", tex_line=4, page=10):
    return {
        "issue_id": "VIS-LARGE_VE-0001",
        "issue_code": code,
        "severity": "P0",
        "repairability": repairability,
        "location": {"pdf_page": page, "tex_file": tex_file,
                     "tex_line": tex_line},
        "evidence": {"gap_pt": 100, "threshold_pt": 70,
                     "prev_block_text": "x", "next_block_text": "y"},
    }


def test_float_policy_repair_rejects_wrong_issue_code(tmp_path):
    workdir = tmp_path
    (workdir / "chapter").mkdir()
    _write_tex(workdir / "chapter", "ch01.tex",
               "\\begin{figure}[H]\n  ...\n\\end{figure}\n")
    out = ar.float_policy_repair(_issue(code="some_other"), workdir)
    assert out is None


def test_float_policy_repair_rejects_non_deterministic(tmp_path):
    workdir = tmp_path
    (workdir / "chapter").mkdir()
    _write_tex(workdir / "chapter", "ch01.tex",
               "\\begin{figure}[H]\n  ...\n\\end{figure}\n")
    out = ar.float_policy_repair(_issue(repairability="trial"), workdir)
    assert out is None


def test_float_policy_repair_diagnostic_when_outside_figure(tmp_path):
    workdir = tmp_path
    (workdir / "chapter").mkdir()
    _write_tex(workdir / "chapter", "ch01.tex",
               "Plain prose.\n")  # line 1 not inside figure
    out = ar.float_policy_repair(_issue(tex_line=1), workdir)
    assert out is not None
    assert out["status"] == "diagnostic"
    assert "not inside a figure" in out["reason"]


def test_float_policy_repair_diagnostic_when_no_synctex_location(tmp_path):
    workdir = tmp_path
    issue = _issue()
    issue["location"]["tex_line"] = None
    out = ar.float_policy_repair(issue, workdir)
    assert out and out["status"] == "diagnostic"
    assert "SyncTeX" in out["reason"] or "tex_line" in out["reason"]


# ---------------------------------------------------------------------------
# Day 13A: equation_gap subtype guard. Belt-and-suspenders — even if a caller
# bypasses the repairability check, the explicit subtype check refuses.
# ---------------------------------------------------------------------------


def test_float_policy_repair_rejects_equation_gap_subtype(tmp_path):
    """An issue with evidence.subtype=equation_gap must be refused even if
    the caller forgot to filter by repairability. Belt-and-suspenders for
    the 9 wrong-fix candidates from Day 12."""
    workdir = tmp_path
    (workdir / "chapter").mkdir()
    _write_tex(workdir / "chapter", "ch01.tex",
               "\\begin{figure}[H]\n  ...\n\\end{figure}\n")
    issue = _issue(repairability="deterministic")  # would normally pass
    issue["evidence"]["subtype"] = "equation_gap"
    out = ar.float_policy_repair(issue, workdir)
    assert out is None, "equation_gap must be refused even if repairability=deterministic"


def test_float_policy_repair_accepts_float_gap_subtype(tmp_path):
    """Float_gap subtype must NOT be refused — the auto-repair pipeline
    still owns this path for genuine figure-float gaps."""
    workdir = tmp_path
    (workdir / "chapter").mkdir()
    _write_tex(workdir / "chapter", "ch01.tex",
               "Plain prose.\n")  # outside figure → diagnostic, not None
    issue = _issue(repairability="deterministic", tex_line=1)
    issue["evidence"]["subtype"] = "float_gap"
    out = ar.float_policy_repair(issue, workdir)
    # Not None (means subtype guard didn't reject); diagnostic because
    # line 1 isn't inside a figure environment in this fixture.
    assert out is not None
    assert out["status"] == "diagnostic"


def test_float_policy_repair_no_subtype_falls_through_to_repairability(tmp_path):
    """Issues without subtype (legacy / pre-Day-13 contracts elsewhere)
    must still be filtered by repairability — backward compat."""
    workdir = tmp_path
    (workdir / "chapter").mkdir()
    _write_tex(workdir / "chapter", "ch01.tex",
               "\\begin{figure}[H]\n  ...\n\\end{figure}\n")
    issue = _issue(repairability="trial")
    # No subtype set
    out = ar.float_policy_repair(issue, workdir)
    assert out is None  # rejected by repairability check, not subtype check


# ---------------------------------------------------------------------------
# float_policy_repair: ready plans
# ---------------------------------------------------------------------------


def _make_workdir_with_figure(tmp_path, placement="[H]", floatbarrier_present=False,
                              placeins_loaded=False):
    """Build a minimal sandbox with a figure environment + main.tex."""
    (tmp_path / "chapter").mkdir()
    fb_lines = ""
    if floatbarrier_present:
        fb_lines = ar.FLOATBARRIER_MARKER + "\n\\FloatBarrier\n"
    ch_text = (
        "\\section{x}\n"
        "para text\n"
        f"\\begin{{figure}}{placement}\n"     # line 3
        "  \\centering\n"
        "  \\includegraphics{x.png}\n"        # line 5
        "  \\caption{c}\n"
        "\\end{figure}\n"                     # line 7
        + fb_lines +
        "after\n"
    )
    _write_tex(tmp_path / "chapter", "ch01.tex", ch_text)

    placeins_line = (ar.PLACEINS_PREAMBLE_MARKER + "\n\\usepackage{placeins}\n"
                     if placeins_loaded else "")
    main_text = (
        "\\documentclass{article}\n"
        "\\usepackage{graphicx}\n"
        f"{placeins_line}"
        "\\begin{document}\n\\input{chapter/ch01}\n\\end{document}\n"
    )
    _write_tex(tmp_path, "main.tex", main_text)
    return tmp_path


def test_float_policy_repair_changes_H_to_htbp_and_adds_floatbarrier(tmp_path):
    wd = _make_workdir_with_figure(tmp_path, placement="[H]")
    issue = _issue(tex_file="chapter/ch01.tex", tex_line=5)
    plan = ar.float_policy_repair(issue, wd)
    assert plan["status"] == "ready"
    types = {a["type"] for a in plan["actions"]}
    assert "placement_change" in types
    assert "insert_floatbarrier_after_figure" in types
    # Two files touched: the figure file AND main.tex (placeins enabler)
    assert len(plan["touched_files"]) == 2


def test_float_policy_repair_skips_placement_when_already_htbp(tmp_path):
    wd = _make_workdir_with_figure(tmp_path, placement="[!htbp]")
    issue = _issue(tex_file="chapter/ch01.tex", tex_line=5)
    plan = ar.float_policy_repair(issue, wd)
    assert plan["status"] == "ready"
    types = {a["type"] for a in plan["actions"]}
    assert "placement_change" not in types
    assert "insert_floatbarrier_after_figure" in types


def test_float_policy_repair_idempotent_when_floatbarrier_present(tmp_path):
    wd = _make_workdir_with_figure(tmp_path, placement="[!htbp]",
                                   floatbarrier_present=True,
                                   placeins_loaded=True)
    issue = _issue(tex_file="chapter/ch01.tex", tex_line=5)
    plan = ar.float_policy_repair(issue, wd)
    assert plan["status"] == "diagnostic"
    assert "already" in plan["reason"].lower()


def test_float_policy_repair_skips_placeins_enabler_when_already_loaded(tmp_path):
    wd = _make_workdir_with_figure(tmp_path, placement="[H]",
                                   placeins_loaded=True)
    issue = _issue(tex_file="chapter/ch01.tex", tex_line=5)
    plan = ar.float_policy_repair(issue, wd)
    assert plan["status"] == "ready"
    # main.tex must NOT be in touched_files since placeins is loaded already
    main_path = str((wd / "main.tex").resolve())
    touched = {str(Path(p).resolve()) for p in plan["touched_files"]}
    assert main_path not in touched


# ---------------------------------------------------------------------------
# Day 8: prev-sibling figure detection + multi-insertion ordering
# ---------------------------------------------------------------------------


def test_find_prev_sibling_figure_simple_pair(tmp_path):
    p = _write_tex(tmp_path, content=(
        "\\begin{figure}[htbp]\n"     # 1: prev start
        "  imgA\n"
        "\\end{figure}\n"              # 3: prev end
        "\n"
        "tiny prose\n"                 # 5
        "\n"
        "\\begin{figure}[htbp]\n"     # 7: target start
        "  imgB\n"
        "\\end{figure}\n"
    ))
    sib = ar._find_prev_sibling_figure(p, target_start_line=7)
    assert sib == (1, 3)


def test_find_prev_sibling_figure_blocked_by_section_heading(tmp_path):
    p = _write_tex(tmp_path, content=(
        "\\begin{figure}[htbp]\n"     # 1
        "  imgA\n"
        "\\end{figure}\n"              # 3
        "\\section{Boundary}\n"        # 4 — heading boundary
        "\\begin{figure}[htbp]\n"     # 5: target
        "\\end{figure}\n"
    ))
    sib = ar._find_prev_sibling_figure(p, target_start_line=5)
    assert sib is None


def test_find_prev_sibling_figure_too_far(tmp_path):
    """If gap exceeds max_gap_lines, refuse."""
    body = ["body line"] * 50
    content = (
        "\\begin{figure}[htbp]\n"
        "imgA\n"
        "\\end{figure}\n"
        + "\n".join(body) + "\n"
        + "\\begin{figure}[htbp]\n"
        + "\\end{figure}\n"
    )
    p = _write_tex(tmp_path, content=content)
    target_start = 3 + len(body) + 1
    assert ar._find_prev_sibling_figure(p, target_start_line=target_start,
                                         max_gap_lines=10) is None


def test_find_prev_sibling_figure_no_prev_returns_none(tmp_path):
    p = _write_tex(tmp_path, content=(
        "first prose\n"
        "\\begin{figure}[htbp]\n"     # 2: target, no sibling before
        "\\end{figure}\n"
    ))
    sib = ar._find_prev_sibling_figure(p, target_start_line=2)
    assert sib is None


def test_float_policy_repair_emits_three_actions_for_two_siblings(tmp_path):
    """When [H] target follows a sibling: placement_change +
    floatbarrier_after_target + floatbarrier_via_prev_sibling = 3 actions."""
    (tmp_path / "chapter").mkdir()
    _write_tex(tmp_path / "chapter", "ch01.tex", (
        "\\begin{figure}[htbp]\n"     # 1
        "  imgA\n"
        "\\end{figure}\n"              # 3
        "\n"
        "prose\n"                      # 5
        "\n"
        "\\begin{figure}[H]\n"         # 7: target with [H]
        "  \\includegraphics{x}\n"     # 8
        "\\end{figure}\n"              # 9
    ))
    _write_tex(tmp_path, "main.tex", (
        "\\documentclass{article}\n"
        "\\usepackage{graphicx}\n"
        "\\begin{document}\n\\input{chapter/ch01}\n\\end{document}\n"
    ))
    issue = _issue(tex_file="chapter/ch01.tex", tex_line=8)
    plan = ar.float_policy_repair(issue, tmp_path)
    assert plan["status"] == "ready"
    types = {a["type"] for a in plan["actions"]}
    assert "placement_change" in types
    assert "insert_floatbarrier_after_figure" in types
    assert "insert_floatbarrier_before_target_via_prev_sibling" in types


def test_float_policy_repair_no_sibling_when_section_in_between(tmp_path):
    (tmp_path / "chapter").mkdir()
    _write_tex(tmp_path / "chapter", "ch01.tex", (
        "\\begin{figure}[htbp]\n"     # 1
        "imgA\n"
        "\\end{figure}\n"              # 3
        "\\section{Boundary}\n"        # 4
        "\\begin{figure}[htbp]\n"     # 5: target
        "  \\includegraphics{x}\n"
        "\\end{figure}\n"              # 7
    ))
    _write_tex(tmp_path, "main.tex",
               "\\documentclass{article}\n\\usepackage{graphicx}\n"
               "\\begin{document}\n\\input{chapter/ch01}\n\\end{document}\n")
    issue = _issue(tex_file="chapter/ch01.tex", tex_line=6)
    plan = ar.float_policy_repair(issue, tmp_path)
    assert plan["status"] == "ready"
    types = {a["type"] for a in plan["actions"]}
    # Sibling barrier should NOT be in actions when section heading separates
    assert "insert_floatbarrier_before_target_via_prev_sibling" not in types
    # But the after-target barrier still applies
    assert "insert_floatbarrier_after_figure" in types


def test_descending_insertion_order_preserves_correctness(tmp_path):
    """Insertions ordered by descending line so earlier indices stay valid.
    Verify the resulting file has both barriers at the correct logical
    positions (not shifted off-by-one)."""
    (tmp_path / "chapter").mkdir()
    _write_tex(tmp_path / "chapter", "ch01.tex", (
        "\\begin{figure}[htbp]\n"     # 1
        "imgA\n"
        "\\end{figure}\n"              # 3 — prev sibling end
        "\n"
        "prose\n"                      # 5
        "\n"
        "\\begin{figure}[htbp]\n"     # 7 — target start
        "  \\includegraphics{x}\n"     # 8
        "\\end{figure}\n"              # 9 — target end
        "after\n"
    ))
    _write_tex(tmp_path, "main.tex",
               "\\documentclass{article}\n\\usepackage{graphicx}\n"
               "\\begin{document}\n\\input{chapter/ch01}\n\\end{document}\n")
    issue = _issue(tex_file="chapter/ch01.tex", tex_line=8)
    plan = ar.float_policy_repair(issue, tmp_path)
    assert plan["status"] == "ready"

    ar.apply_plan(plan)
    out = (tmp_path / "chapter/ch01.tex").read_text(encoding="utf-8").splitlines()
    # Expected layout after insertion:
    # 1 \begin{figure}[htbp]
    # 2 imgA
    # 3 \end{figure}
    # 4 % v5-auto-repair: float_policy_repair (idempotent)
    # 5 \FloatBarrier
    # 6 (blank)
    # 7 prose
    # 8 (blank)
    # 9 \begin{figure}[htbp]
    # 10 \includegraphics{x}
    # 11 \end{figure}
    # 12 % marker
    # 13 \FloatBarrier
    # 14 after
    assert out[2].strip() == "\\end{figure}"
    assert out[3] == ar.FLOATBARRIER_MARKER
    assert out[4].strip() == "\\FloatBarrier"
    assert out[10].strip() == "\\end{figure}"
    assert out[11] == ar.FLOATBARRIER_MARKER
    assert out[12].strip() == "\\FloatBarrier"


# ---------------------------------------------------------------------------
# Apply / rollback round-trip
# ---------------------------------------------------------------------------


def test_apply_then_rollback_restores_byte_exact(tmp_path):
    wd = _make_workdir_with_figure(tmp_path, placement="[H]")
    issue = _issue(tex_file="chapter/ch01.tex", tex_line=5)

    before_ch = (wd / "chapter/ch01.tex").read_bytes()
    before_main = (wd / "main.tex").read_bytes()

    plan = ar.float_policy_repair(issue, wd)
    ar.apply_plan(plan)
    after_ch = (wd / "chapter/ch01.tex").read_bytes()
    assert after_ch != before_ch  # actually changed

    ar.rollback_plan(plan)
    assert (wd / "chapter/ch01.tex").read_bytes() == before_ch
    assert (wd / "main.tex").read_bytes() == before_main


# ---------------------------------------------------------------------------
# Plan hash determinism
# ---------------------------------------------------------------------------


def test_plan_hash_deterministic_for_same_input(tmp_path):
    wd = _make_workdir_with_figure(tmp_path, placement="[H]")
    issue = _issue(tex_file="chapter/ch01.tex", tex_line=5)
    plan_a = ar.float_policy_repair(issue, wd)
    # Recompute against the same baseline (no apply): should be identical
    plan_b = ar.float_policy_repair(issue, wd)
    assert plan_a["plan_hash"] == plan_b["plan_hash"]


# ---------------------------------------------------------------------------
# Acceptance evaluator
# ---------------------------------------------------------------------------


def test_acceptance_full_success_when_target_gone_and_no_new_p0():
    target = {"issue_code": "large_vertical_gap",
              "location": {"pdf_page": 10}}
    audit_before = {"issues": [target]}
    audit_after = {"issues": []}
    decision = ar.evaluate_acceptance(target, score_before=1000,
                                      audit_after=audit_after, score_after=0,
                                      audit_before=audit_before)
    assert decision["outcome"] == "full_success"
    assert decision["accepted"] is True
    assert decision["target_gone"] is True


def test_acceptance_partial_success_when_score_drops_target_remains():
    target = {"issue_code": "large_vertical_gap",
              "location": {"pdf_page": 10}}
    other = {"issue_code": "orphan_heading_at_page_bottom",
             "location": {"pdf_page": 9},
             "severity": "P0"}
    audit_before = {"issues": [target, other]}
    audit_after = {"issues": [target]}
    decision = ar.evaluate_acceptance(target, score_before=2000,
                                      audit_after=audit_after, score_after=1000,
                                      audit_before=audit_before)
    assert decision["outcome"] == "partial_success"
    assert decision["accepted"] is True
    assert decision["target_gone"] is False
    assert decision["score_dropped"] is True
    assert decision["no_new_p0"] is True


def test_acceptance_rejected_new_p0_overrides_target_gone():
    """Day 8: even if target disappears, introducing a new P0 elsewhere
    must reject (no collateral damage allowed)."""
    target = {"issue_code": "large_vertical_gap",
              "location": {"pdf_page": 10}}
    new_p0 = {"issue_code": "image_caption_split_page",
              "location": {"pdf_page": 22},
              "severity": "P0"}
    audit_before = {"issues": [target]}
    audit_after = {"issues": [new_p0]}
    decision = ar.evaluate_acceptance(target, score_before=1000,
                                      audit_after=audit_after, score_after=1000,
                                      audit_before=audit_before)
    assert decision["outcome"] == "rejected_new_p0"
    assert decision["accepted"] is False


def test_acceptance_rejected_no_progress_when_score_unchanged():
    target = {"issue_code": "large_vertical_gap",
              "location": {"pdf_page": 10}}
    audit_before = {"issues": [target]}
    audit_after = {"issues": [target]}
    decision = ar.evaluate_acceptance(target, score_before=1000,
                                      audit_after=audit_after, score_after=1000,
                                      audit_before=audit_before)
    assert decision["outcome"] == "rejected_no_progress"
    assert decision["accepted"] is False


def test_acceptance_outcome_field_always_present():
    """Schema stability: outcome must exist on every decision dict."""
    target = {"issue_code": "x", "location": {"pdf_page": 1}}
    decision = ar.evaluate_acceptance(target, score_before=0,
                                      audit_after={"issues": []},
                                      score_after=0,
                                      audit_before={"issues": [target]})
    assert "outcome" in decision
    assert decision["outcome"] in {
        "full_success", "partial_success",
        "rejected_new_p0", "rejected_no_progress",
    }


# ---------------------------------------------------------------------------
# Day 15: bounded backtrack from SyncTeX-into-post-figure-body case.
# Driven by Day 14 finding (case 11 ch04.tex:327 — line in body AFTER
# \end{figure}). Helper crosses ONLY blank/comment lines; refuses on any
# structural marker (heading, table, display math, body prose).
# ---------------------------------------------------------------------------


def _write_chapter(workdir: Path, content: str) -> Path:
    """Convenience: build a workdir with chapter/ch01.tex + main.tex."""
    (workdir / "chapter").mkdir(exist_ok=True)
    p = workdir / "chapter" / "ch01.tex"
    p.write_text(content, encoding="utf-8")
    (workdir / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    return p


def _float_gap_issue(tex_line: int, **kw):
    """Issue with evidence.subtype=float_gap (the only subtype eligible for
    backtrack). Helper layers on top of the existing _issue() factory."""
    issue = _issue(tex_line=tex_line, **kw)
    issue["evidence"]["subtype"] = "float_gap"
    return issue


def test_backtrack_unused_when_line_already_inside_figure(tmp_path):
    """Day 7 path stays unchanged: line inside figure → no backtrack."""
    _write_chapter(tmp_path,
        "preamble\n"
        "\\begin{figure}[H]\n"          # line 2
        "    \\centering\n"
        "    \\includegraphics{img.png}\n"  # line 4 — SyncTeX hit
        "    \\caption{c}\n"
        "    \\label{fig:x}\n"
        "\\end{figure}\n"               # line 7
        "post-figure prose.\n"
    )
    issue = _float_gap_issue(tex_line=4)
    plan = ar.float_policy_repair(issue, tmp_path)
    assert plan["status"] == "ready"
    # No backtrack metadata set when the figure was located directly
    assert "resolution_adjustment" not in plan
    assert "anchor_tex_line" not in plan
    assert plan["figure_block"]["start_line"] == 2
    assert plan["figure_block"]["end_line"] == 7


def test_backtrack_succeeds_one_blank_line_after_end_figure(tmp_path):
    """Most common SyncTeX case: 1 blank line then body para — backtrack."""
    _write_chapter(tmp_path,
        "\\begin{figure}[H]\n"          # 1
        "    \\centering\n"
        "    \\includegraphics{img.png}\n"
        "    \\caption{c}\n"
        "    \\label{fig:x}\n"
        "\\end{figure}\n"               # 6
        "\n"                              # 7 blank
        "Body paragraph after figure.\n"  # 8 — SyncTeX hit
    )
    issue = _float_gap_issue(tex_line=8)
    plan = ar.float_policy_repair(issue, tmp_path)
    assert plan["status"] == "ready"
    assert plan["resolution_adjustment"] == "backtrack_from_post_figure_text"
    assert plan["original_tex_line"] == 8
    assert plan["figure_end_line"] == 6
    assert plan["anchor_tex_line"] == 5
    assert plan["figure_block"]["end_line"] == 6


def test_backtrack_succeeds_two_blank_lines(tmp_path):
    """Two blank lines is still pure-blank — backtrack should succeed."""
    _write_chapter(tmp_path,
        "\\begin{figure}[H]\n"          # 1
        "    \\centering\n"
        "    \\includegraphics{img.png}\n"
        "    \\caption{c}\n"
        "    \\label{fig:x}\n"
        "\\end{figure}\n"               # 6
        "\n"                              # 7 blank
        "\n"                              # 8 blank
        "Body paragraph.\n"             # 9 SyncTeX hit
    )
    issue = _float_gap_issue(tex_line=9)
    plan = ar.float_policy_repair(issue, tmp_path)
    assert plan["status"] == "ready"
    assert plan["figure_end_line"] == 6
    assert plan["anchor_tex_line"] == 5


def test_backtrack_crosses_pure_comment_lines(tmp_path):
    """Pure-% comments are allowed pass-through (latex idiomatic spacing)."""
    _write_chapter(tmp_path,
        "\\begin{figure}[H]\n"          # 1
        "    \\centering\n"
        "    \\includegraphics{img.png}\n"
        "    \\caption{c}\n"
        "    \\label{fig:x}\n"
        "\\end{figure}\n"               # 6
        "% spacer comment\n"            # 7
        "%\n"                              # 8
        "Body paragraph.\n"             # 9
    )
    issue = _float_gap_issue(tex_line=9)
    plan = ar.float_policy_repair(issue, tmp_path)
    assert plan["status"] == "ready"
    assert plan["figure_end_line"] == 6


def test_backtrack_rejects_intervening_body_prose(tmp_path):
    """Body prose between tex_line and \\end{figure} → diagnostic.
    We won't reach across an intervening paragraph."""
    _write_chapter(tmp_path,
        "\\begin{figure}[H]\n"          # 1
        "    \\centering\n"
        "    \\includegraphics{img.png}\n"
        "    \\caption{c}\n"
        "\\end{figure}\n"               # 5
        "first paragraph after figure\n"  # 6 — body line
        "\n"                              # 7
        "second paragraph hit\n"        # 8 — SyncTeX hit
    )
    issue = _float_gap_issue(tex_line=8)
    plan = ar.float_policy_repair(issue, tmp_path)
    assert plan["status"] == "diagnostic"
    assert "no safe backtrack" in plan["reason"]


def test_backtrack_rejects_intervening_section_heading(tmp_path):
    """Section / chapter / heading in the gap → diagnostic. Patching the
    earlier figure could be patching a wrong-section figure."""
    _write_chapter(tmp_path,
        "\\begin{figure}[H]\n"          # 1
        "    \\centering\n"
        "    \\includegraphics{img.png}\n"
        "    \\caption{c}\n"
        "\\end{figure}\n"               # 5
        "\n"
        "\\section{New Section}\n"       # 7 — heading
        "\n"
        "body line in new section\n"    # 9 SyncTeX hit
    )
    issue = _float_gap_issue(tex_line=9)
    plan = ar.float_policy_repair(issue, tmp_path)
    assert plan["status"] == "diagnostic"
    assert "no safe backtrack" in plan["reason"]


def test_backtrack_rejects_intervening_display_math(tmp_path):
    """\\begin{equation} or \\[ \\] between figure and tex_line → diagnostic.
    Display math has its own large gaps; auto-repair must not mistake them."""
    _write_chapter(tmp_path,
        "\\begin{figure}[H]\n"          # 1
        "    \\centering\n"
        "    \\includegraphics{img.png}\n"
        "    \\caption{c}\n"
        "\\end{figure}\n"               # 5
        "\\begin{equation}\n"            # 6 — display math
        "    a = b\n"
        "\\end{equation}\n"
        "\n"
        "body line\n"                    # 10 SyncTeX hit
    )
    issue = _float_gap_issue(tex_line=10)
    plan = ar.float_policy_repair(issue, tmp_path)
    assert plan["status"] == "diagnostic"
    assert "no safe backtrack" in plan["reason"]


def test_backtrack_rejects_when_end_figure_beyond_max_back(tmp_path):
    """\\end{figure} is more than 10 blank lines above tex_line → diagnostic.
    Bounded scan caps at max_back=10 — no spurious distant matches."""
    blanks = "\n" * 12  # 12 blank lines
    _write_chapter(tmp_path,
        "\\begin{figure}[H]\n"          # 1
        "    \\centering\n"
        "    \\includegraphics{img.png}\n"
        "    \\caption{c}\n"
        "\\end{figure}\n"               # 5
        + blanks +                        # lines 6..17 (12 blanks)
        "body line very far below\n"   # 18 SyncTeX hit
    )
    issue = _float_gap_issue(tex_line=18)
    plan = ar.float_policy_repair(issue, tmp_path)
    assert plan["status"] == "diagnostic"
    assert "no safe backtrack" in plan["reason"]


def test_backtrack_does_not_apply_to_equation_gap_subtype(tmp_path):
    """equation_gap subtype must keep being rejected upstream by the
    Day 13A guard, never reach the backtrack helper."""
    _write_chapter(tmp_path,
        "\\begin{figure}[H]\n"
        "    \\includegraphics{img.png}\n"
        "    \\caption{c}\n"
        "\\end{figure}\n"               # line 4
        "\n"
        "(3.6)\n"                       # line 6 — SyncTeX hit (equation tag)
    )
    issue = _issue(tex_line=6)
    issue["evidence"]["subtype"] = "equation_gap"
    plan = ar.float_policy_repair(issue, tmp_path)
    # Subtype guard refuses BEFORE the backtrack path is considered
    assert plan is None


def test_case11_ch04_line_327_shape_produces_ready_plan(tmp_path):
    """Day 14 finding fixture: case 11 ch04.tex:327 was the body line
    immediately after \\end{figure} (line 325). Reproduce the exact shape
    and confirm Day 15 backtrack produces a ready plan."""
    # Mirror the actual ch04.tex layout around figure 4.3:
    #   prologue line introduces the figure
    #   \begin{figure}[H] ... \end{figure}
    #   blank line
    #   body paragraph "在图4.3中可以看到..."
    _write_chapter(tmp_path,
        "Some prior body context.\n"
        "\n"
        "仿真实验2: 噪声标准差关系。图4.3展示RMSE。\n"
        "\n"
        "\n"
        "\\begin{figure}[H]\n"
        "    \\centering\n"
        "    \\includegraphics[width=0.7\\textwidth]{media/image10.png}\n"
        "    \\caption{各算法的RMSE与高斯白噪声标准差的关系}\n"
        "    \\label{fig:4.3}\n"
        "\\end{figure}\n"
        "\n"
        "在图4.3中可以看到，当不存在离群值测量，仅存在...\n"  # SyncTeX hit
    )
    # 1: Some prior body context.
    # 2: blank
    # 3: 仿真实验2...
    # 4: blank
    # 5: blank
    # 6: \begin{figure}[H]
    # 7-10: figure body
    # 11: \end{figure}
    # 12: blank
    # 13: 在图4.3中... ← SyncTeX target line
    issue = _float_gap_issue(tex_line=13)
    plan = ar.float_policy_repair(issue, tmp_path)
    assert plan["status"] == "ready", plan
    assert plan["resolution_adjustment"] == "backtrack_from_post_figure_text"
    assert plan["original_tex_line"] == 13
    assert plan["figure_end_line"] == 11
    assert plan["anchor_tex_line"] == 10
    # Plan still does the standard Day 7 fix (placement + FloatBarrier)
    action_types = {a["type"] for a in plan["actions"]}
    assert "placement_change" in action_types
    assert "insert_floatbarrier_after_figure" in action_types
    # Idempotency: plan_hash is deterministic & non-empty
    assert plan["plan_hash"] and len(plan["plan_hash"]) == 16


# ---------------------------------------------------------------------------
# Day 17: contraindication guard.
# Day 16 实测 in case 11: target figure with [H] + prev sibling figure within
# max_gap_lines + post-figure backtrack — produces rejected_no_progress.
# Until strategy redesign, refuse this shape early as diagnostic-only.
# ---------------------------------------------------------------------------


def test_contraindication_two_adjacent_H_figures_short_prose_post_backtrack(tmp_path):
    """Day 16 case 11 ch04.tex shape (figure 4-2 / 4-3 紧邻 + [H] + post-figure
    backtrack). Day 15 alone would have produced ready plan; Day 17 must
    refuse with strategy_contraindicated_adjacent_figures."""
    _write_chapter(tmp_path,
        "Some prior context.\n"                                  # 1
        "\n"                                                       # 2
        "\\begin{figure}[H]\n"                                    # 3 fig 1
        "    \\centering\n"
        "    \\includegraphics{img1.png}\n"
        "    \\caption{First figure}\n"
        "\\end{figure}\n"                                         # 7
        "\n"                                                       # 8
        "Short paragraph between figures, two-three lines.\n"   # 9
        "\n"                                                       # 10
        "\\begin{figure}[H]\n"                                    # 11 fig 2 (target)
        "    \\centering\n"
        "    \\includegraphics{img2.png}\n"
        "    \\caption{Second figure}\n"
        "    \\label{fig:second}\n"
        "\\end{figure}\n"                                         # 16
        "\n"                                                       # 17
        "Body paragraph after second figure.\n"                  # 18 SyncTeX hit
    )
    # tex_line=18: parse_figure_block None (line 18 outside figure)
    # → backtrack → \end{figure}@16, anchor=15
    # → parse_figure_block(15) → figure 11-16, placement="[H]"
    # → sibling = figure 3-7 found (within max_gap_lines=30)
    # → all 3 conditions met → contraindication guard fires
    issue = _float_gap_issue(tex_line=18)
    plan = ar.float_policy_repair(issue, tmp_path)
    assert plan["status"] == "diagnostic"
    assert plan["reason"].startswith(
        "strategy_contraindicated_adjacent_figures")
    # Diagnostic metadata is structured for audit log
    meta = plan["diagnostic_meta"]
    assert meta["guard"] == "strategy_contraindicated_adjacent_figures"
    assert meta["target_figure_block"]["start_line"] == 11
    assert meta["target_figure_block"]["end_line"] == 16
    assert meta["target_figure_block"]["original_placement"] == "[H]"
    assert meta["prev_sibling_figure_block"]["start_line"] == 3
    assert meta["prev_sibling_figure_block"]["end_line"] == 7
    assert meta["resolution_adjustment"] == "backtrack_from_post_figure_text"
    assert meta["original_tex_line"] == 18
    assert meta["anchor_tex_line"] == 15
    assert meta["figure_end_line"] == 16


def test_day18_case16_vis0003_next_sibling_now_diagnostic(tmp_path):
    """Day 19 closes the next-sibling guard hole found on Day 18.

    Day 18 triage: case 16 VIS-LARGE_VE-0003 in ch03.tex showed the
    *next-direction* mirror of case 11's pathology — target figure
    219-224 [H] with figure 229-234 only 5 lines downstream. Day 17
    contraindication guard only checked prev sibling, so VIS-0003
    appeared as ready plan. Day 19 _find_next_sibling_figure closes
    the hole: this fixture (mirroring case 16 ch03.tex shape) MUST
    now produce diagnostic with sibling_direction='next'."""
    _write_chapter(tmp_path,
        "Some prior context.\n"                                  # 1
        "\n"                                                       # 2
        "Setup paragraph mentioning the figure.\n"               # 3
        "\n"                                                       # 4
        "\n"                                                       # 5
        "\\begin{figure}[H]\n"                                    # 6 — TARGET (figure 3-4 mirror)
        "    \\centering\n"
        "    \\includegraphics{img1.png}\n"
        "    \\caption{first caption}\n"
        "    \\label{fig:3.4}\n"
        "\\end{figure}\n"                                         # 11
        "\n"                                                       # 12
        "Body para after target referring to figure.\n"          # 13 SyncTeX hit
        "\n"                                                       # 14
        "\n"                                                       # 15
        "\\begin{figure}[H]\n"                                    # 16 — NEXT sibling (figure 3-5 mirror)
        "    \\centering\n"
        "    \\includegraphics{img2.png}\n"
        "    \\caption{second caption}\n"
        "    \\label{fig:3.5}\n"
        "\\end{figure}\n"                                         # 21
        "\n"
        "more body.\n"
    )
    # tex_line=13 → backtrack to \end{figure}@11, anchor=10 → fig 6-11 [H]
    # _find_prev_sibling_figure(start=6) → None (no figure above)
    # _find_next_sibling_figure(end=11) → fig 16-21 (gap=5, ≤30) ✓
    # → Day 19 guard fires with sibling_direction="next"
    issue = _float_gap_issue(tex_line=13)
    plan = ar.float_policy_repair(issue, tmp_path)
    assert plan["status"] == "diagnostic"
    assert plan["reason"].startswith(
        "strategy_contraindicated_adjacent_figures")
    meta = plan["diagnostic_meta"]
    assert meta["guard"] == "strategy_contraindicated_adjacent_figures"
    assert meta["sibling_direction"] == "next"
    # Target figure recorded
    assert meta["target_figure_block"]["start_line"] == 6
    assert meta["target_figure_block"]["end_line"] == 11
    assert meta["target_figure_block"]["original_placement"] == "[H]"
    # Next sibling figure recorded
    assert "next_sibling_figure_block" in meta
    assert meta["next_sibling_figure_block"]["start_line"] == 16
    assert meta["next_sibling_figure_block"]["end_line"] == 21
    # No prev sibling for this fixture
    assert "prev_sibling_figure_block" not in meta
    # Backtrack metadata still present
    assert meta["resolution_adjustment"] == "backtrack_from_post_figure_text"
    assert meta["original_tex_line"] == 13


def test_contraindication_both_prev_and_next_sibling_marks_direction_both(tmp_path):
    """Three figures with target sandwiched in the middle — guard reports
    sibling_direction='both' and includes both figure_block entries."""
    _write_chapter(tmp_path,
        "intro.\n"                                              # 1
        "\\begin{figure}[H]\n"                                  # 2 — prev
        "    \\caption{a}\n"
        "\\end{figure}\n"                                       # 4
        "\n"                                                     # 5
        "Short prose between figures.\n"                       # 6
        "\n"                                                     # 7
        "\\begin{figure}[H]\n"                                  # 8 — TARGET
        "    \\caption{b}\n"
        "    \\label{fig:t}\n"
        "\\end{figure}\n"                                       # 11
        "\n"                                                     # 12
        "Body line after target.\n"                            # 13 SyncTeX hit
        "\n"                                                     # 14
        "\\begin{figure}[H]\n"                                  # 15 — next
        "    \\caption{c}\n"
        "\\end{figure}\n"                                       # 17
    )
    issue = _float_gap_issue(tex_line=13)
    plan = ar.float_policy_repair(issue, tmp_path)
    assert plan["status"] == "diagnostic"
    meta = plan["diagnostic_meta"]
    assert meta["sibling_direction"] == "both"
    assert "prev_sibling_figure_block" in meta
    assert "next_sibling_figure_block" in meta
    assert meta["prev_sibling_figure_block"]["start_line"] == 2
    assert meta["next_sibling_figure_block"]["start_line"] == 15


def test_next_sibling_helper_rejects_when_section_intervenes(tmp_path):
    """`_find_next_sibling_figure` mirrors prev-side: section heading
    between target end and downstream figure → return None (refuse)."""
    p = _write_chapter(tmp_path,
        "intro.\n"                       # 1
        "\\begin{figure}[H]\n"          # 2 target
        "    \\caption{a}\n"
        "\\end{figure}\n"               # 4
        "\n"                              # 5
        "\\section{New section}\n"       # 6 — heading
        "\n"
        "\\begin{figure}[H]\n"          # 8
        "    \\caption{b}\n"
        "\\end{figure}\n"               # 10
    )
    result = ar._find_next_sibling_figure(p, target_end_line=4)
    assert result is None


def test_next_sibling_helper_rejects_beyond_max_gap_lines(tmp_path):
    """Distance > max_gap_lines → None (mirrors prev-side semantics)."""
    blanks = "\n" * 35  # 35 blank lines downstream
    p = _write_chapter(tmp_path,
        "\\begin{figure}[H]\n"          # 1 target
        "    \\caption{a}\n"
        "\\end{figure}\n"               # 3
        + blanks +                        # 4..38 blanks
        "\\begin{figure}[H]\n"          # 39 — too far (35 > 30)
        "    \\caption{b}\n"
        "\\end{figure}\n"
    )
    result = ar._find_next_sibling_figure(p, target_end_line=3)
    assert result is None


def test_next_sibling_helper_finds_figure_within_gap(tmp_path):
    """Positive control: figure within max_gap_lines → return (start, end)."""
    p = _write_chapter(tmp_path,
        "\\begin{figure}[H]\n"          # 1 target
        "    \\caption{a}\n"
        "\\end{figure}\n"               # 3
        "\n"                              # 4
        "Some prose here.\n"             # 5
        "\n"                              # 6
        "\\begin{figure}[H]\n"          # 7 — next sibling
        "    \\caption{b}\n"
        "\\end{figure}\n"               # 9
    )
    result = ar._find_next_sibling_figure(p, target_end_line=3)
    assert result == (7, 9)


def test_contraindication_does_not_fire_for_single_figure(tmp_path):
    """Day 15 single-figure fixture must stay ready — only adjacent-figure
    pathology is contraindicated."""
    _write_chapter(tmp_path,
        "intro.\n"                       # 1
        "\n"                              # 2
        "\\begin{figure}[H]\n"          # 3
        "    \\caption{c}\n"
        "    \\label{fig:x}\n"
        "\\end{figure}\n"               # 6
        "\n"                              # 7
        "body line\n"                    # 8 SyncTeX hit
    )
    issue = _float_gap_issue(tex_line=8)
    plan = ar.float_policy_repair(issue, tmp_path)
    assert plan["status"] == "ready", plan
    # No prev sibling → contraindication guard MUST NOT fire
    assert "diagnostic_meta" not in plan


def test_contraindication_does_not_fire_when_placement_not_H(tmp_path):
    """[!htbp] placement is the post-fix target — by construction Day 7
    repair would not even trigger placement_change. If detector lands on
    such a figure with backtrack + sibling, guard does NOT fire because
    the [H] precondition is missing."""
    _write_chapter(tmp_path,
        "intro.\n"                                              # 1
        "\\begin{figure}[!htbp]\n"                              # 2 sibling
        "    \\caption{first}\n"
        "\\end{figure}\n"                                       # 4
        "\n"                                                     # 5
        "short prose.\n"                                        # 6
        "\n"                                                     # 7
        "\\begin{figure}[!htbp]\n"                              # 8 target (NOT [H])
        "    \\caption{second}\n"
        "    \\label{fig:y}\n"
        "\\end{figure}\n"                                       # 11
        "\n"                                                     # 12
        "body line.\n"                                           # 13 SyncTeX hit
    )
    issue = _float_gap_issue(tex_line=13)
    plan = ar.float_policy_repair(issue, tmp_path)
    # Plan may still be ready (sibling barrier strategy applies) OR
    # diagnostic ("no actionable change" if all barriers exist), but it
    # must NOT carry the contraindication reason.
    if plan["status"] == "diagnostic":
        assert "strategy_contraindicated" not in plan["reason"]
    else:
        assert plan["status"] == "ready"
        assert "diagnostic_meta" not in plan


def test_contraindication_does_not_fire_when_not_post_figure_backtrack(tmp_path):
    """If parse_figure_block succeeds directly (line in figure), backtrack
    never runs and guard cannot apply — even with sibling and [H]."""
    _write_chapter(tmp_path,
        "intro.\n"                       # 1
        "\\begin{figure}[H]\n"          # 2 sibling
        "    \\caption{a}\n"
        "\\end{figure}\n"               # 4
        "\n"                              # 5
        "\\begin{figure}[H]\n"          # 6 target
        "    \\caption{b}\n"             # 7 SyncTeX hit (INSIDE target figure)
        "\\end{figure}\n"               # 8
    )
    issue = _float_gap_issue(tex_line=7)
    plan = ar.float_policy_repair(issue, tmp_path)
    # backtrack_meta is None, so guard short-circuits — plan should be ready
    assert plan["status"] == "ready"
    assert "diagnostic_meta" not in plan
    # No backtrack metadata since direct parse worked
    assert "resolution_adjustment" not in plan


def test_contraindication_equation_gap_still_rejected_upstream(tmp_path):
    """equation_gap remains rejected by Day 13A subtype guard; Day 17
    contraindication does not perturb that early-exit."""
    _write_chapter(tmp_path,
        "\\begin{figure}[H]\n"          # 1 sibling
        "    \\caption{a}\n"
        "\\end{figure}\n"               # 3
        "\\begin{figure}[H]\n"          # 4 target
        "    \\caption{b}\n"
        "\\end{figure}\n"               # 6
        "\n"                              # 7
        "(3.6)\n"                       # 8 — equation tag
    )
    issue = _issue(tex_line=8)
    issue["evidence"]["subtype"] = "equation_gap"
    plan = ar.float_policy_repair(issue, tmp_path)
    # Day 13A guard: equation_gap → return None (issue not eligible at all)
    assert plan is None


# ---------------------------------------------------------------------------
# Day 17: run_loop case_label parameterisation (was hard-coded "CASE-A").
# ---------------------------------------------------------------------------


def test_run_loop_accepts_case_label_kwarg():
    """Sanity: signature exposes case_label, default 'UNK'.
    No actual loop execution — that requires a built workdir + Docker."""
    import inspect
    sig = inspect.signature(ar.run_loop)
    assert "case_label" in sig.parameters
    param = sig.parameters["case_label"]
    assert param.default == "UNK"


def test_run_loop_no_more_hardcoded_case_015():
    """Source-level guard: no run_loop call site embeds the literal
    'CASE-A' as a case_label argument value. Comments/docstrings
    that *mention* CASE-A in narrative text are allowed."""
    src = (Path(ar.__file__)).read_text(encoding="utf-8")
    # Anything matching case_label="CASE-A" or case_label='CASE-A' as
    # an actual call argument would be the regression. The literal
    # 'case_label="CASE-A"' was the pre-Day-17 pattern.
    import re
    bad = re.findall(r"case_label\s*=\s*['\"]CASE-A['\"]", src)
    assert bad == [], (
        f"Found {len(bad)} occurrences of hard-coded "
        f"case_label='CASE-A' — Day 17 should have parameterised these")


def test_backtrack_rejects_intervening_table_environment(tmp_path):
    """\\begin{table} / \\end{table} between figure and tex_line →
    diagnostic. Tables are a different float type with their own gap
    semantics; auto-repair on the figure above might mis-attribute."""
    _write_chapter(tmp_path,
        "\\begin{figure}[H]\n"          # 1
        "    \\centering\n"
        "    \\includegraphics{img.png}\n"
        "    \\caption{c}\n"
        "\\end{figure}\n"               # 5
        "\\begin{table}[H]\n"            # 6 — table env intervening
        "    \\caption{t}\n"
        "\\end{table}\n"                  # 8
        "\n"
        "body line\n"                    # 10 SyncTeX hit
    )
    issue = _float_gap_issue(tex_line=10)
    plan = ar.float_policy_repair(issue, tmp_path)
    assert plan["status"] == "diagnostic"
    assert "no safe backtrack" in plan["reason"]
