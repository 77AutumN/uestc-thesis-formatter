"""SyncTeX reverse-locator (Phase 1).

Given a PDF page + (x, y) coordinate (top-left origin, big point), returns
the originating ``tex_file`` + ``tex_line`` by shelling ``synctex edit``
inside the project's pinned Docker image.

Origin: ``work/_v5_spike_synctex_acid_test.py`` (Day 1 spike, Day 1 PASS:
two duplicate-caption figures resolved to two correct distinct source lines
in CASE-A ch04).

Why Docker not native: the host (Windows 10/11) does not ship ``synctex``
binary; the project's pinned ``ghcr.io/xu-cheng/texlive-full:20240101``
already includes it. Each call is one Docker invocation (~0.5–1.5 s round
trip) — acceptable for MVP since per-PDF audit emits dozens not thousands
of issues. If perf becomes a problem later, batch many queries into one
``docker exec`` against a pre-warmed container.

Coordinate system note (verified Day 1 spike):
    PyMuPDF page bbox     → (x, y) pt, top-left origin
    SyncTeX edit -o       → page:x:y, top-left origin, big point (1 bp = 1 pt)
    direct mapping, no transform required.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional


# Pinned in CLAUDE.md / project convention
DEFAULT_DOCKER_IMAGE = "ghcr.io/xu-cheng/texlive-full:20240101"

# SyncTeX prefixes the input file with `<docker-mount-root>/./` (e.g.
# ``/thesis/./chapter/ch04.tex``). We strip that to recover host-relative
# paths.
_INPUT_PREFIX_RE = re.compile(r"^/thesis/(?:\./)?(.*)$")

_OUTPUT_RE = re.compile(r"^Output:\s*(.+)$")
_INPUT_RE = re.compile(r"^Input:\s*(.+)$")
_LINE_RE = re.compile(r"^Line:\s*(\d+)$")
_COLUMN_RE = re.compile(r"^Column:\s*(-?\d+)$")


@dataclass
class SyncTeXRecord:
    tex_file: str       # relative to skill / workdir root, e.g. "chapter/ch04.tex"
    tex_line: int       # 1-based
    column: Optional[int] = None   # -1 in CJK / unknown
    raw_input: Optional[str] = None  # original synctex Input: line, for debug

    def to_location_dict(self) -> dict:
        return {
            "tex_file": self.tex_file,
            "tex_line": self.tex_line,
            "column": self.column,
            "resolution_method": "synctex",
        }


class SyncTeXLocator:
    """Wrapper around ``synctex edit`` over Docker.

    Caller is expected to keep one instance per ``workdir`` for the duration
    of an audit. ``locate(...)`` may be called many times.
    """

    def __init__(self, workdir, docker_image: str = DEFAULT_DOCKER_IMAGE,
                 pdf_filename: str = "main.pdf"):
        self.workdir = Path(workdir)
        if not self.workdir.is_dir():
            raise FileNotFoundError(f"workdir does not exist: {self.workdir}")
        synctex_gz = self.workdir / "main.synctex.gz"
        if not synctex_gz.is_file():
            # locator can still be constructed but locate() will return None
            # — surface this once at __init__ rather than failing per call
            self._available = False
            self._reason = f"main.synctex.gz not found in {workdir}"
        else:
            self._available = True
            self._reason = None
        self.docker_image = docker_image
        self.pdf_filename = pdf_filename

    @property
    def available(self) -> bool:
        return self._available

    @property
    def unavailable_reason(self) -> Optional[str]:
        return self._reason

    def _docker_cmd(self, page: int, x: float, y: float) -> List[str]:
        # Mount workdir as /thesis (matches the project compile command convention)
        mount_src = str(self.workdir).replace("\\", "/")
        return [
            "docker", "run", "--rm",
            "-v", f"{mount_src}:/thesis",
            "-w", "/thesis",
            self.docker_image,
            "synctex", "edit",
            "-o", f"{page}:{x}:{y}:{self.pdf_filename}",
        ]

    @staticmethod
    def parse_synctex_output(stdout: str) -> List[SyncTeXRecord]:
        """Parse one or more ``Output: / Input: / Line: / Column:`` records.

        SyncTeX may emit multiple records for ambiguous queries — usually the
        first is the most precise (per ``synctex help view``). Caller decides
        which to use. We surface all.
        """
        records: List[SyncTeXRecord] = []
        cur: dict = {}
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            m = _OUTPUT_RE.match(line)
            if m:
                if cur.get("input"):
                    records.append(_record_from_dict(cur))
                cur = {"output": m.group(1)}
                continue
            m = _INPUT_RE.match(line)
            if m:
                cur["input"] = m.group(1)
                continue
            m = _LINE_RE.match(line)
            if m:
                cur["line"] = int(m.group(1)); continue
            m = _COLUMN_RE.match(line)
            if m:
                cur["column"] = int(m.group(1)); continue
        if cur.get("input") and cur.get("line") is not None:
            records.append(_record_from_dict(cur))
        return records

    def locate(self, page: int, x: float, y: float,
               timeout: float = 30.0) -> Optional[SyncTeXRecord]:
        """Return the most-precise SyncTeXRecord, or None on failure / no synctex."""
        if not self._available:
            return None
        try:
            res = subprocess.run(self._docker_cmd(page, x, y),
                                 capture_output=True, text=True,
                                 encoding="utf-8", timeout=timeout)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return None
        if res.returncode != 0:
            return None
        records = self.parse_synctex_output(res.stdout or "")
        return records[0] if records else None

    def locate_many(self, queries: Iterable) -> List[Optional[SyncTeXRecord]]:
        """Convenience: bulk locate, in input order. No batching yet (MVP)."""
        return [self.locate(p, x, y) for (p, x, y) in queries]


def _record_from_dict(d: dict) -> SyncTeXRecord:
    raw_input = d.get("input", "")
    m = _INPUT_PREFIX_RE.match(raw_input)
    tex_file = m.group(1) if m else raw_input
    return SyncTeXRecord(
        tex_file=tex_file.replace("\\", "/"),
        tex_line=int(d.get("line", 0)),
        column=d.get("column"),
        raw_input=raw_input,
    )
