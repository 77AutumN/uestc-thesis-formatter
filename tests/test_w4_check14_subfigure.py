"""tests/test_w4_check14_subfigure.py — W4 Check 14 subfigure parity 单元测试.

直接测试 `_subfigure_parity_from_manifest` 核心算法, 不依赖 docx 真实 fixture
(multi-image docx 较复杂, 需 word/media/*.png 真实文件 + rels 注册;
核心算法是纯逻辑, 单元测试足以防回归).

CASE-A 三角的子图问题: docx 一 paragraph 含 N 张 image (subfigure 组),
pandoc 或 recover_figures 只抓第一张. Check 14 advisory 起手, 报漏抓.
"""
from __future__ import annotations
import os
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(THIS, "..", "scripts"))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import product_audit as pa  # noqa: E402


def _mk_manifest(figures):
    return {"figures": figures}


def test_check14_no_figures():
    """空 figures list → trivial pass, 0 missing."""
    r = pa._subfigure_parity_from_manifest(_mk_manifest([]), set())
    assert r["n_src_figs_with_image"] == 0
    assert r["n_multi_image_figs"] == 0
    assert r["total_src_imgs"] == 0
    assert r["missing_in_chap"] == []


def test_check14_single_image_per_figure_no_subfigure():
    """每个 figure 单 image (非子图组) → 0 multi_image, 0 missing."""
    figs = [
        {"id": "fig1", "image_filenames": ["chart01.png"]},
        {"id": "fig2", "image_filenames": ["chart02.png"]},
    ]
    chap_refs = {"chart01.png", "chart02.png"}
    r = pa._subfigure_parity_from_manifest(_mk_manifest(figs), chap_refs)
    assert r["n_src_figs_with_image"] == 2
    assert r["n_multi_image_figs"] == 0
    assert r["total_src_imgs"] == 2
    assert r["missing_in_chap"] == []


def test_check14_subfigure_all_referenced_passes():
    """3 子图全在 chapter 引用 → 0 missing."""
    figs = [{
        "id": "fig_3_4",
        "image_filenames": ["sub_a.png", "sub_b.png", "sub_c.png"],
    }]
    chap_refs = {"sub_a.png", "sub_b.png", "sub_c.png"}
    r = pa._subfigure_parity_from_manifest(_mk_manifest(figs), chap_refs)
    assert r["n_multi_image_figs"] == 1
    assert r["total_src_imgs"] == 3
    assert r["missing_in_chap"] == []


def test_check14_subfigure_two_dropped_advisory():
    """3 子图只引用第 1 张 (CASE-A 子图拆解症状) → 2 missing."""
    figs = [{
        "id": "fig_3_4",
        "image_filenames": ["sub_a.png", "sub_b.png", "sub_c.png"],
    }]
    chap_refs = {"sub_a.png"}  # 只第一张被 \includegraphics
    r = pa._subfigure_parity_from_manifest(_mk_manifest(figs), chap_refs)
    assert r["n_multi_image_figs"] == 1
    assert r["total_src_imgs"] == 3
    missing_bases = [b for _, b in r["missing_in_chap"]]
    assert "sub_b.png" in missing_bases
    assert "sub_c.png" in missing_bases
    assert "sub_a.png" not in missing_bases


def test_check14_excludes_template_imgs():
    """ALLOWED_UNREFERENCED (校徽 image1.jpeg 等) 不计."""
    figs = [{
        "id": "fig_cover",
        "image_filenames": ["image1.jpeg", "real_chart.png"],
    }]
    chap_refs = {"real_chart.png"}
    r = pa._subfigure_parity_from_manifest(_mk_manifest(figs), chap_refs)
    # 校徽排除后只剩 1 张 → 不算多 image 组
    assert r["total_src_imgs"] == 1
    assert r["n_multi_image_figs"] == 0
    assert r["missing_in_chap"] == []


def test_check14_path_basename_normalized():
    """source_manifest image_filenames 含路径前缀 → 用 basename 比对."""
    figs = [{
        "id": "fig_x",
        "image_filenames": ["word/media/sub_a.png", "word/media/sub_b.png"],
    }]
    chap_refs = {"sub_a.png", "sub_b.png"}
    r = pa._subfigure_parity_from_manifest(_mk_manifest(figs), chap_refs)
    assert r["missing_in_chap"] == []


def test_check14_missing_in_chap_preserves_fig_id():
    """missing_in_chap 应记录 fig_id (用于 advisory 报告)."""
    figs = [{
        "id": "fig_5_2",
        "image_filenames": ["a.png", "b.png", "c.png"],
    }]
    r = pa._subfigure_parity_from_manifest(_mk_manifest(figs), set())  # 全 missing
    assert all(fid == "fig_5_2" for fid, _ in r["missing_in_chap"])
    assert len(r["missing_in_chap"]) == 3


def test_check14_multiple_figures_mixed():
    """多 figure: 一个全引用, 一个有 missing → 只报 missing 的子图."""
    figs = [
        {"id": "fig_ok", "image_filenames": ["x1.png", "x2.png"]},
        {"id": "fig_drop", "image_filenames": ["y1.png", "y2.png", "y3.png"]},
    ]
    chap_refs = {"x1.png", "x2.png", "y1.png"}
    r = pa._subfigure_parity_from_manifest(_mk_manifest(figs), chap_refs)
    assert r["n_multi_image_figs"] == 2
    assert r["total_src_imgs"] == 5
    miss_ids = {fid for fid, _ in r["missing_in_chap"]}
    assert miss_ids == {"fig_drop"}
    assert len(r["missing_in_chap"]) == 2  # y2 + y3
