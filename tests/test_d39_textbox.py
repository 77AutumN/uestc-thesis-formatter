"""tests/test_d39_textbox.py — D39 (textbox-as-caption) 端到端 fixture suite.

3 项: collector (pandoc_ast_extract) / merge (recover_figures) / Check 9 (product_audit).
依赖 tests/fixtures/textbox_caption_minimal.docx (build_textbox_minimal.py 产物).
"""
from __future__ import annotations
import json
import os
import sys
import tempfile

import pytest

THIS = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(THIS, "..", "scripts"))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

FIXTURE_DOCX = os.path.join(THIS, "fixtures", "textbox_caption_minimal.docx")


def _need_fixture():
    if not os.path.isfile(FIXTURE_DOCX):
        pytest.skip(f"fixture missing: {FIXTURE_DOCX} (run build_textbox_minimal.py)")


def test_collect_textbox_captions_minimal_fixture():
    """D39: collect_textbox_captions reads <w:txbxContent> 'figX-Y' caption."""
    _need_fixture()
    import pandoc_ast_extract as ext
    with tempfile.TemporaryDirectory() as td:
        captions = ext.collect_textbox_captions(FIXTURE_DOCX, td)
        assert len(captions) == 1
        assert captions[0]["label"] == "图1-1"
        assert "测试图片说明" in captions[0]["caption"]
        # JSON 落盘正确
        json_path = os.path.join(td, "textbox_captions.json")
        assert os.path.isfile(json_path)
        loaded = json.loads(open(json_path, encoding="utf-8").read())
        assert loaded == captions


def test_merge_textbox_captions_fills_record_caption():
    """D39: recover_figures.merge_textbox_captions 给缺 caption 的 record 注入 caption."""
    import recover_figures as rf
    with tempfile.TemporaryDirectory() as td:
        # 写一个 textbox_captions.json
        captions = [
            {"label": "图1-1", "caption": "图1-1 测试图片说明", "tx_idx": 0},
        ]
        cap_path = os.path.join(td, "textbox_captions.json")
        with open(cap_path, "w", encoding="utf-8") as f:
            json.dump(captions, f, ensure_ascii=False)

        # 模拟一个无 caption_text 的 record (chapter=1)
        records = [
            {
                "drawing_para": 5,
                "image_filenames": ["image2.png"],
                "caption_para": None,
                "caption_text": None,
                "caption_chapter": None,
                "caption_subnum": None,
                "chapter": 1,
            }
        ]
        filled = rf.merge_textbox_captions(records, cap_path)
        assert filled == 1
        assert records[0]["caption_text"] == "测试图片说明"
        assert records[0]["caption_chapter"] == 1
        assert records[0]["caption_subnum"] == 1


def test_merge_textbox_captions_no_json_silent_skip():
    """D39: merge_textbox_captions 在 json 不存在时返回 0 (不抛)."""
    import recover_figures as rf
    records = [{"caption_text": None, "chapter": 1}]
    filled = rf.merge_textbox_captions(records, "/nonexistent/path.json")
    assert filled == 0


def test_check_figure_caption_parity_passes_when_aligned():
    """D39: Check 9 在 caption 全非空 + 编号连续时 pass."""
    import product_audit as pa
    with tempfile.TemporaryDirectory() as td:
        # workdir = td/DissertationUESTC
        workdir = os.path.join(td, "DissertationUESTC")
        chap_dir = os.path.join(workdir, "chapter")
        os.makedirs(chap_dir)
        with open(os.path.join(chap_dir, "ch01.tex"), "w", encoding="utf-8") as f:
            f.write(
                "\\begin{figure}\n  \\caption{测试}\n  \\label{fig:1-1}\n\\end{figure}\n"
            )
        # extracted dir with json
        extracted = os.path.join(td, "extracted")
        os.makedirs(extracted)
        with open(os.path.join(extracted, "textbox_captions.json"), "w", encoding="utf-8") as f:
            json.dump([{"label": "图1-1", "caption": "图1-1 测试", "tx_idx": 0}], f)

        passed, lines = pa.check_figure_caption_parity(workdir, extracted)
        assert passed, "\n".join(lines)


def test_check_figure_caption_parity_advisory_on_empty_caption_only():
    """CASE-A: 单纯 caption 文字空 (编号正常) 是 C 类客户内容缺失, 降 advisory.
    Check 9 不再 P0 阻断, 写入 client_feedback 退回客户填补图名."""
    import product_audit as pa
    with tempfile.TemporaryDirectory() as td:
        workdir = os.path.join(td, "DissertationUESTC")
        chap_dir = os.path.join(workdir, "chapter")
        os.makedirs(chap_dir)
        with open(os.path.join(chap_dir, "ch01.tex"), "w", encoding="utf-8") as f:
            f.write(
                "\\begin{figure}\n  \\caption{}\n  \\label{fig:1-1}\n\\end{figure}\n"
            )
        extracted = os.path.join(td, "extracted")
        os.makedirs(extracted)
        passed, lines = pa.check_figure_caption_parity(workdir, extracted)
        # CASE-A policy: empty caption + sequence sane → advisory, not block.
        assert passed
        assert any("C 类客户内容缺失" in line for line in lines)


def test_check_figure_caption_parity_fails_on_numbering_gap():
    """编号跳号是结构 bug — 仍 P0 阻断 (CASE-A policy 不放过结构问题)."""
    import product_audit as pa
    with tempfile.TemporaryDirectory() as td:
        workdir = os.path.join(td, "DissertationUESTC")
        chap_dir = os.path.join(workdir, "chapter")
        os.makedirs(chap_dir)
        with open(os.path.join(chap_dir, "ch01.tex"), "w", encoding="utf-8") as f:
            # ch01: fig:1-1, fig:1-3 跳了 1-2 → 编号异常
            f.write(
                "\\begin{figure}\n  \\caption{}\n  \\label{fig:1-1}\n\\end{figure}\n"
                "\\begin{figure}\n  \\caption{}\n  \\label{fig:1-3}\n\\end{figure}\n"
            )
        extracted = os.path.join(td, "extracted")
        os.makedirs(extracted)
        passed, lines = pa.check_figure_caption_parity(workdir, extracted)
        assert not passed
        assert any("编号序列异常" in line for line in lines)
