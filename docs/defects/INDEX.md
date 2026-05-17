# 缺陷卡片索引 (D-card INDEX)

> 自动生成 — 不要手动编辑. 改动来源: `reference/defects/D??.md`
> 重新生成: `python scripts/build_defect_index.py`

**总数**: 50 张卡片. **AI 友好版**: `dashboard.json` (jq 检索).

## 按命中频率排序 (Top 5 最常踩)

| Rank | ID | 频率 | 标题 | 状态 | severity |
|------|----|------|------|------|----------|
| 1 | [D40](D40.md) | 3 | 整段 inline `$math$ + (X-Y)/（X-Y）` 应转 \\begin{equati | shared_code_fixed | P0 |
| 2 | [D06](D06.md) | 2 | pandoc 把 docx 图当 inline Image 不打 Figure block → 流水 | shared_code_fixed | P0 |
| 3 | [D10](D10.md) | 2 | extractor 不识别"外文资料原文/译文" section → main.tex 不 \inp | shared_code_fixed | P0 |
| 4 | [D12](D12.md) | 2 | refs_to_bib 不处理 IEEE 格式英文文献 → 6 条参考文献被丢 | shared_code_fixed | P0 |
| 5 | [D23](D23.md) | 2 | refs_to_bib.py 漏 [C]/[S]/[R]/[P]/[Z] 文献类型 → 部分条目不入 | shared_code_fixed | P0 |

## 全部缺陷 (按 ID)

| ID | 标题 | severity | status | 学位 | cases | fix_location |
|----|------|----------|--------|------|-------|--------------|
| [D01](D01.md) | inlines_to_text 漏 Underline 容器 → 封面元数据全空 | P0 | shared_code_fixed | bachelor,master,doctor,marxism | CASE-A | scripts/pandoc_ast_extract.py:inlines_to_text() li |
| [D02](D02.md) | run_v2.py Step 3 与 Step 3.5 顺序倒置 → vendo | P0 | shared_code_fixed | bachelor,master,doctor,marxism | CASE-A | scripts/run_v2.py 把 step3_5_assemble 提到 step3_gene |
| [D03](D03.md) | refs_to_bib.py cite key 含空格逗号 → bibtex 解 | P0 | shared_code_fixed | bachelor,master,doctor,marxism | CASE-A | scripts/refs_to_bib.py:sanitize_citekey() |
| [D04](D04.md) | refs_to_bib.py author 字段用逗号分隔 → bibtex 报 | P0 | shared_code_fixed | bachelor,master,doctor,marxism | CASE-A | scripts/refs_to_bib.py:sanitize_author_list() |
| [D05](D05.md) | format_abstract.py 字面 \\n 换行 + forbidden | P0 | shared_code_fixed | bachelor,master,doctor,marxism | CASE-A | scripts/hooks/format_abstract.py (完全重写) |
| [D06](D06.md) | pandoc 把 docx 图当 inline Image 不打 Figure  | P0 | shared_code_fixed | bachelor,master,doctor,marxism | CASE-A,CASE-A | scripts/recover_figures.py (新建独立脚本, 集成 run_v2.py s |
| [D07](D07.md) | 公式 = WMF 回退渲染 pandoc 完全丢 → ~30 公式编号无本体 | P0 | shared_code_fixed | bachelor,master,doctor,marxism | CASE-A | scripts/recover_equations.py (新建, 集成 run_v2.py ste |
| [D08](D08.md) | Word 章节标题不用 Heading 样式 → AST 检不出章节 | P0 | case_private | bachelor,master,doctor,marxism | CASE-A | 当前: 手工备份 docx + python-docx 注入 Heading 1 段; 长远: To |
| [D09](D09.md) | inlines_to_text 漏 Underline 容器(D1 验证) —  | P0 | shared_code_fixed | bachelor,master,doctor,marxism | CASE-A | scripts/pandoc_ast_extract.py:inlines_to_text() (D |
| [D10](D10.md) | extractor 不识别"外文资料原文/译文" section → main. | P0 | shared_code_fixed | bachelor | CASE-A,CASE-A | scripts/pandoc_ast_extract.py + template_adapter.p |
| [D11](D11.md) | extractor refs boundary 不含 foreign → ref | P0 | shared_code_fixed | bachelor | CASE-A | scripts/pandoc_ast_extract.py Step 9 boundary 链 |
| [D12](D12.md) | refs_to_bib 不处理 IEEE 格式英文文献 → 6 条参考文献被丢 | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A,CASE-A | scripts/refs_to_bib.py IEEE_FALLBACK 启发式 + templat |
| [D13](D13.md) | LibreOffice WMF→PNG 输出整页 letter-canvas → | P0 | shared_code_fixed | bachelor,master,doctor,marxism | CASE-A | scripts/recover_equations.py PIL auto-crop + rende |
| [D14](D14.md) | 外文 \includegraphics 强 width=0.95\textwid | P1 | shared_code_fixed | bachelor | CASE-A | scripts/pandoc_ast_extract.py:_emit_foreign_sectio |
| [D15](D15.md) | _emit_foreign_section 先 emit 文字后 emit 图  | P1 | shared_code_fixed | bachelor | CASE-A | scripts/pandoc_ast_extract.py:_emit_foreign_sectio |
| [D16](D16.md) | 外文译文段落扁平化 → PDF 缺层级 (启发式恢复) | P1 | shared_code_fixed | bachelor | CASE-A | scripts/pandoc_ast_extract.py:_classify_foreign_pa |
| [D17](D17.md) | profile.degree_type 不注入 meta dict → adap | P0 | shared_code_fixed | bachelor,doctor | CASE-A | scripts/run_v2.py:357-363 (assemble_main_tex 调用前注入 |
| [D18](D18.md) | 表格模式 fallback `if cover_meta:` 太宽松 → 正文数 | P0 | shared_code_fixed | bachelor | CASE-A | scripts/pandoc_ast_extract.py:1685-1700 (Step 6.5  |
| [D19](D19.md) | abstract_en 结束边界仅认"目录"段 → 吞 TOC 章节列表 | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/pandoc_ast_extract.py:1807-1819 (用 abstrac |
| [D20](D20.md) | Windows GBK 控制台无法打印 emoji → run_v2.py 第一 | P0 | shared_code_fixed | bachelor,master,doctor,marxism | CASE-A | scripts/run_v2.py:11-19 (模块顶层 set os.environ + rec |
| [D21](D21.md) | recover_figures.py 多子图 + caption-in-same | P0 | case_private | bachelor,master,doctor | CASE-A | scripts/recover_figures.py 多处 (caption 探测策略 + mult |
| [D22](D22.md) | 摘要/关键词含 % 字符未转义 → LaTeX 注释吃掉整段 | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/template_adapter.py:200-210 (emit_abstract |
| [D23](D23.md) | refs_to_bib.py 漏 [C]/[S]/[R]/[P]/[Z] 文献类 | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A,CASE-A | scripts/refs_to_bib.py (新增 parse_proceedings/parse |
| [D24](D24.md) | \nocite{*} 致 bbl 顺序按 ref.bib 字典序而非 docx  | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/template_adapter.py:emit_bibliography_stan |
| [D25](D25.md) | refs_to_bib 英文作者 'Sun Y' 空格分隔致 BST 把 'Y' | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/refs_to_bib.py:_fix_one_author + sanitize_ |
| [D26](D26.md) | 摘要/正文 ~ 字符被 LaTeX 当不间断空格吞 → 范围号 0~3% 渲染成 | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/template_adapter.py:escape_latex_specials_ |
| [D27](D27.md) | 本科 \cite 默认行内不上标, 不符 spec "上标 [n] 12pt" | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/template_adapter.py:assemble_main_tex prea |
| [D28](D28.md) | documentclass 缺 noreminder 选项 → CLS 内置红字 | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/template_adapter.py:emit_documentclass (Ro |
| [D29](D29.md) | BST sentence-case 把 ref.bib title 中化学式/缩 | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/refs_to_bib.py:postprocess_bib_for_render  |
| [D30](D30.md) | ref.bib publisher/journal 字段裸 & 字符未 esca | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/refs_to_bib.py:postprocess_bib_for_render  |
| [D31](D31.md) | ref.bib 中文机构作者含 () 被 BST 当人名拆 → 渲染崩 "□.  | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/refs_to_bib.py:_fix_one_author (Round 8 中文 |
| [D32](D32.md) | caption 字号默认 12pt, 应 10.5pt 五号 | P1 | shared_code_fixed | bachelor,master,doctor | CASE-A,CASE-A | scripts/template_adapter.py:assemble_main_tex prea |
| [D33](D33.md) | OrderedList item 内 Para 漏走 classify_para | P1 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/pandoc_ast_extract.py:1159 OrderedList 分支  |
| [D34](D34.md) | refs_to_bib 不识别 [EB/OL] 在线资源 + 公式高度按 PNG | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/refs_to_bib.py:473 parse_electronic — [EB/ |
| [D35](D35.md) | refs 前缀正则不容忍 [N] 内/旁空格 (客户原稿手打瑕疵) | P1 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/refs_to_bib.py:612 — 把 `^\[(\d+)\]\s*` 放宽为 |
| [D36](D36.md) | latexmkrc max_repeat=1 致 natbib \cite 渲染 | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A | vendor/DissertationUESTC/latexmkrc — `$max_repeat  |
| [D37](D37.md) | assemble main.tex 早于 refs_to_bib 致 \noci | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A,CASE-A | scripts/run_v2.py:235 step3_generate_bib — refs_to |
| [D38](D38.md) | recover_figures placement 算法致图序错位 + prod | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/recover_figures.py:211 placement 算法重写 — ca |
| [D39](D39.md) | Word textbox (w:txbxContent) 装图 caption  | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/pandoc_ast_extract.py:collect_textbox_capt |
| [D40](D40.md) | 整段 inline `$math$ + (X-Y)/（X-Y）` 应转 \\be | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A,CASE-A,CASE-A | scripts/pandoc_ast_extract.py:_maybe_emit_inline_n |
| [D41](D41.md) | caption 含 inline 数学 (Word `<m:oMath>` 或  | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/recover_figures.py:_text_of_paragraph — 抓  |
| [D42](D42.md) | "图X-Y 给出了..."解说正文段被 recover_figures 误识别为 | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/recover_figures.py:inject_into_chapter — ` |
| [D43](D43.md) | refs_to_bib parse_thesis 不补 address, lun | P1 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/refs_to_bib.py — 新增 SCHOOL_TO_CITY 映射表 (60 |
| [D44](D44.md) | parse_abstract_text 关键词分隔符不归一, lun51 报"分 | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/template_adapter.py — parse_abstract_text  |
| [D45](D45.md) | format_punctuation 不归一 CJK 段中半角逗号/句号, lu | P2 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/hooks/format_punctuation.py — 新增 normalize |
| [D46](D46.md) | parse_abstract_text 不 strip 摘要段头尾占位, 致 P | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/template_adapter.py — 新加 parse_abstract_te |
| [D47](D47.md) | refs_to_bib parse_article 漏 "Y (N):P" 格式 | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/refs_to_bib.py — parse_article 加 "Y (N):P" |
| [D48](D48.md) | product_audit Check 10 v2 normalize 漏 ht | P2 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/product_audit.py — _normalize 起手加 s = html |
| [D49](D49.md) | docx_surgery W4-C — inject_heading_befor | P0 | shared_code_fixed | bachelor,master,doctor | CASE-A,CASE-A | scripts/docx_surgery.py:_apply_inject_heading_befo |
| [D50](D50.md) | refs_to_bib IEEE_FALLBACK 不补类型标识 [C]/[J] | P2 | shared_code_fixed | bachelor,master,doctor | CASE-A | scripts/refs_to_bib.py — IEEE_FALLBACK 启发式补 [C]/[J |

## 统计

- **severity**: {'P0': 40, 'P1': 7, 'P2': 3}
- **status**: {'shared_code_fixed': 48, 'case_private': 2}
- **applies_to_degree**: {'bachelor': 50, 'master': 43, 'doctor': 44, 'marxism': 11}

## 按 case 索引 (哪个 case 命中了哪些 D)

- **CASE-A**: D01, D02, D03, D04, D05, D06, D07, D08, D09, D10, D11, D12, D13, D14, D15, D16, D33, D43, D44, D45, D50
- **CASE-A**: D06, D10, D12, D17, D18, D19, D20, D21, D22, D23, D24, D25, D26, D27, D28, D29, D30, D31
- **CASE-A**: D23, D34, D35, D36, D37, D38
- **CASE-A**: D32, D40, D49
- **CASE-A**: D32, D39, D40
- **CASE-A**: D40, D41, D42
- **CASE-A**: D37, D46, D47, D48, D49
