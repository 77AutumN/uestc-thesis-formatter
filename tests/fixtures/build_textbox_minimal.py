"""Generate minimal docx fixture with textbox-as-caption pattern (D39, CASE-A).

The shape we synthesize:
  - 1 normal heading paragraph
  - 1 paragraph with an inline image + adjacent textbox containing "图1-1 demo caption"
  - 1 trailing body paragraph

Resulting docx triggers D39: pandoc loses textbox content; collect_textbox_captions
should recover the 图1-1 caption.

Usage: `python build_textbox_minimal.py` regenerates `textbox_caption_minimal.docx`.
"""
from __future__ import annotations
import os
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "textbox_caption_minimal.docx"

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

# Minimal document.xml with a textbox containing 图1-1 caption.
# Real Word output is more verbose; this captures the shape collect_textbox_captions
# needs to handle: a <w:txbxContent> wrapping a <w:p>...<w:t>图1-1 ...</w:t>.
DOCUMENT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
            xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>第一章 引言</w:t></w:r></w:p>
    <w:p><w:r><w:t>下面展示一张测试图片。</w:t></w:r></w:p>
    <w:p>
      <w:r>
        <mc:AlternateContent>
          <mc:Choice Requires="wps">
            <w:drawing>
              <wp:inline>
                <w:txbxContent>
                  <w:p><w:r><w:t>图1-1 测试图片说明</w:t></w:r></w:p>
                </w:txbxContent>
              </wp:inline>
            </w:drawing>
          </mc:Choice>
          <mc:Fallback>
            <w:drawing>
              <wp:inline>
                <w:txbxContent>
                  <w:p><w:r><w:t>图1-1 测试图片说明</w:t></w:r></w:p>
                </w:txbxContent>
              </wp:inline>
            </w:drawing>
          </mc:Fallback>
        </mc:AlternateContent>
      </w:r>
    </w:p>
    <w:p><w:r><w:t>本章简要介绍研究背景。</w:t></w:r></w:p>
  </w:body>
</w:document>"""


def build():
    if OUT.exists():
        OUT.unlink()
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("word/_rels/document.xml.rels", DOC_RELS)
        z.writestr("word/document.xml", DOCUMENT)
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    build()
