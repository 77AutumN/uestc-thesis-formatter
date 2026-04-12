# ❌ Pipeline 失败报告

## 🛑 阻塞阶段: {{CURRENT_PHASE}}

| 字段 | 值 |
|------|-----|
| **错误类型** | {{ERROR_TYPE}} |
| **触发条件** | {{TRIGGER}} |
| **当前重试次数** | {{RETRY_COUNT}} / 3 |

## 📋 底层日志片段
```
{{LOG_SNIPPET}}
```

## 🔍 根因分析
{{ROOT_CAUSE}}

## ⤴️ 回滚判定
| 错误类别 | 建议动作 |
|---------|---------|
| Font/Package (环境类) | 保持当前 Phase，修复环境后重试 |
| Section/Chapter 结构错误 | **ROLLBACK → Phase 3** (重新确认章节结构) |
| Citation/Reference 格式错误 | **ROLLBACK → Phase 4 Step 14** (重新生成引用) |
| Overfull/Underfull 排版警告 | 记录但不阻塞，在 Phase 6 视觉验收时处理 |

## 💡 建议修复
{{SUGGESTED_FIX}}

---
> 此报告由 thesis-formatter Pipeline 自动生成。Agent 必须填充 {{}} 占位符后输出，严禁输出空模板。
