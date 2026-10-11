# REQ-WKR-001: Coder Worker 架构、接口与闸门机制

**状态**: v1.0-implemented | **优先级**: P0 | **完成度**: Stage 1.5 | **最后更新**: 2026-10-11

---

## 1. 概述

**Coder Worker** 是一个与 LLM 模型协作修复代码 bug 的工作单元。它通过 ReAct 循环（Observe → Reason → Act）让模型逐步读取、分析、修复代码，并在任务完成时通过多点验证闸门确保修复质量。

核心特性:
- **ReAct Loop 完整闭合**: 模型与工具交互，每次迭代都保存检查点，支持崩溃恢复。
- **Task Branch 隔离**: 所有改动都在专用任务分支上，不触及主分支或其他代码。
- **自动审批网关**: 文件写入、代码提交等高风险操作在任务分支内自动通过，无需外部审批。
- **多点验证闸门**: 完成声明时检查是否真的修复了问题（代码改变、测试通过、提交完成）。

---

## 2. 核心职责与数据流

### 2.1 输入: `CoderTaskSpec`

```python
@dataclass
class CoderTaskSpec:
    # 任务身份
    task_id: str
    workflow_id: str
    worker_id: str
    trace_id: str
    
    # 问题描述
    issue_title: str
    issue_description: str
    
    # Git 仓库与分支
    repo_path: str
    task_branch: str
    base_branch: str = "main"
    
    # 安全沙箱
    test_path: str
    allowed_paths: list[str]  # 模型只能改这些路径
    
    # 运行控制
    max_iterations: int = 12
    checkpoint_dir: str | None = None
```

### 2.2 输出: `CoderResult`

```python
@dataclass
class CoderResult:
    success: bool
    error_message: str | None = None
    
    # 完成状态
    commit_sha: str | None = None
    changed_files: list[str] = field(default_factory=list)
    
    # 验证报告
    verification: VerificationReport | None = None
```

### 2.3 验证报告: `VerificationReport`

```python
@dataclass
class VerificationReport:
    passed: bool
    
    # 各项检查结果
    files_changed: bool
    tests_passed_after_last_write: bool
    committed: bool
    
    # 诊断信息
    summary: str
    test_output: str = ""
```

---

## 3. ReAct Loop 核心流程

### 3.1 单次迭代步骤

每个迭代遵循严格的 Observe → Reason → Act 顺序:

#### Step 1: Observe (`_observe()`)
- 读取当前 git 状态（工作区、暂存区、最新提交）
- 读取上一次迭代的工具输出（如果有）
- 如有检查点，加载已执行 Action 历史

#### Step 2: Reason (`_reason()`)
- 组装系统提示词（包含工具规范、上下文、任务描述）
- 把观察结果和历史 Action 打包成用户消息
- 调用 LLM 模型，获得下一步思考与工具调用

#### Step 3: Act (`_act()`)
- 将 LLM 的 `ToolCall` 转换为 `Action` 实体（含 UUID、HEAD commit SHA、幂等键）
- 通过 `ActionExecutor` 执行工具调用，经过 Policy Gateway 拦截和审批
- 将结果包装成 `<<<TOOL_OUTPUT_START>>>...<<<TOOL_OUTPUT_END>>>` 格式，放回模型消息历史
- 保存检查点（包含本次 Action 的完整执行结果）

### 3.2 终止条件

当模型返回 `final_summary` 时进入完成路径:

```python
if model_response.final_summary:
    result = await self._verify()  # 多点验证闸门
    if result.verification.passed:
        return CoderResult(success=True, verification=result.verification)
    else:
        # 闸门拒绝，继续循环
        result = continue_loop()
```

当达到 `max_iterations` 时失败。

---

## 4. 验证闸门 (`_verify()`)

多点验证确保修复真实有效:

| 检查项 | 规则 | 失败行为 |
|--------|------|---------|
| **Files Changed** | `git diff HEAD --name-only` 非空 | 没改任何代码 → 拒绝 |
| **Tests Passed** | 运行 `pytest` 在 `test_path` 成功 | 测试失败 → 拒绝 |
| **Committed** | HEAD commit 时间戳晚于任务启动时间 | 没有提交改动 → 拒绝 |

**闸门拒绝行为**:
- 返回 `verification.passed = False`
- 模型收到失败反馈，继续循环（重新尝试最多 `max_iterations - current` 次）
- 若超过最大迭代次数，任务失败

---

## 5. 自动审批网关

### 5.1 高风险工具的自动通过条件

以下工具在满足条件时自动通过审批（生成 `APPROVAL_GRANTED` 证据），无需外部干预:

| 工具 | 自动通过条件 |
|------|------------|
| `file-write` | `path` 在 `allowed_paths` 内，写入在 `task_branch` 上 |
| `git-commit` | `repo_path` 匹配，分支是 `task_branch` |
| `git-push` | 推送目标是 `task_branch` |
| `safe-shell` | 工作目录在 `repo_path` 内，分支是 `task_branch` |

