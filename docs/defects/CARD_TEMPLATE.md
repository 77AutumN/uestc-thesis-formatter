---
id: D??                       # D01..D99, 全局唯一; 已 accept 的 candidate 升级为正式 D 时分配
title: <一句话症状, ≤60 字>     # 用 grep 友好的关键词
status: shared_code_fixed     # shared_code_fixed | case_private | pending | wontfix
severity: P0                  # P0=合规硬错 / P1=用户体验 / P2=优化
applies_to_degree: [bachelor, master, doctor, marxism]  # 可能踩本缺陷的学位类型
introduced_in: CASE-???       # 首次暴露此缺陷的 case
cases: [CASE-???, CASE-???]   # 命中本缺陷的所有 case (cross-case dashboard 自动统计来源)
triggers:                     # 触发条件列表; 每条要可机器化判定
  - <触发条件 1>
  - <触发条件 2>
detect_signature: |           # 一段, 描述如何机器识别 (preflight router 用)
  pandoc AST 含 X / docx XML 含 Y / generated .tex 含 Z
fix_location: scripts/foo.py:func()   # 修复落在哪个文件哪行/函数
test_coverage: tests/test_xxx.py      # 对应测试文件; 若无写 "TODO"
related_defects: []           # 关联的其他 D 缺陷 (optional)
---

# D?? — <短标题>

## 症状

<一段, 客户感知 / PDF 现象 / 流水线日志现象>

## 根因

<一段, 是哪个 step / script / 数据格式触发了问题>

## 修复

<一段, 改了哪些文件、引入了什么辅助、副作用是什么>

## 如何识别

bullet 列表, 给 preflight router / product_audit 用 — 越机器化越好:

- pandoc AST 中: ...
- docx XML 含: ...
- generated .tex 含: ...
- compiled PDF 含: ...
- main.log 含: ...

## 验证

<如何重现 + 如何确认已修>
