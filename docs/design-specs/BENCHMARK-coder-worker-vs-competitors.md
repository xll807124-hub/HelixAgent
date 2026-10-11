# BENCHMARK: Coder Worker 对标分析 vs. 竞品

**状态**: v1.0-benchmark | **完成度**: Stage 1.5 对标与借鉴决策 | **最后更新**: 2026-10-11

---

## 1. 对标产品与设计对比

我们对标了四类代码修复 / 代理产品，对比维度包括: **ReAct 循环设计、工具调用形式、PR 工作流、失败恢复、产品定位、对本项目的借鉴价值**。

### 1.1 Codex (OpenAI 内部)

**产品定位**: OpenAI 内部工具 + 开源社区 → Worker 级别的代码修复，强调 ReAct 循环与工具调用完整闭合。

| 维度 | 描述 |
|------|------|
| **ReAct 循环** | 完整闭合，每次迭代都保存状态；支持崩溃恢复 |
| **工具调用形式** | Structured 输出 (JSON/函数签名)，工具返回值回写到上下文 |
| **PR 工作流** | 无 — 只做修复和本地测试验证，不涉及 PR 流程 |
| **失败恢复** | Checkpoint + resume，支持长期持久任务 |
| **失败重试** | 在 ReAct Loop 内直接重试（如测试失败后继续改代码） |
| **验证闸门** | 隐式 — 通过测试自动确认修复完成 |

**我们的采用**:
- ✅ ReAct 循环结构（Observe → Reason → Act）
- ✅ 工具返回值包装成 `<<<TOOL_OUTPUT_START>>>...<<<TOOL_OUTPUT_END>>>` 回写历史
- ✅ Checkpoint + resume 机制
- ✅ Loop 内重试 + 多点验证闸门（比 Codex 显式）

**未采用的理由**:
- ❌ 单纯的隐式验证（依赖测试通过） → 我们加了显式闸门检查 (files_changed + tests_passed + committed)

---

### 1.2 Cursor Agent + Claude Code (Cursor IDE)

**产品定位**: IDE 内集成的编辑器级代理，强调快速 diff 预览、用户可中断、上下文局部化。

| 维度 | 描述 |
|------|------|
| **ReAct 循环** | 弱化循环 — 主要是单次 "思考 + 代码生成 + 展示"，支持用户中断 |
| **工具调用形式** | 代码块直接输出（不走工具系统），模型直接返回修改内容 |
| **PR 工作流** | 建议性 — 用户手动保存、commit、推送 |
| **失败恢复** | 无 — 每次对话独立，修改丢失需手动重新开始 |
| **失败重试** | 用户手动再问一遍；AI 无自主重试机制 |
| **验证闸门** | 无 — 用户看 diff，自己决定是否采纳 |

**我们的采用**:
- ✅ 工具级别的精细化控制（比 Cursor 更自动化）
- ✅ ReAct 循环的完整性（比 Cursor 的单次生成更强） 
- ✅ 自动化修复链闭合（Cursor 需要人工确认）

**未采用的理由**:
- ❌ 弱 ReAct — 不符合"完整自主修复"的目标
- ❌ 缺 Checkpoint — Cursor 没有长期恢复能力

---

### 1.3 Devin (Cognition)

**产品定位**: 商业 AI 工程师，强调端到端的 Issue → PR 完整自动化，包含任务拆解、搜索、代码理解。

| 维度 | 描述 |
|------|------|
| **ReAct 循环** | 超强 — 多层嵌套循环，支持平行搜索、代码审查循环、测试循环 |
| **工具调用形式** | 完整工具系统（文件、shell、git、浏览器），结果实时聚合 |
| **PR 工作流** | 完整 — 从 Issue 理解 → PR 创建 → 与评审者交互 |
| **失败恢复** | 强大 — 整个 session 可暂停、恢复、修改目标 |
| **失败重试** | 内置重试机制，支持全局回溯 |
| **验证闸门** | 多重 — 本地测试 + GitHub Actions 检查 + 评审 |

**我们的采用**:
- ✅ 完整 ReAct 循环架构（从 Devin 借鉴深度）
- ✅ 工具系统的完善性（Devin 的工具覆盖度启发）
- ✅ 多点验证（Devin 的分层验证思路）
- ✅ Checkpoint + 恢复（支持长期 session）

