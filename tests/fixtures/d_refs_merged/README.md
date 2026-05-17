# d_refs_merged — Refs Segment Merged Guard Fixture

## 触发

CASE-A round 1: 客户 docx 用自定义段落样式 (`参考文献`) 标 26 段, 每段一条 `[N]` 参考文献. pandoc 把多段同 custom-style 合并成单 `Para` block (~3003 字), `refs_to_bib` 解析只看到 1 条 → cite_map 1 条 → 章节 `[N]` 替换 25 处缺失.

修复: 在 `pandoc_ast_extract.py` 写 `references_raw.txt` 之前加防御性拆行 guard — 若 references_raw 单行多 `[N]`, 按 `[N]` 拆行.

## 两层 fixture

### Path A — docx 集成 fixture (`generate_min_docx.py`)

生成 5 段同 custom-style refs 的最小 docx, 验证 pandoc + extractor 输出 ≥ 5 行.

**当前 pandoc 3.9 行为**: 5 段 custom-style 被正常拆为 5 条 (不复现 CASE-A 病理). Path A 是**未来回归保险** — 若 pandoc 升级回退合并行为, 此 fixture 立即捕获.

CASE-A 病理的精确触发条件比"5 段同 custom style"更窄 (可能与 style 性质 / pandoc 内部启发式相关). 我们用 Path B 覆盖核心 guard 逻辑.

### Path B — references_raw.txt 单元 fixture (`merged_input.txt`)

直接给一个**已经合并成单行**的 references_raw.txt 模拟病理输入, 验证 shared guard 拆行正确性. 不依赖 pandoc 是否复现.

## 反向不变量 (`expected_invariant.json`)

| 不变量 | 阈值 | 说明 |
|---|---|---|
| `refs_raw_line_count_min` | ≥ 5 | docx → references_raw.txt 后行数 ≥ 5 (Path A) |
| `no_single_para_with_3_plus_n_markers` | true | 任何 Para block 单行不能含 ≥ 3 个 `[N]` |
| `merged_input_split_count_min` | ≥ 5 | guard 处理 merged_input.txt 后输出 ≥ 5 行 (Path B) |

## 扩展 (后续 fixture 复用此模板)

后续 D 卡 fixture 推荐复用本目录:
- D23 refs_to_bib J/OL 变体 → `tests/fixtures/d_refs_jol/`
- D12 refs_to_bib no_author_title_only → `tests/fixtures/d_refs_no_author/`
- D49 docx_surgery plan/apply → `tests/fixtures/d_docx_surgery/`

## 起源

- 起草: Codex GPT-5.4 (high effort), 2026-05-16, 写入 `docs/w5_refs_merged_guard_report_2026-05-16.md`
- Codex sandbox 写权限受限 (`.agents` 是 junction), 由 Claude Code 落地 fixture + 实施 shared guard
