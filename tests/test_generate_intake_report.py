"""tests/test_generate_intake_report.py — Round 8 阶段 B."""
import os
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(THIS, "..", "scripts"))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import generate_intake_report as gir  # noqa: E402


def test_section_basic_with_real_file(tmp_path):
    """basic section 含 docx path + size."""
    fake = tmp_path / "x.docx"
    fake.write_bytes(b"x" * 1024)
    lines = gir._section_basic(str(fake))
    txt = "\n".join(lines)
    assert "## 1. 基本信息" in txt
    assert "x.docx" in txt
    assert "KB" in txt


def test_section_basic_missing_file(tmp_path):
    """文件不存在时报 ❌"""
    lines = gir._section_basic(str(tmp_path / "noexist.docx"))
    txt = "\n".join(lines)
    assert "❌" in txt


def test_integration_case_anon_full_intake(tmp_path):
    """CASE-A docx 应生成 6 节完整 intake."""
    repo = os.environ.get("THESIS_REPO_ROOT", "")
    docx = os.path.join(repo, "work", "新case.docx")
    if not os.path.isfile(docx):
        import pytest
        pytest.skip("CASE-A docx 不存在, 跳过集成测试")

    out_path = str(tmp_path / "intake.md")
    md = gir.generate(docx, out_path)

    # 6 节齐
    assert "## 1. 基本信息" in md
    assert "## 2. Profile 决策推荐" in md
    assert "## 3. Preflight 检查" in md
    assert "## 4. Risk Router" in md
    assert "## 5. 客户原稿瑕疵" in md
    assert "## 6. 建议路径" in md

    # 关键数据
    assert "uestc-bachelor" in md  # profile router 命中
    assert "BACHELOR" in md or "学士" in md  # 证据
    assert "12" in md or "11" in md or "10" in md  # risk hits 数量

    # 文件已写
    assert os.path.isfile(out_path)
