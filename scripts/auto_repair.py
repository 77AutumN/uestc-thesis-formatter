"""Auto-repair MVP loop (Phase 2, Day 7).

Closed-loop demonstration on a SINGLE issue type / SINGLE repairer:

    visual_geometry_audit → SyncTeX → float_policy_repair → recompile →
    re-audit → accept (target gone OR weighted score down) or rollback + taboo

Hard scope (Day 7):
  * Only ``issue_code == "large_vertical_gap"`` with
    ``repairability == "deterministic"`` enters the repair pipeline.
  * Only one repairer: ``float_policy_repair``.
  * Repairer locates the enclosing figure block from a SyncTeX line, and
    if the line is not inside a figure environment it emits a *diagnostic*
    no-op rather than guess.
  * Edits are limited to the located figure block boundary:
      - ``[H]`` placement is rewritten to ``[!htbp]``;
      - immediately after ``\\end{figure}`` an idempotent
        ``\\FloatBarrier`` is inserted (with a marker comment so re-runs
        don't stack).
  * No edits to caption text, image path, body prose, or chapter
    structure.
  * ``max_rounds`` defaults to 2 (Day 7 only proves the loop, not full
    convergence).

Hard non-scope (Day 7):
  * Does NOT call run_v2.py.
  * Does NOT touch SKILL.md / CLAUDE.md / ARCHITECTURE.md /
    product_audit.py / templates/ / vendor/.
  * Operates only on a sandbox workdir; original case workspaces are
    read-only and never visited by this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
import audit_issue_schema as ais  # noqa: E402
import visual_geometry_audit as vga  # noqa: E402

DEFAULT_DOCKER_IMAGE = "ghcr.io/xu-cheng/texlive-full:20240101"
FLOATBARRIER_MARKER = "% v5-auto-repair: float_policy_repair (idempotent)"
PLACEINS_PREAMBLE_MARKER = "% v5-auto-repair: placeins enabler for \\FloatBarrier (idempotent)"

# ---------------------------------------------------------------------------
# Weighted score (Day 4 spec, simplified for Day 7 MVP)
# ---------------------------------------------------------------------------

_SEVERITY_WEIGHT = {"P0": 1000, "P1": 100, "P2": 10}


def weighted_score(issues: List[Dict[str, Any]]) -> int:
    return sum(_SEVERITY_WEIGHT.get(i.get("severity"), 0) for i in issues)


# ---------------------------------------------------------------------------
# Figure block parser
# ---------------------------------------------------------------------------

_FIG_BEGIN = re.compile(r"\\begin\{figure\}(\[[^\]]*\])?")
_FIG_END = re.compile(r"\\end\{figure\}")
# Section-level boundaries that must not be barrier-crossed
_HEADING_RE = re.compile(
    r"^\s*\\(chapter|section|subsection|subsubsection|paragraph|subparagraph)"
    r"(\*)?(\[|\{|\s)"
)

# Day 15: structural markers that backtrack must NOT cross.
_TABLE_BEGIN_RE = re.compile(r"\\begin\{table\}")
_TABLE_END_RE = re.compile(r"\\end\{table\}")
_DISPLAY_MATH_ENV_RE = re.compile(
    r"\\(begin|end)\{(equation|align|gather|displaymath|multline|eqnarray)\*?\}"
)
_DISPLAY_MATH_BRACKET_RE = re.compile(r"\\\[|\\\]")


def parse_figure_block(tex_path: Path, line_num: int
                       ) -> Optional[Tuple[int, int, str]]:
    """Locate the figure environment containing ``line_num`` (1-based).

    Returns ``(start_line, end_line, placement)`` where ``placement`` is
    the bracketed spec like ``"[H]"`` or ``"[htbp]"`` (empty string when
    no placement was given). Returns ``None`` when the line is not
    inside any figure environment — caller must treat that as no-op.

    Walks backward from ``line_num`` looking for ``\\begin{figure}``, but
    bails out (returns None) if it sees a ``\\end{figure}`` first because
    that means the line sits *between* figures, not inside one.
    """
    if line_num < 1:
        return None
    text = tex_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if line_num > len(lines):
        return None

    start = None
    placement = ""
    for i in range(line_num - 1, -1, -1):
        m = _FIG_BEGIN.search(lines[i])
        if m:
            start = i + 1
            placement = m.group(1) or ""
            break
        if _FIG_END.search(lines[i]):
            return None  # walked past a previous \end{figure}

    if start is None:
        return None

    end = None
    for i in range(start - 1, len(lines)):
        if _FIG_END.search(lines[i]):
            end = i + 1
            break
    if end is None or end < line_num:
        return None
    return (start, end, placement)


# ---------------------------------------------------------------------------
# Day 15: bounded backtrack for SyncTeX-into-post-figure-body case.
#
# Background (CASE Day 14 finding): detect_large_vertical_gap queries
# SyncTeX with the *curr* (post-gap) block center, which for a figure-float
# gap maps to the first body line AFTER \end{figure}. parse_figure_block
# then refuses (line not inside any figure env). Without this helper the
# repairer would emit diagnostic for every real figure-float gap.
#
# This helper is intentionally conservative: it crosses only blank lines or
# pure-% comments, and refuses on ANY recognised structural marker between
# tex_line and the nearest \end{figure} above. Caller (float_policy_repair)
# only invokes this when subtype="float_gap"; equation_gap is rejected
# upstream by the existing belt-and-suspenders subtype guard.
# ---------------------------------------------------------------------------


def _backtrack_to_figure_end(tex_path: Path, tex_line: int,
                             max_back: int = 10
                             ) -> Optional[Tuple[int, int]]:
    """Locate \\end{figure} above ``tex_line`` for SyncTeX-into-post-figure
    rescue.

    Walks upward from ``tex_line - 1`` for at most ``max_back`` lines.
    Allowed pass-through: blank lines and pure-comment lines (``stripped``
    starts with ``%``). Refuses (returns ``None``) on:
      * body prose (any non-empty / non-comment line that is not a known
        structural marker)
      * heading: \\chapter / \\section / \\subsection / ... — possibly a
        new section, fixing the wrong figure
      * \\begin{table} / \\end{table} — different float type
      * display math environments and \\[ \\] delimiters
      * \\begin{figure} — means tex_line is BEFORE a figure, not after
        \\end{figure} of an earlier one
      * walked past max_back without finding \\end{figure}

    Returns ``(figure_end_line, anchor_line)`` 1-based on success, where
    ``anchor_line == figure_end_line - 1``. The anchor is guaranteed to lie
    inside the figure block (it is the line immediately above the closing
    ``\\end{figure}``), so passing it to ``parse_figure_block`` will succeed.
    """
    if tex_line < 2:
        return None
    text = tex_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if tex_line > len(lines):
        return None

    # Walk over the (max_back) lines immediately above tex_line, exclusive.
    # tex_line is 1-based; convert to 0-based, then back off by 1 to skip
    # tex_line itself and start at the line above.
    start_idx = tex_line - 2
    earliest_idx = max(0, tex_line - 1 - max_back)

    for i in range(start_idx, earliest_idx - 1, -1):
        ln = lines[i]
        stripped = ln.strip()
        # Allowed pass-through
        if not stripped or stripped.startswith("%"):
            continue
        # Anchor found
        if _FIG_END.search(ln):
            figure_end_line = i + 1
            anchor_line = figure_end_line - 1
            if anchor_line < 1:
                return None
            return (figure_end_line, anchor_line)
        # Refuse on any structural marker — better to diagnostic than
        # patch the wrong figure.
        if _FIG_BEGIN.search(ln):
            return None
        if _HEADING_RE.match(ln):
            return None
        if _TABLE_BEGIN_RE.search(ln) or _TABLE_END_RE.search(ln):
            return None
        if _DISPLAY_MATH_ENV_RE.search(ln):
            return None
        if _DISPLAY_MATH_BRACKET_RE.search(ln):
            return None
        # Non-empty, non-comment, no recognised marker → body text. Refuse.
        return None

    # Scanned max_back lines without finding \end{figure}
    return None


# ---------------------------------------------------------------------------
# float_policy_repair
# ---------------------------------------------------------------------------


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _plan_hash(tex_path: Path, before: str, after: str) -> str:
    """Stable hash so the same patch applied to the same file at the same
    state is recognised in the taboo list."""
    h = hashlib.sha256()
    h.update(str(tex_path).encode("utf-8")); h.update(b"\0")
    h.update(before.encode("utf-8")); h.update(b"\0")
    h.update(after.encode("utf-8"))
    return h.hexdigest()[:16]


def _find_prev_sibling_figure(tex_path: Path, target_start_line: int,
                               max_gap_lines: int = 30
                               ) -> Optional[Tuple[int, int]]:
    """Locate the figure block immediately preceding the target figure.

    Used to insert a barrier *between* two adjacent figure environments,
    forcing the earlier one to flush before the next begins. This is what
    makes ``large_vertical_gap`` between two co-placed figures actually
    disappear (Day 7 showed that a barrier *after* the located figure
    only manages downstream floats, not the gap already between siblings).

    Heuristics (deliberately conservative — refuses when ambiguous):
      * Walk backward from the line before the target's
        ``\\begin{figure}`` (i.e. ``target_start_line - 1``).
      * Find the previous ``\\end{figure}`` within ``max_gap_lines``
        lines (default 30) of the target's begin.
      * Then continue back to find the matching ``\\begin{figure}``.
      * Refuse (return ``None``) if a section-level heading lies in
        between, or if the gap exceeds ``max_gap_lines``, or if the
        structure is malformed (two ``\\end{figure}`` before any begin).

    Returns ``(prev_start_line, prev_end_line)`` 1-based, or ``None``.
    """
    text = tex_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if target_start_line < 2 or target_start_line > len(lines):
        return None

    prev_end = None  # 1-based line of previous \end{figure}
    for i in range(target_start_line - 2, -1, -1):  # 0-based, walk up
        ln = lines[i]
        if _HEADING_RE.match(ln):
            return None  # section boundary — refuse to barrier across it
        if prev_end is None:
            # Looking for \end{figure} of the previous figure
            if (target_start_line - 1) - (i + 1) > max_gap_lines:
                # Too far without finding a sibling
                return None
            if _FIG_END.search(ln):
                prev_end = i + 1
                continue
        else:
            # Looking for the matching \begin{figure}
            if _FIG_BEGIN.search(ln):
                return (i + 1, prev_end)
            if _FIG_END.search(ln):
                # Two \end{figure} without intervening \begin: malformed
                return None
    return None


def _find_next_sibling_figure(tex_path: Path, target_end_line: int,
                               max_gap_lines: int = 30
                               ) -> Optional[Tuple[int, int]]:
    """Locate the figure block immediately FOLLOWING the target figure.

    Day 19: mirror of ``_find_prev_sibling_figure`` to close the contraind-
    ication guard hole found in Day 18. Day 17 only checked prev sibling
    (case 11 form). case 16 VIS-LARGE_VE-0003 turned out to be the next-
    direction mirror: target figure 219-224 with figure 229-234 only 5
    lines downstream — same figure-figure adjacency pathology, opposite
    direction. The contraindication guard now considers either direction.

    Heuristics (deliberately conservative, mirrors prev side):
      * Walk forward from the line after the target's ``\\end{figure}``
        (i.e. ``target_end_line + 1``).
      * Find the next ``\\begin{figure}`` within ``max_gap_lines``
        lines (default 30) of the target's end.
      * Then continue forward to find the matching ``\\end{figure}``.
      * Refuse (return ``None``) if a section-level heading lies in
        between, or if the gap exceeds ``max_gap_lines``, or if the
        structure is malformed (two ``\\begin{figure}`` before any end).

    Returns ``(next_start_line, next_end_line)`` 1-based, or ``None``.
    """
    text = tex_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if target_end_line < 1 or target_end_line >= len(lines):
        return None

    next_start = None  # 1-based line of next \begin{figure}
    # Walk from the line *after* target_end_line (0-based index = target_end_line).
    for i in range(target_end_line, len(lines)):
        ln = lines[i]
        if _HEADING_RE.match(ln):
            return None  # section boundary — refuse to barrier across it
        if next_start is None:
            # Looking for \begin{figure} of the next figure
            if (i + 1) - target_end_line > max_gap_lines:
                # Too far downstream without finding a sibling
                return None
            if _FIG_BEGIN.search(ln):
                next_start = i + 1
                continue
        else:
            # Looking for the matching \end{figure}
            if _FIG_END.search(ln):
                return (next_start, i + 1)
            if _FIG_BEGIN.search(ln):
                # Two \begin{figure} without intervening \end: malformed
                return None
    return None


def _floatbarrier_already_after_line(lines: List[str], one_based_line: int) -> bool:
    """Check if ``\\FloatBarrier`` (or our marker) is on the next 1-2 lines."""
    idx = one_based_line  # next 0-based after the given line
    next_line = lines[idx] if idx < len(lines) else ""
    line_after = lines[idx + 1] if idx + 1 < len(lines) else ""
    return (
        FLOATBARRIER_MARKER in next_line
        or FLOATBARRIER_MARKER in line_after
        or re.search(r"\\FloatBarrier\b", next_line) is not None
    )


def _placeins_already_loaded(main_tex_text: str) -> bool:
    """Detect whether placeins (or an equivalent providing \\FloatBarrier) is
    already imported. We only check direct \\usepackage{placeins}; a project
    relying on a custom .cls that defines \\FloatBarrier without placeins
    would still pass at compile time even if this returns False (the
    repairer's preamble injection is then redundant but idempotent)."""
    return bool(re.search(r"\\usepackage(\[[^\]]*\])?\{placeins\}", main_tex_text)) \
        or PLACEINS_PREAMBLE_MARKER in main_tex_text


def _plan_placeins_preamble_patch(main_tex_path: Path
                                   ) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """If main.tex needs ``\\usepackage{placeins}``, return (before, after, action).
    Otherwise return None (already loaded)."""
    before = main_tex_path.read_text(encoding="utf-8")
    if _placeins_already_loaded(before):
        return None
    lines = before.splitlines()
    # Find the last \usepackage{...} line; insert after it
    last_usepackage_idx = -1
    for i, ln in enumerate(lines):
        if re.search(r"^\s*\\usepackage(\[[^\]]*\])?\{", ln):
            last_usepackage_idx = i
    if last_usepackage_idx == -1:
        # Unusual: no \usepackage at all. Skip (we won't guess where to insert).
        return None
    new_lines = list(lines)
    new_lines.insert(last_usepackage_idx + 1, PLACEINS_PREAMBLE_MARKER)
    new_lines.insert(last_usepackage_idx + 2, "\\usepackage{placeins}")
    after = "\n".join(new_lines)
    if before.endswith("\n"):
        after += "\n"
    action = {"type": "preamble_load_placeins",
              "file": "main.tex",
              "line_after": last_usepackage_idx + 2}
    return before, after, action


def float_policy_repair(issue: Dict[str, Any], workdir: Path
                        ) -> Optional[Dict[str, Any]]:
    """Plan a repair for one ``large_vertical_gap`` issue.

    Returns a plan dict with ``status`` field:
      - ``"ready"``: actionable plan, see ``actions`` for details
      - ``"diagnostic"``: cannot act safely (no figure block found,
        already idempotent, etc.); ``reason`` explains why
      - ``None`` returned when issue is not eligible
    """
    if issue.get("issue_code") != "large_vertical_gap":
        return None
    # Day 13A: belt-and-suspenders guard. The detector already downgrades
    # equation_gap to repairability="diagnostic" so the next check would also
    # reject, but the explicit subtype check makes the intent visible at the
    # repairer entry — wrong-fix in equation environments is the failure mode
    # we're guarding against.
    if (issue.get("evidence") or {}).get("subtype") == "equation_gap":
        return None
    if issue.get("repairability") != "deterministic":
        return None
    loc = issue.get("location") or {}
    tex_file = loc.get("tex_file")
    tex_line = loc.get("tex_line")
    if not tex_file or tex_line is None:
        return {"status": "diagnostic",
                "reason": "no SyncTeX location (tex_file/tex_line missing)"}

    tex_path = workdir / tex_file
    if not tex_path.is_file():
        return {"status": "diagnostic",
                "reason": f"tex_file not found in workdir: {tex_path}"}

    block = parse_figure_block(tex_path, tex_line)
    backtrack_meta: Optional[Dict[str, Any]] = None
    if block is None:
        # Day 15: SyncTeX commonly maps a float_gap issue to the body line
        # *after* \end{figure} (detector queries the post-gap block centre).
        # Try a bounded backtrack — only for float_gap, only across blank/
        # comment lines, only ≤10 lines up. Any structural marker in the
        # window forces diagnostic.
        if (issue.get("evidence") or {}).get("subtype") != "float_gap":
            return {"status": "diagnostic",
                    "reason": (f"line {tex_file}:{tex_line} not inside a "
                               f"figure environment — refusing to guess")}
        bt = _backtrack_to_figure_end(tex_path, tex_line)
        if bt is None:
            return {"status": "diagnostic",
                    "reason": (f"line {tex_file}:{tex_line} not inside a "
                               f"figure environment, and no safe backtrack "
                               f"to \\end{{figure}} within 10 lines — "
                               f"refusing to guess")}
        figure_end_line, anchor_line = bt
        block = parse_figure_block(tex_path, anchor_line)
        if block is None:
            # Defensive: anchor is supposed to be inside the figure block
            # by construction. If parse fails here the file is malformed.
            return {"status": "diagnostic",
                    "reason": (f"line {tex_file}:{tex_line} backtracked "
                               f"to anchor :{anchor_line} but figure "
                               f"block parse still failed — refusing")}
        backtrack_meta = {
            "resolution_adjustment": "backtrack_from_post_figure_text",
            "original_tex_line": tex_line,
            "anchor_tex_line": anchor_line,
            "figure_end_line": figure_end_line,
        }

    start, end, placement = block
    before = tex_path.read_text(encoding="utf-8")
    lines = before.splitlines()
    actions: List[Dict[str, Any]] = []

    # We collect insertions as (one_based_line_to_insert_after, marker, code)
    # tuples and apply them in DESCENDING order so earlier line numbers
    # remain valid as later lines shift down.
    insertions: List[Tuple[int, str, str]] = []

    # ---- Strategy 1: [H] → [!htbp] inside located \begin{figure}[...] line
    # (single-line in-place replacement, doesn't change line numbering)
    begin_idx = start - 1
    placement_change_text = None
    if "[H]" in lines[begin_idx]:
        placement_change_text = lines[begin_idx].replace("[H]", "[!htbp]", 1)
        actions.append({"type": "placement_change",
                        "line": start, "from": "[H]", "to": "[!htbp]"})

    # ---- Strategy 2: idempotent \FloatBarrier after target \end{figure}
    if not _floatbarrier_already_after_line(lines, end):
        insertions.append((end, FLOATBARRIER_MARKER, "\\FloatBarrier"))
        actions.append({"type": "insert_floatbarrier_after_figure",
                        "after_line": end})

    # ---- Strategy 3 (Day 8): \FloatBarrier after immediately-preceding
    # sibling figure's \end{figure} — the actual fix for figure-figure gap.
    sibling = _find_prev_sibling_figure(tex_path, start)
    # Day 19: also check the next direction (case 16 VIS-0003 was the
    # mirror of case 11 — adjacent figure was DOWNSTREAM, not upstream).
    next_sibling = _find_next_sibling_figure(tex_path, end)

    # ---- Day 17/19: contraindication guard.
    # Day 16 实测 in case 11 ch04.tex: a target figure with original [H]
    # placement, accompanied by an adjacent sibling figure within
    # max_gap_lines, reached via post-figure backtrack from SyncTeX — this
    # combination produced rejected_no_progress: the [H]→[!htbp] +
    # FloatBarrier×2 + placeins set transformed the gap rather than
    # closing it (1× 88pt before → 2× 91pt after).
    #
    # Day 19: extended to either direction. Day 17 only checked prev
    # (case 11 was prev-side); case 16 VIS-0003 (Day 18 triage) revealed
    # the same pathology in next-side. Refuse on either prev OR next
    # sibling adjacency. equation_gap is already rejected upstream (Day
    # 13A subtype guard); this guard handles the separate float_gap
    # adjacency pathology that the existing Day 7-8 strategy cannot
    # safely fix.
    if (backtrack_meta is not None
            and placement == "[H]"
            and (sibling is not None or next_sibling is not None)):
        if sibling is not None and next_sibling is not None:
            sibling_direction = "both"
        elif sibling is not None:
            sibling_direction = "prev"
        else:
            sibling_direction = "next"
        diag_meta: Dict[str, Any] = {
            "guard": "strategy_contraindicated_adjacent_figures",
            "sibling_direction": sibling_direction,
            "target_figure_block": {
                "tex_file": tex_file, "start_line": start,
                "end_line": end, "original_placement": placement,
            },
            "resolution_adjustment": backtrack_meta["resolution_adjustment"],
            "original_tex_line": backtrack_meta["original_tex_line"],
            "anchor_tex_line": backtrack_meta["anchor_tex_line"],
            "figure_end_line": backtrack_meta["figure_end_line"],
        }
        if sibling is not None:
            ps, pe = sibling
            diag_meta["prev_sibling_figure_block"] = {
                "start_line": ps, "end_line": pe,
            }
        if next_sibling is not None:
            ns, ne = next_sibling
            diag_meta["next_sibling_figure_block"] = {
                "start_line": ns, "end_line": ne,
            }
        # Reason mentions the actual sibling location for debug clarity
        if sibling_direction == "prev":
            ps, pe = sibling
            sibling_desc = f"prev sibling figure ({ps}-{pe})"
        elif sibling_direction == "next":
            ns, ne = next_sibling
            sibling_desc = f"next sibling figure ({ns}-{ne})"
        else:
            ps, pe = sibling; ns, ne = next_sibling
            sibling_desc = (f"both prev sibling ({ps}-{pe}) and next "
                            f"sibling ({ns}-{ne})")
        return {
            "status": "diagnostic",
            "reason": (
                "strategy_contraindicated_adjacent_figures: target figure "
                f"({tex_file}:{start}-{end}, original placement [H]) has "
                f"{sibling_desc} within max_gap_lines, AND the issue was "
                f"located via post-figure backtrack — Day 16/18 measured "
                f"this shape produces rejected_no_progress, refusing to "
                f"plan a known-bad fix"
            ),
            "issue_id": issue.get("issue_id"),
            "issue_code": issue.get("issue_code"),
            "diagnostic_meta": diag_meta,
        }

    if sibling is not None:
        prev_start, prev_end = sibling
        if not _floatbarrier_already_after_line(lines, prev_end):
            insertions.append((prev_end, FLOATBARRIER_MARKER, "\\FloatBarrier"))
            actions.append({
                "type": "insert_floatbarrier_before_target_via_prev_sibling",
                "after_line": prev_end,
                "prev_figure_block": {
                    "start_line": prev_start, "end_line": prev_end,
                },
            })

    if not actions:
        return {"status": "diagnostic",
                "reason": ("no actionable change — figure already uses "
                           "non-[H] placement and \\FloatBarrier is "
                           "present after target and any sibling")}

    # Apply insertions in DESCENDING line order so earlier-line indices
    # remain stable; higher inserts happen first, lower ones unaffected.
    new_lines = list(lines)
    if placement_change_text is not None:
        new_lines[begin_idx] = placement_change_text
    for after_line, marker, code in sorted(insertions, key=lambda x: -x[0]):
        new_lines.insert(after_line, marker)
        new_lines.insert(after_line + 1, code)

    # Reconstruct figure-file new text, preserving final newline if any
    after = "\n".join(new_lines)
    if before.endswith("\n"):
        after += "\n"

    file_changes: List[Dict[str, Any]] = [{
        "path": str(tex_path),
        "before_text": before,
        "after_text": after,
        "before_hash": _hash_text(before),
        "after_hash": _hash_text(after),
    }]

    # ----------------------------------------------------------------------
    # Day 7 scope-decision: \FloatBarrier requires the placeins package.
    # CASE-A main.tex (and DissertUESTC.cls) does not load placeins,
    # so without preamble enablement the FloatBarrier insertion would
    # produce "Undefined control sequence" at xelatex time. The repairer
    # therefore conditionally adds ``\usepackage{placeins}`` to main.tex
    # preamble as a one-line idempotent enabler with a marker comment.
    #
    # This is documented in the Day 7 report under "scope decision: scope
    # of repairer's allowed file edits". It does NOT touch body text,
    # captions, image paths, or chapter structure (the user's explicit
    # forbidden list, constraint #4). It is bounded to exactly the line
    # required for the strategy to work, and is detected as already-present
    # to stay idempotent across re-runs.
    # ----------------------------------------------------------------------
    floatbarrier_added = any(a["type"] == "insert_floatbarrier_after_figure"
                              for a in actions)
    if floatbarrier_added:
        main_tex_path = workdir / "main.tex"
        if main_tex_path.is_file():
            preamble_patch = _plan_placeins_preamble_patch(main_tex_path)
            if preamble_patch is not None:
                pre_before, pre_after, pre_action = preamble_patch
                actions.append(pre_action)
                file_changes.append({
                    "path": str(main_tex_path),
                    "before_text": pre_before,
                    "after_text": pre_after,
                    "before_hash": _hash_text(pre_before),
                    "after_hash": _hash_text(pre_after),
                })

    # Compose plan hash from ALL touched files (order-stable)
    h = hashlib.sha256()
    for ch in file_changes:
        h.update(ch["path"].encode("utf-8")); h.update(b"\0")
        h.update(ch["before_hash"].encode("utf-8")); h.update(b"\0")
        h.update(ch["after_hash"].encode("utf-8")); h.update(b"\0")
    plan_hash = h.hexdigest()[:16]

    plan = {
        "status": "ready",
        "issue_id": issue.get("issue_id"),
        "issue_code": issue.get("issue_code"),
        "repairer": "float_policy_repair",
        "strategy": "ensure_safe_placement_and_floatbarrier_after",
        "plan_hash": plan_hash,
        "touched_files": [c["path"] for c in file_changes],
        "actions": actions,
        "figure_block": {"tex_file": tex_file, "start_line": start,
                         "end_line": end, "original_placement": placement},
        # Internal: per-file before/after texts used by apply / rollback
        "_file_changes": file_changes,
    }
    # Day 15: surface backtrack provenance so audit log can explain why
    # SyncTeX hit post-figure body but the repairer modified the figure
    # before it.
    if backtrack_meta is not None:
        plan.update(backtrack_meta)
    return plan


def serialise_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Drop internal fields before writing to disk."""
    out = {k: v for k, v in plan.items() if not k.startswith("_")}
    # Surface per-file hashes (without text) for plan provenance
    if "_file_changes" in plan:
        out["file_changes"] = [
            {k: v for k, v in ch.items() if k not in ("before_text", "after_text")}
            for ch in plan["_file_changes"]
        ]
    return out


# ---------------------------------------------------------------------------
# Apply / rollback / compile
# ---------------------------------------------------------------------------


def apply_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    if plan.get("status") != "ready":
        return {"status": "skipped", "reason": plan.get("reason"),
                "plan_hash": plan.get("plan_hash")}
    for ch in plan["_file_changes"]:
        Path(ch["path"]).write_text(ch["after_text"], encoding="utf-8")
    return {"status": "applied", "plan_hash": plan["plan_hash"],
            "files_written": [ch["path"] for ch in plan["_file_changes"]]}


def rollback_plan(plan: Dict[str, Any]) -> None:
    if plan.get("status") != "ready":
        return
    for ch in plan["_file_changes"]:
        Path(ch["path"]).write_text(ch["before_text"], encoding="utf-8")


def compile_workdir(workdir: Path, docker_image: str = DEFAULT_DOCKER_IMAGE
                    ) -> Tuple[bool, str]:
    """Recompile main.tex via the project Docker image with -synctex=1.

    Returns ``(success, log_tail)`` where success requires a zero return
    code AND ``main.pdf`` to exist. Always retains the last 800 chars of
    stdout+stderr in ``log_tail`` for diagnostics.
    """
    workdir_str = str(workdir).replace("\\", "/")
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{workdir_str}:/thesis",
        "-v", "C:/Windows/Fonts:/thesis/fonts:ro",
        "-w", "/thesis",
        docker_image,
        "bash", "-c",
        ("export OSFONTDIR=/thesis/fonts:/thesis/font && "
         "latexmk -synctex=1 -f -xelatex -interaction=nonstopmode main.tex"),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    pdf_ok = (workdir / "main.pdf").is_file()
    success = (res.returncode == 0) and pdf_ok
    log_tail = ((res.stdout or "")[-400:] + "\n--STDERR--\n" + (res.stderr or "")[-400:])
    return success, log_tail


# ---------------------------------------------------------------------------
# Snapshotting (round0 / round1 / round2 dirs)
# ---------------------------------------------------------------------------


def snapshot_round(snapshot_dir: Path, workdir: Path,
                   audit_report: Optional[Dict[str, Any]],
                   plan: Optional[Dict[str, Any]],
                   result: Optional[Dict[str, Any]],
                   score: Optional[int]) -> None:
    """Copy build artefacts + reports into a per-round snapshot directory."""
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    # PDF + synctex
    for name in ("main.pdf", "main.synctex.gz", "main.tex"):
        src = workdir / name
        if src.is_file():
            shutil.copy2(src, snapshot_dir / name)
    # All currently-touched files (current state, post-apply or post-rollback)
    if plan and plan.get("status") == "ready":
        for ch in plan.get("_file_changes", []):
            src = Path(ch["path"])
            if src.is_file():
                try:
                    rel = src.relative_to(workdir)
                except ValueError:
                    rel = Path(src.name)
                dst = snapshot_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    if audit_report is not None:
        (snapshot_dir / "audit_issues_visual_geometry.json").write_text(
            json.dumps(audit_report, ensure_ascii=False, indent=2),
            encoding="utf-8")
    if plan is not None:
        (snapshot_dir / "repair_plan.json").write_text(
            json.dumps(serialise_plan(plan), ensure_ascii=False, indent=2),
            encoding="utf-8")
    if result is not None:
        (snapshot_dir / "repair_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {"score": score, "n_issues": (len(audit_report["issues"])
               if audit_report and "issues" in audit_report else None)}
    (snapshot_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Acceptance
# ---------------------------------------------------------------------------


def _issue_signature(issue: Dict[str, Any]) -> str:
    """Stable signature: (code, page) — matches "same problem in same place"."""
    return f"{issue.get('issue_code')}|p{issue.get('location', {}).get('pdf_page')}"


def evaluate_acceptance(target: Dict[str, Any],
                        score_before: int,
                        audit_after: Dict[str, Any],
                        score_after: int,
                        audit_before: Dict[str, Any]) -> Dict[str, Any]:
    """Day 8: explicit two-tier acceptance.

    1. ``target_gone``: the targeted ``(issue_code, pdf_page)`` is not in
       ``audit_after``.
    2. ``score_dropped``: weighted score strictly decreased.
    3. ``no_new_p0``: ``audit_after`` has no P0 with a signature absent
       from ``audit_before`` (no new-P0-introduction collateral).

    Outcome enum:
      - ``full_success``    target_gone AND no_new_p0
      - ``partial_success`` (NOT target_gone) AND score_dropped AND no_new_p0
      - ``rejected_new_p0`` no_new_p0 is False
      - ``rejected_no_progress`` neither target_gone nor score_dropped

    ``accepted`` boolean is True iff outcome is full or partial success
    (i.e. preserves Day 7 reject-on-new-P0 / reject-on-no-progress contract).
    """
    target_sig = _issue_signature(target)
    after_sigs = {_issue_signature(i) for i in audit_after["issues"]}
    target_gone = target_sig not in after_sigs

    score_dropped = score_after < score_before

    before_sigs = {_issue_signature(i) for i in audit_before["issues"]}
    new_p0 = [
        i for i in audit_after["issues"]
        if i.get("severity") == "P0" and _issue_signature(i) not in before_sigs
    ]
    no_new_p0 = not new_p0

    if not no_new_p0:
        outcome = "rejected_new_p0"
    elif target_gone:
        outcome = "full_success"
    elif score_dropped:
        outcome = "partial_success"
    else:
        outcome = "rejected_no_progress"

    accepted = outcome in {"full_success", "partial_success"}

    return {
        "outcome": outcome,
        "accepted": accepted,
        "target_gone": target_gone,
        "score_before": score_before,
        "score_after": score_after,
        "score_dropped": score_dropped,
        "no_new_p0": no_new_p0,
        "introduced_p0_signatures": [_issue_signature(i) for i in new_p0],
    }


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------


def run_loop(workdir: Path, output_root: Path, target_issue_code: str,
             max_rounds: int = 2,
             gap_threshold_pt: float = 70.0,
             case_label: str = "UNK") -> Dict[str, Any]:
    """Day 17: ``case_label`` is now a parameter (was hard-coded
    "CASE-A" residual from the Day 7 MVP). All internal audit calls
    use the supplied label. Default "UNK" for callers that don't know
    or care; production callers should pass a meaningful case id."""
    output_root.mkdir(parents=True, exist_ok=True)
    taboo_path = output_root / "taboo.json"
    taboo: List[Dict[str, Any]] = (
        json.loads(taboo_path.read_text(encoding="utf-8"))
        if taboo_path.is_file() else []
    )

    log: List[Dict[str, Any]] = []

    # Round 0 — baseline
    print(f"[round 0] baseline audit on {workdir}")
    audit_prev = vga.run_audit(workdir, gap_threshold_pt=gap_threshold_pt,
                                case_label=case_label, use_synctex=True)
    score_prev = weighted_score(audit_prev["issues"])
    snapshot_round(output_root / "round0", workdir, audit_prev,
                   plan=None, result=None, score=score_prev)
    print(f"  baseline issues={len(audit_prev['issues'])} score={score_prev}")
    log.append({"round": 0, "n_issues": len(audit_prev["issues"]),
                "score": score_prev})

    final_status = "no_targets"

    for round_n in range(1, max_rounds + 1):
        targets = [
            i for i in audit_prev["issues"]
            if i.get("issue_code") == target_issue_code
            and i.get("repairability") == "deterministic"
        ]
        if not targets:
            print(f"[round {round_n}] no targets matching "
                  f"{target_issue_code}/deterministic, ending")
            final_status = "no_targets"
            break

        target = targets[0]
        sig = _issue_signature(target)
        print(f"[round {round_n}] target: {target['issue_id']} ({sig}) "
              f"@ {target['location'].get('tex_file')}:{target['location'].get('tex_line')}")

        plan = float_policy_repair(target, workdir)
        if plan is None:
            log.append({"round": round_n, "status": "ineligible"})
            final_status = "ineligible"; break
        if plan.get("status") == "diagnostic":
            print(f"[round {round_n}] DIAGNOSTIC: {plan['reason']}")
            snapshot_round(output_root / f"round{round_n}", workdir, audit_prev,
                           plan, {"status": "diagnostic_no_op",
                                  "reason": plan["reason"]}, score_prev)
            log.append({"round": round_n, "status": "diagnostic",
                        "reason": plan["reason"]})
            final_status = "diagnostic_no_op"
            break

        ph = plan["plan_hash"]
        if any(t["plan_hash"] == ph for t in taboo):
            print(f"[round {round_n}] plan_hash {ph} in taboo, skipping")
            log.append({"round": round_n, "status": "taboo_skip",
                        "plan_hash": ph})
            final_status = "taboo_exhausted"
            break

        # Apply
        apply_result = apply_plan(plan)
        print(f"[round {round_n}] applied plan {ph}, recompiling...")

        ok, comp_log = compile_workdir(workdir)
        if not ok:
            print(f"[round {round_n}] COMPILE FAILED, rolling back")
            rollback_plan(plan)
            taboo.append({
                "issue_signature": sig, "repairer": plan["repairer"],
                "strategy": plan["strategy"], "plan_hash": ph,
                "failure_reason": "compile_failed",
            })
            taboo_path.write_text(
                json.dumps(taboo, ensure_ascii=False, indent=2),
                encoding="utf-8")
            ok2, _ = compile_workdir(workdir)
            snapshot_round(output_root / f"round{round_n}", workdir, None,
                           plan, {"status": "rolled_back_compile_failed",
                                  "log_tail": comp_log,
                                  "rebuild_after_rollback_ok": ok2},
                           None)
            log.append({"round": round_n, "status": "compile_failed_taboo",
                        "plan_hash": ph})
            final_status = "compile_failed"
            break

        # Re-audit
        audit_n = vga.run_audit(workdir, gap_threshold_pt=gap_threshold_pt,
                                 case_label=case_label, use_synctex=True)
        score_n = weighted_score(audit_n["issues"])

        decision = evaluate_acceptance(target, score_prev, audit_n, score_n,
                                       audit_prev)
        decision["plan_hash"] = ph
        decision["compile_log_tail"] = comp_log[-300:]

        if decision["accepted"]:
            print(f"[round {round_n}] ACCEPTED: target_gone="
                  f"{decision['target_gone']} score "
                  f"{score_prev}→{score_n}")
            snapshot_round(output_root / f"round{round_n}", workdir, audit_n,
                           plan, decision, score_n)
            log.append({"round": round_n, "status": "accepted",
                        "score": score_n, "plan_hash": ph})
            audit_prev = audit_n
            score_prev = score_n
            final_status = "accepted"
            # Continue: maybe next round there's another target
            continue
        else:
            print(f"[round {round_n}] REJECTED, rolling back. "
                  f"target_gone={decision['target_gone']} "
                  f"score_dropped={decision['score_dropped']} "
                  f"no_new_p0={decision['no_new_p0']}")
            rollback_plan(plan)
            taboo.append({
                "issue_signature": sig, "repairer": plan["repairer"],
                "strategy": plan["strategy"], "plan_hash": ph,
                "failure_reason": "score_not_improved",
                "decision": decision,
            })
            taboo_path.write_text(
                json.dumps(taboo, ensure_ascii=False, indent=2),
                encoding="utf-8")
            # Recompile to restore PDF state to pre-patch baseline
            ok2, _ = compile_workdir(workdir)
            audit_restored = vga.run_audit(
                workdir, gap_threshold_pt=gap_threshold_pt,
                case_label=case_label, use_synctex=True)
            snapshot_round(output_root / f"round{round_n}", workdir, audit_n,
                           plan, decision, score_n)
            log.append({"round": round_n, "status": "rejected_taboo",
                        "score": score_n, "plan_hash": ph,
                        "rebuild_after_rollback_ok": ok2})
            final_status = "rejected_taboo"
            break

    (output_root / "loop_log.json").write_text(
        json.dumps({"final_status": final_status, "rounds": log,
                    "taboo": taboo}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return {"final_status": final_status, "log": log, "taboo": taboo}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Auto-repair MVP loop (Day 7, single repairer)")
    parser.add_argument("--workdir", required=True,
                        help="Sandbox DissertationUESTC directory containing "
                             "main.pdf + main.synctex.gz to repair in-place")
    parser.add_argument("--output-root", required=True,
                        help="Where to write round0/, round1/, ..., taboo.json, loop_log.json")
    parser.add_argument("--target-issue-code", default="large_vertical_gap",
                        help="Only this issue_code enters the repair pipeline")
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument("--gap-threshold-pt", type=float, default=70.0)
    parser.add_argument("--case-label", default="UNK",
                        help="Case identifier surfaced in audit reports / "
                             "snapshots (Day 17 — was hard-coded CASE-A)")
    args = parser.parse_args(argv)

    workdir = Path(args.workdir)
    if not workdir.is_dir():
        print(f"workdir not a directory: {workdir}", file=sys.stderr)
        return 1
    if not (workdir / "main.tex").is_file():
        print(f"workdir missing main.tex: {workdir}", file=sys.stderr)
        return 1

    result = run_loop(workdir, Path(args.output_root),
                      target_issue_code=args.target_issue_code,
                      max_rounds=args.max_rounds,
                      gap_threshold_pt=args.gap_threshold_pt,
                      case_label=args.case_label)
    print(f"\nfinal_status: {result['final_status']}")
    print(f"taboo entries: {len(result['taboo'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
