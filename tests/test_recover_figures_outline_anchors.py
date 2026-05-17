"""CASE-A regression: recover_figures uses outline.json docx_para_idx
when available, instead of regex re-detection (which lacks cluster
suppression and trips on '全文结构安排' mention paragraphs).

Also covers CASE-A caption-digit normalization: customer-typed labels
like '图4-1 0' / '图4-1 2 (a)' must compress whitespace inside the
number run, otherwise CAPTION_PAT captures only the first digit.
"""
import json
from pathlib import Path

from scripts.recover_figures import (
    load_outline_anchors,
    _normalize_caption_digits,
    inject_into_chapter,
)


def _write(tmp_path, name: str, payload: dict) -> str:
    p = tmp_path / name
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_load_outline_anchors_happy_path(tmp_path):
    path = _write(tmp_path, "outline.json", {
        "chapters": [
            {"filename": "ch01.tex", "title": "第一章 绪论",
             "latex_title": "绪论", "docx_para_idx": 46},
            {"filename": "ch02.tex", "title": "第二章 系统设计",
             "latex_title": "系统设计", "docx_para_idx": 66},
            {"filename": "ch03.tex", "title": "第三章 模型训练",
             "latex_title": "模型训练", "docx_para_idx": 114},
            {"filename": "ch04.tex", "title": "第四章 实验结果",
             "latex_title": "实验结果", "docx_para_idx": 180},
            {"filename": "ch05.tex", "title": "第五章 结论",
             "latex_title": "结论", "docx_para_idx": 453},
        ],
        "special_sections": {},
    })
    anchors = load_outline_anchors(path)
    assert anchors == [(1, 46), (2, 66), (3, 114), (4, 180), (5, 453)]


def test_load_outline_anchors_missing_field_returns_none(tmp_path):
    """Old extractor output without docx_para_idx → caller falls back to regex."""
    path = _write(tmp_path, "outline.json", {
        "chapters": [
            {"filename": "ch01.tex", "title": "第一章 绪论",
             "latex_title": "绪论"},
            {"filename": "ch02.tex", "title": "第二章 系统设计",
             "latex_title": "系统设计"},
        ],
        "special_sections": {},
    })
    assert load_outline_anchors(path) is None


def test_load_outline_anchors_partial_field_returns_none(tmp_path):
    """One chapter missing docx_para_idx is still fallback (no partial trust)."""
    path = _write(tmp_path, "outline.json", {
        "chapters": [
            {"filename": "ch01.tex", "title": "第一章 绪论",
             "latex_title": "绪论", "docx_para_idx": 46},
            {"filename": "ch02.tex", "title": "第二章 系统设计",
             "latex_title": "系统设计"},  # missing
        ],
        "special_sections": {},
    })
    assert load_outline_anchors(path) is None


def test_load_outline_anchors_bad_filename_returns_none(tmp_path):
    """filename doesn't match chNN.tex → fall back."""
    path = _write(tmp_path, "outline.json", {
        "chapters": [
            {"filename": "intro.tex", "title": "第一章",
             "latex_title": "绪论", "docx_para_idx": 46},
        ],
        "special_sections": {},
    })
    assert load_outline_anchors(path) is None


def test_load_outline_anchors_missing_file_returns_none(tmp_path):
    assert load_outline_anchors(str(tmp_path / "nonexistent.json")) is None


# ===== CASE-A caption-digit whitespace normalization =====


def test_normalize_caption_digits_clean_input_unchanged():
    """Already-clean labels are not modified."""
    assert _normalize_caption_digits("图4-1") == "图4-1"
    assert _normalize_caption_digits("图4-12") == "图4-12"
    assert _normalize_caption_digits("图4-1 不同方法对比") == "图4-1 不同方法对比"


def test_normalize_caption_digits_dash_internal_space():
    """'图4- 9' (space after dash) → '图4-9'."""
    assert _normalize_caption_digits("图4- 9") == "图4-9"


def test_normalize_caption_digits_dash_leading_space():
    """'图4 -1' (space before dash) → '图4-1'."""
    assert _normalize_caption_digits("图4 -1") == "图4-1"


def test_normalize_caption_digits_double_digit_split():
    """'图4-1 0' / '图4-1 1' / '图4-1 2' → '图4-10' / '图4-11' / '图4-12'."""
    assert _normalize_caption_digits("图4-1 0") == "图4-10"
    assert _normalize_caption_digits("图4-1 1") == "图4-11"
    assert _normalize_caption_digits("图4-1 2") == "图4-12"


def test_normalize_caption_digits_with_subfigure_letter():
    """'图4-1 2 (a)' → '图4-12 (a)' — split digits compressed, (a) preserved."""
    assert _normalize_caption_digits("图4-1 2 (a)") == "图4-12 (a)"
    assert _normalize_caption_digits("图4-1 2 (b)") == "图4-12 (b)"


def test_normalize_caption_digits_two_digit_chapter():
    """'图1 0-1' → '图10-1' (chapter 10)."""
    assert _normalize_caption_digits("图1 0-1") == "图10-1"


def test_normalize_caption_digits_inline_ref():
    """Whitespace inside number on inline body refs also normalized."""
    assert _normalize_caption_digits("如图4-1 0所示给出") == "如图4-10所示给出"