### 5.2 网关架构

```
LLM ToolCall 
    ↓
ActionBuilder: ToolCall → Action (幂等键、HEAD SHA)
    ↓
ActionExecutor.execute_action()
    ↓
ApprovalAwarePolicyGateway 
    ├─ TaskBranchApprovalPolicy 检查 (repo_path, task_branch, allowed_paths)
    ├─ 若通过 → 生成 APPROVAL_GRANTED 证据
    └─ 若拒绝 → 返回 DENIED 证据
    ↓
ToolRegistry.execute() / Tool.execute()
    ↓
工具执行结果
```

### 5.3 拦截场景

**拒绝场景**:
1. 写入路径不在 `allowed_paths` 内 → 文件写入被拒
2. 操作分支非 `task_branch` → git 操作被拒
3. 提交信息包含敏感关键词（如 `token=...`）→ 被拒，返回清理版错误信息

**每次拒绝后**:
- 模型收到清理后的错误消息
- 循环继续，模型可重试（如修改路径或改写提交信息）

---

## 6. 检查点与恢复

### 6.1 检查点内容

```python
@dataclass
class LoopCheckpoint:
    task_id: str
    iteration: int
    
    # 模型会话状态
    messages: list[ModelMessage]
    
    # 已执行 Action 历史
    actions: list[Action]
    
    # 最后一次工具调用的结果
    last_tool_result: str | None
    
    # Git 状态快照
    head_commit_sha: str
    last_write_iteration: int
```

### 6.2 保存时机

- **正常迭代**: 每个 Act 步骤后保存检查点（Action 执行完成后）
- **异常中断**: 模型崩溃、网络超时、工具失败 → 检查点已保存，恢复时直接从上一迭代继续

### 6.3 恢复流程 (`resume()`)

```python
async def resume() -> CoderResult:
    checkpoint = checkpoint_store.load(task_id)
    if not checkpoint:
        return CoderResult(success=False, error_message="找不到检查点")
    
    # 重新初始化 worker
    worker.messages = checkpoint.messages
    worker.actions = checkpoint.actions
    worker.current_iteration = checkpoint.iteration
    
    # 从下一迭代继续
    return await worker.run()
```

---

## 7. 工具规范与输入正规化

### 7.1 统一接口约定

所有工具通过标准化的 `ToolCall` 接口调用:

```python
@dataclass
class ToolCall:
    name: str                    # 工具唯一标识符
    arguments: dict[str, object] # 工具参数（dict，非 JSON）
```

### 7.2 参数正规化

模型可能使用不同的参数名，系统自动适配:

| 工具 | 模型常用名 | 标准名 | 转换规则 |
|------|----------|--------|---------|
| `file-read` | `file_path`, `filepath`, `path` | `path` | 取别名第一个匹配项 |
| `file-write` | `file_path`, `filepath`, `path` | `path` | 取别名第一个匹配项 |
| `pytest-run` | `test_path`, `test_dir`, `tests` | `test_path` | 取别名第一个匹配项 |

当参数缺失或格式错误时:
- 返回友好的错误提示给模型
- 模型下一次迭代时修正参数
- 不影响已保存的检查点

---

## 8. 错误分类与恢复策略

### 8.1 可恢复错误（循环继续）

| 错误类型 | 来源 | 处理 |
|---------|------|------|
| 参数格式错误 | 工具验证 | 返回错误提示，下一迭代重试 |
| 文件不存在 | 文件读写 | 返回 File Not Found，提示路径 |
| 审批拒绝 (path out of bounds) | Policy Gateway | 返回 DENIED，提示约束条件 |
| 测试失败 | pytest runner | 返回测试失败输出，模型继续改进 |
| 权限拒绝 (git branch mismatch) | git 工具 | 返回错误，模型处理 |

### 8.2 不可恢复错误（任务失败）

| 错误类型 | 来源 | 行为 |
|---------|------|------|
| 超过 max_iterations | ReAct Loop | 返回 `success=False` |
| 模型内部异常 | ModelClient | 返回 `success=False, error=...` |
| 验证闸门多次拒绝 | `_verify()` | 返回 `success=False, verification.passed=False` |
| 检查点损坏 | 恢复流程 | 返回 `success=False, error="Checkpoint corruption"` |

---

## 9. 实现清单与验证

### 9.1 已实现组件

