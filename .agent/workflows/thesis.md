---
description: 论文格式化工作协议
---

// turbo-all

# /thesis — 论文格式化工作协议

当用户说 `/thesis` 时，执行以下工作流。
**核心原则**：先恢复上下文 → 检查环境 → 判断模式 → 确认后执行 → 里程碑 commit。

> **🔒 强制规则（任何模型必须遵守，不得跳过）：**
> 1. **Step 1 是入场券**：必须 `view_file` 读完 `.agent/skills/thesis-formatter/SKILL.md` 全文后才能执行任何 pipeline 操作。不读 = 不干。
> 2. **Post-flight 是交付门**：Phase C 的 12 项检查必须逐项输出 ✅/⚠️/❌ 结果。不输出 = 不交付。
> 3. **NEVER 猜测修复**：编译失败时走 Pipeline Error Triage Tree（SKILL.md），不要凭经验猜。
> 4. **NEVER 说"已完成"却没验证**：每个 Step 必须有可观测的输出（截图/日志/数值），不接受纯文字"检查完毕"。
> 5. **编译失败必须结构化输出**：使用 `./templates/failure-report.md` 模板诊断。
> 6. **交付前必须 Definition of Done**：用户明确回复"确认交付"后才可执行文件拷贝。

---

## Step 0: 🧠 上下文重建

**目标**：搞清楚"上次干到哪了"。

1. 检查项目目录下的交接文档
2. 检查当前 conversation 的 artifacts（`task.md` / `implementation_plan.md`）
3. 兜底：扫描 conversation summaries 中含 "Thesis" 的最近会话
4. 输出一句话**进度摘要**

---

## Step 1: 🎒 技能装备

**始终加载**（不可跳过）：
- `.agent/skills/thesis-formatter/SKILL.md` — pipeline 架构与规则

**按需加载**：

| 任务性质 | 加载 |
|---------|------|
| 新论文处理 | 读取对应 profile: `./templates/<profile>/profile.json` |

---

## Step 2: 🔍 环境检查

### 2.1 Git 状态
```bash
git status --short
git log --oneline -3
```

### 2.2 工具链检查（首次/报错时）
```bash
pandoc --version     # 需要 3.9+
python --version     # 需要 3.10+
docker info          # Docker Desktop
```

---

## Step 3: 🔀 模式判断

### 🛠️ 开发模式（Dev Mode）
**触发词**：P0, Phase, AST, 重构, 迁移, 改代码, 新功能, bug, 修复脚本
→ 在 `feature/*` 分支上工作，遵循增量迭代

### 📦 生产模式（Process Mode）
**触发词**：同学, 论文, 处理, 调格式, 交付, 帮忙
→ 在 `master` 分支上运行（不改代码），进入下方 SOP

**如果判断不了** → 直接问用户

---

## Step 4: 📋 汇报 & 执行

向用户输出简洁汇报后等待确认。

---

## 论文处理 SOP（生产模式）

### Phase A: 接收
1. 确认 .docx 文件路径
2. 确认 profile（马克思主义学院 → `uestc-marxism`，其他 → `uestc`）
3. 确认参考标准 PDF（如有）

### Phase A.5: Pre-flight 预检 — ⚡ INTERVIEW MODE（不可跳过）

> 🔒 **你现在是面试官，不是执行者。**
> 逐项向用户提问，等用户回答后再问下一个。
> **严禁自己替用户回答**。
> 6/6 问题回答完毕前 → REFUSE to proceed to Phase B。

```
INTERVIEW QUESTIONS:
Q1: 学院是什么？(马院/理工/经管/其他)
Q2: 学位类型？(学士/硕士/专硕/博士/工程博士)
Q3: 论文大约几章？（含绪论和总结）
Q4: 有公式/图表吗？大约多少？
Q5: 参考文献大约多少条？
Q6: 有参考标准 PDF 吗？
```

**门控判定：**
- 6/6 已回答 + 假设已确认 → ✅ 进入 Phase B
- 有未回答的问题 → 🛑 继续提问

### Phase B: 运行
```bash
python ./scripts/run_v2.py "<thesis.docx>" --profile <profile> --auto
```

### Phase B.5: 编译失败裁决（仅在 Phase B 失败时触发）
1. 加载 `./templates/failure-report.md` 模板
2. 填充所有 `{{}}` 占位符
3. 输出结构化诊断报告
4. 按 SKILL.md Phase 5.5 裁决表决定回滚

### Phase C: Post-flight 质量验证

#### 🔴 CRITICAL（5 项）— 任一失败 = 禁止交付

| # | 检查项 | 验证方式 |
|---|--------|----------|
| C1 | 封面元数据完整 | 学号/姓名/导师不得为默认值 |
| C2 | 摘要区干净 | 不混入封面文本或 Word 目录条目 |
| C3 | 学位类型正确 | 与 Word 源文档一致 |
| C4 | 章节切分完整 | 与 Pre-flight Q3 用户回答一致 |
| C5 | 电子版无空白页 | PDF 中不得出现空白页面 |

#### 🟡 WARN（4 项）— 记录但可交付

| # | 检查项 |
|---|--------|
| W1 | 目录页链接正确（非 `??`） |
| W2 | 页眉规范 |
| W3 | 摘要长度 |
| W4 | 参考文献格式 |

#### 判定规则
- 0 CRITICAL 失败 → 🟢 可交付
- ≥1 CRITICAL 失败 → 🔴 禁止交付

#### 输出格式（不可省略）
```
POST-FLIGHT REPORT:
[CRITICAL]
 C1 封面元数据 ........... ✅/❌ (证据)
 C2 摘要区 ............... ✅/❌ (证据)
 C3 学位类型 ............. ✅/❌ (证据)
 C4 章节切分 ............. ✅/❌ (证据)
 C5 无空白页 ............. ✅/❌ (证据)
[WARN]
 W1-W4 ...
VERDICT: 🟢 PASS / 🔴 FAIL
```

### Phase C.5: Definition of Done
```
📦 交付摘要:
- PDF 总页数 / 章节数 / 参考文献条数
- Post-flight 结果
- 已知遗留

请回复 "确认交付" 以执行最终拷贝。
```

### Phase D: 交付
```bash
git add -A && git commit -m "feat: process thesis"
```

---

## 故障排查

| 症状 | 处理 |
|------|------|
| Extract 失败 | 检查 DOCX 格式，WPS 兼容性差 |
| Compile 失败 | 查 build.log，搜索 `! ` 行 |
| 章节检测不全 | Word 标题未用 Heading 样式 |
| PDF 不更新 | **关闭 PDF 阅读器** |

---

## 快捷方式

- 同一对话内重复 `/thesis` → 跳过 Step 0
- 简单修复 → 压缩 Step 0-2，直接执行
- `/thesis process` → 直接进 SOP