def test_normalize_caption_digits_does_not_affect_unrelated_digits():
    """Digits not preceded by '图' label are untouched."""
    assert _normalize_caption_digits("第4-1 章节") == "第4-1 章节"
    assert _normalize_caption_digits("公式 4-1 0") == "公式 4-1 0"


def test_load_outline_anchors_unsorted_input_sorted_output(tmp_path):
    """Outline chapters in any order → anchors returned sorted by para idx."""
    path = _write(tmp_path, "outline.json", {
        "chapters": [
            {"filename": "ch03.tex", "title": "三",
             "latex_title": "三", "docx_para_idx": 200},
            {"filename": "ch01.tex", "title": "一",
             "latex_title": "一", "docx_para_idx": 50},
            {"filename": "ch02.tex", "title": "二",
             "latex_title": "二", "docx_para_idx": 100},
        ],
        "special_sections": {},
    })
    anchors = load_outline_anchors(path)
    assert [idx for _, idx in anchors] == [50, 100, 200]
    assert [num for num, _ in anchors] == [1, 2, 3]


def test_inject_skips_when_image_already_in_chapter(tmp_path):
    r"""CASE-A dedup: AST Figure block 已 emit \includegraphics{media/image23.png}
    + \caption + \label, recover_figures 不应再为同 image 的 record emit 第二次.
    旧版 fallback inline-ref 路径不识别 chapter 已有 image, 致重复 \begin{figure}."""
    chapter = tmp_path / "ch04.tex"
    chapter.write_text(
        r"""\chapter{实验结果}

\section{实验对比}

直观对比图如下图所示:

\begin{figure}[H]
  \centering
  \includegraphics[width=0.90\textwidth]{media/image23.png}
  \caption{不同放大倍数的超分辨率方法直观对比}
  \label{fig:4-7}
\end{figure}

图4-7直观展示了检测性能F1和FPS推理速度的权衡关系。
""",
        encoding="utf-8",
    )
    record = {
        "caption_chapter": 4,
        "caption_subnum": 7,
        "caption_text": "不同放大倍数的超分辨率方法直观对比",
        "image_filenames": ["image23.png"],
        "drawing_para": 360,
    }
    report = {"matched": [], "warnings": [], "unreferenced": []}
    n = inject_into_chapter(str(chapter), [record], report)
    new_text = chapter.read_text(encoding="utf-8")
    assert n == 0, "AST 已 emit, recover_figures 应 skip 这条 record"
    assert new_text.count(r"\includegraphics") == 1, (
        r"image23.png 应只 emit 1 次, 不允许重复 \includegraphics"
    )
    assert new_text.count(r"\begin{figure}") == 1
    assert any("skipped" in m for m in report["matched"]), \
        "report 应记录 skip 决策"


def test_inject_does_not_insert_inside_longtable(tmp_path):
    r"""CASE-A #2: \caption{图4-3 ...} 在 longtable 内时, inline-ref fallback 不
    应把 \begin{figure} 插到 longtable 内部 — 否则非法嵌套 + xelatex 渲染 \toprule
    中断为粗黑横线."""
    chapter = tmp_path / "ch04.tex"
    chapter.write_text(
        r"""\chapter{实验}

\subsection{对比实验}

\begin{longtable}{ccc}
  \caption{图4-3 不同方法性能对比} \\
  \toprule
  \endfirsthead
  \bottomrule
  \endlastfoot
  A & B & C \\
\end{longtable}

如图4-3所示。
""",
        encoding="utf-8",
    )
    record = {
        "caption_chapter": 4,
        "caption_subnum": 3,
        "caption_text": "不同方法性能对比",
        "image_filenames": ["image13.png"],
        "drawing_para": 360,
    }
    report = {"matched": [], "warnings": [], "unreferenced": []}
    n = inject_into_chapter(str(chapter), [record], report)
    new_text = chapter.read_text(encoding="utf-8")
    # \begin{figure} 必须在 \end{longtable} 之后, 不在 longtable 内
    end_pos = new_text.index(r"\end{longtable}")
    fig_pos = new_text.index(r"\begin{figure}")
    assert fig_pos > end_pos, (
        f"\\begin{{figure}} 必须在 \\end{{longtable}} 之后. "
        f"实际: figure@{fig_pos}  end_longtable@{end_pos}"
    )
    assert n == 1


def test_inject_emits_when_image_not_in_chapter(tmp_path):
    r"""CASE-A dedup 反向: chapter 没有该 image 时, recover_figures 仍正常 emit."""
    chapter = tmp_path / "ch04.tex"
    chapter.write_text(
        r"""\chapter{实验结果}

\section{对比图}

如图4-7所示。
""",
        encoding="utf-8",
    )
    record = {
        "caption_chapter": 4,
        "caption_subnum": 7,
        "caption_text": "对比图",
        "image_filenames": ["image23.png"],
        "drawing_para": 360,
    }
    report = {"matched": [], "warnings": [], "unreferenced": []}
    n = inject_into_chapter(str(chapter), [record], report)
    new_text = chapter.read_text(encoding="utf-8")
    assert n == 1
    assert r"\includegraphics" in new_text
    assert "image23.png" in new_text