- ✅ `CoderWorker` 主循环 (run/resume)
- ✅ `_observe()` — git 状态读取
- ✅ `_reason()` — 系统提示词组装 + 模型调用
- ✅ `_act()` — ToolCall → Action 转换 + 执行 + 检查点保存
- ✅ `_verify()` — 多点验证闸门 (files/tests/commit)
- ✅ `ActionBuilder` — 幂等键计算、HEAD SHA 获取、Action 实体构造
- ✅ `TaskBranchApprovalPolicy` — repo/branch/path 验证
- ✅ `ApprovalAwarePolicyGateway` — auto-approve + DENIED 拦截
- ✅ `MemoryLoopCheckpointStore` 与 `JsonFileLoopCheckpointStore` — 检查点保存与恢复
- ✅ `MockModelClient` — 可配置预设剧本的模型测试桩

### 9.2 端到端测试覆盖

| 用例 | 测试文件 | 状态 |
|------|---------|------|
| 正常修复路径 (读→改→测→提→完成) | `test_coder_e2e.py::test_happy_path_fixes_bug_and_commits` | ✅ PASS |
| 过早完成被拒，闸门连续拒绝 | `test_coder_e2e.py::test_gate_rejects_premature_completion` | ✅ PASS |
| 模型崩溃后恢复 | `test_coder_e2e.py::test_resume_after_model_crash` | ✅ PASS |
| 无检查点恢复失败 | `test_coder_e2e.py::test_resume_without_checkpoint_fails` | ✅ PASS |
| 越界写入被审批拒绝 | `test_coder_e2e.py::test_write_outside_allowed_paths_is_denied` | ✅ PASS |
| 测试失败时闸门不放行 | `test_coder_e2e.py::test_failing_tests_block_completion` | ✅ PASS |

**测试覆盖**:
- 6 个 E2E 测试用例，每个用例都使用真实 git 仓库 + 真实工具 + 预设模型剧本
- 31 个单元测试（approval/action_builder/prompts/checkpoint_store 模块）
- 0 ruff 代码风格错误，0 mypy 类型错误
- 全项目 pytest 通过: **1302 passed, 10 skipped**

---

## 10. 系统提示词与工具规范

### 10.1 系统提示词结构

```
你是一个代码修复专家。

## 任务
修复一个 bug：[issue_title]

描述：[issue_description]

## 工具约束
- 只能改写 [allowed_paths 列表]
- 所有改动在 [task_branch] 分支上
- 测试路径：[test_path]

## 可用工具
1. file-read(path: str) → 文件内容
2. file-write(path: str, content: str) → 写成功/权限拒绝
3. pytest-run(test_path: str) → 测试结果
4. git-commit(repo_path: str, message: str, all: bool) → commit SHA/错误
5. ...

## 工作流
1. 读文件，理解代码
2. 修改代码，提交
3. 运行测试验证
4. 完成时返回 final_summary: "已修复: ..."
```

### 10.2 工具规范 (`TOOL_SPECS`)

每个工具包含:
- **描述** — 作用与参数
- **参数类型** — JSON schema
- **限制** — path allowed_paths/branch check/等
- **返回值** — 成功/失败格式

---

## 11. 与其他组件的边界

### 11.1 依赖关系

```
CoderWorker
├─ ActionExecutor (工具执行)
├─ ModelClient (LLM 通信)
├─ LoopCheckpointStore (恢复)
├─ ApprovalAwarePolicyGateway (审批)
│  └─ TaskBranchApprovalPolicy (决策)
├─ ToolRegistry (工具注册表)
└─ GitOperations (git 原语)
```

### 11.2 外部约束

- **Git 仓库约束**: 任务分支必须存在、base_branch 必须存在
- **工具约束**: 所有工具必须支持 ToolCall 接口
- **模型约束**: ModelClient 必须返回标准 ModelResponse（tool_call 或 final_summary）
- **权限约束**: 执行 git 操作需要 write 权限；Policy Gateway 需要精确的 allowed_paths 列表

---

## 12. 扩展点与未来方向

### 12.1 可配置参数

- `max_iterations` — 每个任务最多尝试次数
- `checkpoint_dir` — 检查点存储路径
- `allowed_paths` — 每个任务的独立路径白名单
- `base_branch` — 回归基线分支（默认 main）

### 12.2 计划中的增强

1. **代理模式**: 支持多个 Worker 并行处理多个 bug
2. **上下文感知**: 从 Context Manager 获取相关代码片段，冷启动优化
3. **代理生成**: 基于 bug 类型智能选择工具集和提示词
4. **反馈学习**: 收集验证失败案例，自动优化提示词

---

## 13. 参考文献

- [RT-001: 核心实体 Schema](./REQ-RT-001-core-runtime-entities.md)
- [RT-005: Checkpoint Protocol](./REQ-RT-005-checkpoint-protocol.md)
- [SEC-004: 沙箱隔离基线](./REQ-SEC-004-sandbox-isolation-baseline.md)
- [验证闸门设计](./REQ-RT-004-state-projections.md)
- 实现: `src/workers/coder/`

---

**审批签名**: Stage 1.5 完成 | 实现方 | 2026-10-11