**未采用的理由**:
- ❌ PR 交互循环 — Stage 1.5 专注于本地修复，暂不处理 review 反馈
- ❌ 任务拆解层 — 这是 Stage 2 的内容
- ❌ 浏览器工具 — 本项目不支持外网

**采用但简化**:
- Devin 的多重验证闸门 → 我们只检查 (files/tests/commit)，未来可扩展

---

### 1.4 GitHub Copilot Workspace

**产品定位**: GitHub 集成的自适应工作空间，强调规划优先、分解任务、实时预览、降低人工介入。

| 维度 | 描述 |
|------|------|
| **ReAct 循环** | 规划主导 — 先生成任务分解计划，再逐个执行 |
| **工具调用形式** | 工作流 DSL，支持并行执行 |
| **PR 工作流** | 完全集成 — 规划 → 编码 → PR 自动生成 → 链接到 Issue |
| **失败恢复** | 中等 — Workspace 状态可保存，但缺少细粒度 checkpoint |
| **失败重试** | 支持，但需要重新规划 |
| **验证闸门** | 隐式 — 预览展示，用户最终确认 |

**我们的采用**:
- ✅ 规划优先的思路（未来 Stage 2 的任务拆解）
- ✅ 工作空间隔离（我们的 task_branch 概念）

**未采用的理由**:
- ❌ 规划 DSL — 本项目用自然语言 + ReAct，不额外引入 DSL
- ❌ 并行执行 — Stage 1.5 是单个 Worker，Stage 2 才支持多 Worker

---

## 2. 设计决策矩阵

| 特性 | Codex | Cursor | Devin | Copilot | **我们的选择** | **理由** |
|------|:----:|:-----:|:----:|:-------:|:----------:|---------|
| **ReAct 完整闭合** | ✅ | ❌ | ✅ | ⚠️ | ✅ 全闭合 | 支持长期任务与恢复 |
| **工具系统** | ✅ | ❌ | ✅ | ✅ | ✅ 完整 | 精细化控制 + 审批 |
| **Checkpoint 恢复** | ✅ | ❌ | ✅ | ⚠️ | ✅ 细粒度 | 崩溃恢复 + 持久执行 |
| **多点验证闸门** | ⚠️ | ❌ | ✅ | ⚠️ | ✅ 显式多点 | 质量保证 + 可审计 |
| **自动审批机制** | ❌ | ❌ | ❌ | ❌ | ✅ 新增 | 任务分支内自动化 |
| **PR 工作流** | ❌ | ❌ | ✅ | ✅ | ⏸️ 待 Stage 2 | 阶段分离 |
| **任务规划/拆解** | ❌ | ❌ | ✅ | ✅ | ⏸️ 待 Stage 2 | 阶段分离 |

**核心决策**:

1. **ReAct 循环**: 采用 Codex 的完整闭合模型 + Devin 的多层验证，确保"一次修复能到底"
2. **工具执行**: 采用完整工具系统（来自 Devin），但在 Policy Gateway 层加自动审批（创新点）
3. **验证闸门**: 升级 Codex 的隐式验证为显式多点检查，对标 Devin 的分层验证
4. **检查点恢复**: 采用 Codex + Devin 的 checkpoint 模式，支持长期 session
5. **自动审批**: **创新** — 在 allowed_paths + task_branch 限制下，auto-approve 高风险工具，避免人工审批瓶颈

---

## 3. 竞品优势 vs. 我们的补足

### 3.1 Devin 的强项与我们的差距

| Devin 优势 | 我们的现状 | 未来计划 |
|-----------|---------|---------|
| 完整 PR 工作流（从 Issue 到评审） | 只有本地修复 | Stage 2: PR 创建 + review 反馈循环 |
| 任务自动拆解 | 单个 Issue 单个 Worker | Stage 2: 任务规划与并行 Worker 调度 |
| 代码搜索 + 上下文感知 | Context Manager 还在建设中 | Stage 1.6 ~ 2: 混合检索 + 预加载 |
| 多层回溯 | 单向重试 + checkpoint | 未来可扩展：支持回溯到任意迭代 |

### 3.2 我们超越 Devin 的地方

| 我们的优势 | 实现方式 | Devin 是否支持 |
|----------|--------|-------------|
| 细粒度自动审批 | TaskBranchApprovalPolicy + auto-approve | ❓ 未知 |
| 精确的幂等键设计 | HEAD SHA + 工具参数 hash | ✅ 有但方案不同 |
| Checkpoint 设计 | 完整消息历史 + Action 回放 | ✅ 有但细节不清 |
| 工具隔离 + Policy 网关 | 三层（ToolRegistry → PolicyGateway → Tool） | ❓ 未知 |

