"""W3 deterministic mutants — 3 个最小 docx 各触发一个 P0 候选 (D40/D41/D42).

每个 mutant 进 pytest, 防 shared fix 后续回归.
"""
from __future__ import annotations
import zipfile
from pathlib import Path

HERE = Path(__file__).parent

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>"""


def _wrap_doc(body_xml: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">
  <w:body>{body_xml}</w:body>
</w:document>"""


def _write_docx(path: Path, doc_xml: str):
    if path.exists():
        path.unlink()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("word/_rels/document.xml.rels", DOC_RELS)
        z.writestr("word/document.xml", doc_xml)
    print(f"wrote {path.name} ({path.stat().st_size} bytes)")


def build_mutant_caption_math():
    """D41: figure caption 含 OOXML <m:oMath> 公式 |Δτ_m|.
    期望: source_manifest 检测 has_omath; recover_figures._text_of_paragraph
    抓 <m:t> 内容拼 $...$.
    """
    body = """
<w:p><w:r><w:t>正文段示意.</w:t></w:r></w:p>
<w:p><w:r><w:t>图3-4：不同采样频率下各阵元的</w:t></w:r><m:oMath><m:r><m:t>|Δτ_m|</m:t></m:r></m:oMath></w:p>
<w:p><w:r><w:t>下文段.</w:t></w:r></w:p>
"""
    _write_docx(HERE / "mutant_caption_math.docx", _wrap_doc(body))


def build_mutant_caption_lookalike():
    """D42: caption 后跟 "图X-Y 给出了..." 长解说段, 期望 recover 后保留."""
    body = """
<w:p><w:r><w:t>第三章.</w:t></w:r></w:p>
<w:p><w:r><w:t>图3-4：测试 caption</w:t></w:r></w:p>
<w:p><w:r><w:t>图3-4 给出了不同 fs/B 取值下各阵元的分布, 随着采样频率的提高, 各阵元的残余时延整体呈下降趋势, 逐步向零靠近。</w:t></w:r></w:p>
"""
    _write_docx(HERE / "mutant_caption_lookalike.docx", _wrap_doc(body))


def build_mutant_inline_eq():
    """D40: 段落整段 inline `$math$（X-Y）` 全角 + 半角 各一个.
    期望: chapter emit 时检测后转 \\begin{equation}...\\tag.
    """
    body = """
<w:p><w:r><w:t>整段公式 (半角):</w:t></w:r></w:p>
<w:p><w:r><w:t>$x + y = z$ (3-1)</w:t></w:r></w:p>
<w:p><w:r><w:t>整段公式 (全角):</w:t></w:r></w:p>
<w:p><w:r><w:t>$a + b = c$（3-2）</w:t></w:r></w:p>
<w:p><w:r><w:t>正文 inline ref 不应转 (negative test): 如式 $x+y$ (3-1) 所示.</w:t></w:r></w:p>
"""
    _write_docx(HERE / "mutant_inline_eq.docx", _wrap_doc(body))


if __name__ == "__main__":
    build_mutant_caption_math()
    build_mutant_caption_lookalike()
    build_mutant_inline_eq()
