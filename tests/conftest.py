"""Shared fixtures for thesis-formatter tests."""
import sys
import os
from pathlib import Path
import pytest

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts")
sys.path.insert(0, SCRIPTS_DIR)


def pytest_addoption(parser):
    parser.addoption(
        "--pdf", action="store", default=None,
        help="待审计 PDF 绝对路径 (覆盖测试中硬编码 / PDF_PATH env)"
    )
    parser.addoption(
        "--extracted-dir", action="store", default=None,
        help="extracted/ 目录路径 (含 cite_map.json, outline.json, chapters/)"
    )
    parser.addoption(
        "--workdir", action="store", default=None,
        help="DissertationUESTC 工作目录 (含 main.tex, ref.bib, media/, chapter/)"
    )
    parser.addoption(
        "--oracle-pdf", action="store",
        default=None,
        help="黄金参考 PDF 路径 (默认 workA/main_final_v2.pdf, CASE-A 已验收本科)"
    )


@pytest.fixture(scope="session")
def audit_pdf_path(request):
    path = request.config.getoption("--pdf") or os.environ.get("PDF_PATH")
    if not path or not os.path.exists(path):
        pytest.skip(f"--pdf / PDF_PATH 未指定或不存在: {path!r}")
    return path


@pytest.fixture(scope="session")
def audit_pdf(audit_pdf_path):
    try:
        import fitz
    except ImportError:
        pytest.skip("PyMuPDF (fitz) not installed")
    return fitz.open(audit_pdf_path)


@pytest.fixture(scope="session")
def extracted_dir(request):
    path = request.config.getoption("--extracted-dir")
    if not path:
        pytest.skip("--extracted-dir 未指定")
    p = Path(path)
    if not p.exists() or not p.is_dir():
        pytest.skip(f"--extracted-dir 不存在或非目录: {path!r}")
    return p


@pytest.fixture(scope="session")
def workdir(request):
    path = request.config.getoption("--workdir")
    if not path:
        pytest.skip("--workdir 未指定")
    p = Path(path)
    if not p.exists() or not p.is_dir():
        pytest.skip(f"--workdir 不存在或非目录: {path!r}")
    return p


@pytest.fixture(scope="session")
def oracle_pdf(request):
    try:
        import fitz
    except ImportError:
        pytest.skip("PyMuPDF (fitz) not installed")
    path = request.config.getoption("--oracle-pdf")
    if not os.path.exists(path):
        pytest.skip(f"oracle PDF 不存在: {path!r}")
    return fitz.open(path)