---

## 4. 本项目的独特设计

### 4.1 自动审批网关（创新）

**问题**: 高风险工具（文件写、git commit）需要人工审批，会成为性能瓶颈

**竞品做法**:
- Codex: 信任 ReAct 循环本身，不做额外审批
- Cursor: 用户手动看 diff 决定
- Devin: 有审批机制但细节未公开

**我们的解决**:
```python
# TaskBranchApprovalPolicy
if repo_path in allowed_set and branch == task_branch:
    return APPROVE  # 自动通过，生成证据
else:
    return DENY     # 拦截不安全操作
```

**优势**:
- 不损失安全性（严格的分支 + 路径隔离）
- 避免人工审批延迟
- 自动生成审计证据

### 4.2 显式多点验证闸门

**问题**: 如何确保"修复"真的成功了？

**竞品做法**:
- Codex: 测试通过就算成功（隐式）
- Cursor: 用户看代码决定
- Devin: CI + 人工评审（多点，但需人）

**我们的解决**:
```python
class VerificationReport:
    files_changed: bool        # git diff 非空
    tests_passed_after_last_write: bool
    committed: bool            # HEAD 后移
```

**优势**:
- 防止"什么都没改就声称完成"
- 防止"提交忘了"
- 多角度保证质量

### 4.3 完整的消息历史 + Action 回放恢复

**设计**:
```python
@dataclass
class LoopCheckpoint:
    messages: list[ModelMessage]  # 完整对话历史
    actions: list[Action]         # 已执行 Action
```

**恢复时**:
- 不用重新调用 LLM
- 直接恢复消息历史，从下一迭代继续
- 完整的审计链

---

## 5. 未来扩展方向（与竞品对齐）

### 5.1 代理编排 (Agent Orchestration) — 对标 Devin 的任务拆解

**计划**: Stage 2 引入 `TaskPlannerAgent`
- 输入: Issue 描述
- 输出: 任务拆解计划 + 子任务分配
- 每个子任务由独立 CoderWorker 执行，并行或顺序

### 5.2 代码理解与上下文感知 — 对标 Devin 的搜索

**计划**: Stage 1.6 ~ 2 完善 `ContextManager`
- 混合检索：语义 + 语法 + 依赖关系
- 预加载相关代码片段
- 动态调整 token 预算

### 5.3 PR 工作流与评审反馈循环 — 对标 Devin 的完整工作流

**计划**: Stage 2 后期引入 `PRAgentWorker`
- 创建 PR（使用 git-push + GitHub API）
- 监听评审反馈
- 自动修复 review comments
- 回到 CoderWorker 继续迭代

### 5.4 多层回溯与全局搜索 — 对标 Devin 的强大恢复

**计划**: Stage 3 可选特性
- 支持回溯到任意历史迭代
- 并行探索多个修复方向
- 性能与成本平衡

---

## 6. 对标总结

| 产品 | 我们借鉴的 | 我们创新的 |
|------|----------|---------|
| **Codex** | ReAct 循环、Checkpoint 恢复 | 显式多点验证闸门 |
| **Cursor** | IDE 集成思路（暂不用） | 深化自动化程度 |
| **Devin** | 完整验证、工具系统、PR 工作流 | 细粒度自动审批 + 精确幂等键 |
| **Copilot Workspace** | 规划优先、工作区隔离 | 通过 task_branch 实现隔离 |

**阶段目标对齐**:

```
Stage 1.5 (现在)     — 单 Worker + ReAct 完整闭合 + 自动审批
  ↓
Stage 1.6 ~ 2        — 任务规划 + 多 Worker + PR 工作流
  ↓
Stage 2 ~ 3          — 代码理解深化 + 评审反馈循环 + 性能优化
```

---

## 7. 参考资料

- Codex 白皮书: https://arxiv.org/abs/2107.03374
- GitHub Copilot 官方文档: https://github.com/features/copilot
- Devin 产品演示: https://www.devin.ai
- 本项目设计: [REQ-WKR-001](./REQ-WKR-001-coder-worker-architecture.md)

---

**审批签名**: 对标分析 v1.0 | 设计团队 | 2026-10-11
