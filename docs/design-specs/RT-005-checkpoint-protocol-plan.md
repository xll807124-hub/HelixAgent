# RT-005 Checkpoint Protocol — 实施计划设计

> **状态**: 📋 **待复阅**（设计完成，等待您确认后再进入实施阶段）  
> **任务编号**: RT-005  
> **任务名称**: Checkpoint Protocol 设计与 MVP 实施  
> **关联需求**: `docs/design-specs/REQ-RT-005-checkpoint-protocol.md`（v0.1-frozen）  
> **前置依赖**:  
> - ✅ REQ-RT-001（实体类型与状态枚举）  
> - ✅ REQ-RT-002（状态机与迁移规则）  
> - ✅ REQ-RT-003（事件 envelope 与 EventStore）  
> - ✅ REQ-RT-004（投影、检查点、Rebuilder）  
> **本计划范围**: 第一轮 MVP——Checkpoint 数据模型 + 保存路径 + `RUNNING` / `PAUSE` 两个保存原因  
> **完成日期**: 待定  

---

## 1. 任务背景与范围声明

### 1.1 背景

REQ-RT-005 定义了一个**范围大、责任重**的协议：Workflow 可恢复点协议，包含 Checkpoint Schema、保存策略、恢复协议、Action 副作用边界、与 8 个其他 REQ 模块的接口交叉引用（共约 420 行规范）。

一次完整实现覆盖所有 §3-§10 内容会占用多轮交付。本轮（RT-005-MVP）**只交付 MVP**，把 §4-§5 的一张核心骨架搭起来，把数据模型 + 保存路径 + 2 个保存原因做完。其余（APPROVAL/RECOVERY/HISTORY_BOUNDARY、恢复协议、Action 副作用边界）放到后续迭代轮。

### 1.2 MVP 范围（IN-SCOPE）

✅ **包含（本轮必交付）**：

1. **数据模型（§4.1）**：WorkflowCheckpoint / StateSnapshot / WorkerCheckpointRef / ActionCheckpointRef / BudgetSnapshot / ResourceSnapshot 的 Python 映射
2. **保存路径（§5）**：从事件事实 → 构建 Checkpoint → 校验哈希 → 写入存储 → CheckpointCreated 事件追加入 EventStore
3. **2 个保存原因**：RUNNING（自动，事件边界触发） / PAUSE（用户操作触发）
4. **存储层抽象**：CheckpointRepository（异步 / 同步双接口），in-memory 实现（先用于单测；PostgreSQL 实现放到 RT-005-P2）
5. **基础单元测试** + **集成测试**（与 EventStore 协作的端到端流程）

### 1.3 OUT-OF-SCOPE（本轮**不做**，留给后续轮）

❌ **RECOVERY / APPROVAL / HISTORY_BOUNDARY 保存原因**（放到 RT-005-P2）  
❌ **恢复协议（§6）**：权限校验、Schema 兼容性校验、事件回放、Action 副作用重新评估（本轮只交付数据模型，恢复协议放到 RT-005-P2）  
❌ **Action 副作用边界（§7）**：与 REQ-RT-007 一起设计（避免双重还原 REQ-RT-007）  
❌ **PostgreSQL 持久化层**：待 REQ-RT-005-P2 或 RT-005-P3  
❌ **跨版本迁移（§9 第 4-7 项）**：SCHEMA_VERSION 不兼容迁移  
❌ **失败事件处理（§10）**：写入失败、哈希校验失败、源事件缺失（放到 P3）  

### 1.4 与其他模块的依赖声明

| 依赖 | 路径 | 状态 |
|------|------|------|
| EventStore | `src/runtime/events/store.py` | ✅ 已实现（REQ-RT-003） |
| TaskStatus / WorkflowStatus / WorkerStatus / ActionStatus | `src/runtime/entities/` | ✅ 已实现（REQ-RT-001） |
| TaskProjection / WorkflowProjection | `src/runtime/projection/models.py` | ✅ 已实现（REQ-RT-004） |
| EventEnvelope | `src/runtime/events/envelope.py` | ✅ 已实现（REQ-RT-003） |
| Action 副作用模型 | REQ-RT-007（尚未冻结） | ⏳ 待冻结 |

---

## 2. 数据模型设计（§4 → Python 映射）

### 2.1 类层次概览

```text
WorkflowCheckpoint (Top-level 业务恢复点)
├── schema_version: str = "runtime.workflow-checkpoint.v1"        # 兼容 §10 字段不可变约束
├── runtime_contract_version: str                                  # 与 RT-005 §4.1 对齐
├── checkpoint_id: CheckpointId                                    # 业务唯一 ID
├── task_id / workflow_id / org_id / project_id / repo_id
├── created_at / created_by
├── checkpoint_reason: CheckpointReason (RUNNING/PAUSE 本轮; 其它 3 种占位)
├── checkpoint_status: CheckpointStatus (CREATED/VERIFIED/INVALID/SUPERSEDED)
├── source_event_sequence / source_event_id / source_event_hash
├── event_stream_partition: str = "workflow:{workflow_id}"
├── checkpoint_hash: str                                          # SHA-256 over content
├── content_hash: str                                             # hash of state snapshot
├── workflow_template_*: Agent_*/Toolset_* etc. (§4.1 约束字段，不可变)
└── content: WorkflowCheckpointContent
    ├── StateSnapshot
    ├── list[WorkerCheckpointRef]
    ├── list[BudgetSnapshot]                                       # 1 per active worker
    ├── ResourceSnapshot
    └── ...
```

### 2.2 关键约束（从 REQ-RT-005 §9 推导）

| 字段 | 约束 | 实现位置 |
|------|------|---------|
| `schema_version` | 写后不可变，仅新版本迁移可改 | `SchemaVersionGuard.readonly_after_write()` |
| `runtime_contract_version` | 写后不可变 | 同上 |
| 6 个版本字段 | 同上 | 同上 |
| `credential_refs` | **只存不解析的引用**，不能存凭据值 | Pydantic 字段类型仅 `CredentialRef`，无 `value` |
| 凭据内容 | 禁止出现在 Checkpoint | 通过 lint/规则显式禁止（详见 §6.3） |

### 2.3 Python 类签名草案

```python
from datetime import datetime
from enum import Enum
from typing import Optional, Any
from uuid import UUID
from pydantic import BaseModel, Field, computed_field

# ============ Enums (来自 REQ §5.1, §4.1) ============
class CheckpointReason(str, Enum):
    """保存原因（§5.1）"""
    RUNNING = "RUNNING"            # ✅ 本轮实现
    PAUSE = "PAUSE"                # ✅ 本轮实现
    APPROVAL = "APPROVAL"          # ⚠️ 占位，未实现
    RECOVERY = "RECOVERY"          # ⚠️ 占位，未实现
    HISTORY_BOUNDARY = "HISTORY_BOUNDARY"  # ⚠️ 占位，未实现

class CheckpointStatus(str, Enum):
    """Checkpoint 状态机（§4.1）"""
    CREATED = "CREATED"            # 刚写入；后续校验哈希
    VERIFIED = "VERIFIED"          # 哈希校验通过
    INVALID = "INVALID"            # 哈希或 Schema 校验失败（§10 行）
    SUPERSEDED = "SUPERSEDED"      # 被更新的 Checkpoint 取代

# ============ Checkpoint 内容（§4.2 - §4.5）============
class StateSnapshot(BaseModel):
    """§4.2 状态快照"""
    task_status: str                  # TaskStatus enum value
    workflow_status: str              # WorkflowStatus enum value
    current_step_id: Optional[str] = None
    runnable_step_ids: list[str] = Field(default_factory=list)
    waiting_step_ids: list[str] = Field(default_factory=list)
    completed_step_ids: list[str] = Field(default_factory=list)
    failed_step_ids: list[str] = Field(default_factory=list)
    active_worker_refs: list["WorkerCheckpointRef"] = Field(default_factory=list)
    completed_worker_refs: list["WorkerCheckpointRef"] = Field(default_factory=list)
    pending_approval_refs: list[Any] = Field(default_factory=list)  # ApprovalRef 来自 RT-002
    unresolved_failure_refs: list[Any] = Field(default_factory=list)
    required_artifact_refs: list[str] = Field(default_factory=list)
    required_evidence_refs: list[str] = Field(default_factory=list)
    base_revision: str
    working_revision: Optional[str] = None
    workspace_ref: Optional[str] = None

class WorkerCheckpointRef(BaseModel):
    """§4.3 Worker 恢复引用"""
    worker_id: str
    step_id: str
    worker_type: str
    attempt: int = Field(ge=1)
    status: str  # WorkerStatus
    source_revision: str
    last_applied_event_sequence: int = Field(ge=0)
    last_completed_action_id: Optional[str] = None
    pending_action_refs: list["ActionCheckpointRef"] = Field(default_factory=list)
    input_artifact_ids: list[str] = Field(default_factory=list)
    output_artifact_ids: list[str] = Field(default_factory=list)
    context_manifest_ref: Optional[str] = None
    worker_state_ref: Optional[str] = None

class ActionCheckpointRef(BaseModel):
    """§4.4 Action 恢复引用"""
    action_id: str
    worker_id: str
    attempt: int = Field(ge=1)
    action_type: str
    tool_name: str
    tool_schema_version: str
    target_resource_hash: str
    source_revision: str
    action_status: str  # ActionStatus
    policy_decision_id: Optional[str] = None
    idempotency_key_ref: Optional[str] = None
    observation_artifact_id: Optional[str] = None
    # side_effect_state 来自 RT-007；本轮字段预留下游，但不构造
    # recovery_action 同上

class BudgetSnapshot(BaseModel):
    """§4.5 预算快照"""
    max_input_tokens: int = Field(ge=0)
    max_output_tokens: int = Field(ge=0)
    max_total_tokens: int = Field(ge=0)
    max_cost_microusd: int = Field(ge=0)
    max_duration_seconds: int = Field(ge=0)
    max_tool_calls: int = Field(ge=0)
    consumed_input_tokens: int = Field(ge=0)
    consumed_output_tokens: int = Field(ge=0)
    consumed_total_tokens: int = Field(ge=0)
    consumed_cost_microusd: int = Field(ge=0)
    elapsed_duration_seconds: int = Field(ge=0)
    completed_tool_calls: int = Field(ge=0)

class ResourceSnapshot(BaseModel):
    """§4.5 资源快照"""
    workspace_id: str
    workspace_image_version: str
    workspace_state_hash: str
    base_revision: str
    working_revision: Optional[str] = None
    branch_ref: Optional[str] = None
    uncommitted_change_manifest_ref: Optional[str] = None
    generated_artifact_refs: list[str] = Field(default_factory=list)
    temporary_resource_refs: list[str] = Field(default_factory=list)

class WorkflowCheckpointContent(BaseModel):
    """§4 中 4.2-4.5 的容器"""
    state: StateSnapshot
    worker_refs: list[WorkerCheckpointRef] = Field(default_factory=list)
    budgets: list[BudgetSnapshot] = Field(default_factory=list)
    resources: Optional[ResourceSnapshot] = None

# ============ Top-level WorkflowCheckpoint ============
class WorkflowCheckpoint(BaseModel):
    """§4.1 顶层 Checkpoint 容器"""
    schema_version: str = Field(default="runtime.workflow-checkpoint.v1", frozen=True)
    runtime_contract_version: str = Field(default="v1", frozen=True)
    checkpoint_id: str
    task_id: str
    workflow_id: str
    organization_id: str
    project_id: str
    repository_id: str
    created_at: datetime
    created_by: str       # ActorRef（简化本轮用 str）
    checkpoint_reason: CheckpointReason
    checkpoint_status: CheckpointStatus = Field(default=CheckpointStatus.CREATED)
    source_event_sequence: int = Field(ge=0)
    source_event_id: str
    source_event_hash: str
    event_stream_partition: str = "workflow:{workflow_id}"  # 由代码生成
    checkpoint_hash: str = ""      # 写入前计算
    content_hash: str = ""         # 写入前计算
    workflow_template_id: str
    workflow_template_version: str
    agent_profile_version: str
    toolset_version: str
    content: WorkflowCheckpointContent
    
    # 写后不可变字段——Pydantic model_config + 显式校验
    model_config = {"frozen": False}  # 允许 status/hash 在写入前更新
```

### 2.4 与 REQ §9 安全约束的实现映射

**禁止凭据值进入 Checkpoint** 的实现：

```python
# 任何包含 "password", "secret", "token", "api_key" 等的字段将抛错
SENSITIVE_FIELD_PATTERNS = ("password", "secret", "token", "api_key", "private_key")

def _check_no_plaintext_credentials(content: WorkflowCheckpointContent):
    """迭代 content 字段，禁止名称含敏感词的字符串值"""
    # 实现：在 pydantic 序列化后 JSON dump 文本搜索敏感模式
    # （pydantic 不会阻拦，但构造 WorkflowCheckpoint 时主动校验）
    ...
```

**版本字段不可变**：

```python
# pydantic v2 frozen + 自定义 validator
class WorkflowCheckpoint(BaseModel):
    schema_version: str = Field(..., frozen=True)  # 写后只读
    ...
```

---

## 3. 保存路径设计（§5 → Python 实现）

### 3.1 保存路径流图

```text
Caller (RUNNING boundary / PAUSE command)
  │
  ▼
CheckpointBuilder.build(workflow_id, reason, source_event)
  │   ↑ 读取 Projections (TaskProjection/WorkflowProjection/...)
  │   ↑ 计算 StateSnapshot from current projections
  │   ↑ 从 Workflow.active_worker_refs 聚合 Worker refs (REQ §3.5)
  │   ↑ 生成 checkpoint_id (UUID)
  │
  ▼
WorkflowCheckpoint (in-memory, status=CREATED)
  │
  ▼
CheckpointHasher.compute(checkpoint)  ← checksum.py
  │   ↑ 使用 SHA-256(content) → content_hash
  │   ↑ 使用 SHA-256(metadata+content_hash) → checkpoint_hash
  │
  ▼
CheckpointRepository.save(checkpoint)
  │   ↑ 事务：先 save, 后 mark_event_processed (idem)
  │   ↑ 写存储（in-memory / 后续 PostgreSQL）
  │
  ▼
CheckpointCreated 事件追加入 EventStore（REQ-RT-003 + §5.2 步骤 10）
  │   event_id = "evt-{uuid}"
  │   partition_key = "workflow:{workflow_id}"
  │   payload = {checkpoint_id, source_event_sequence, source_event_id, ...}
  │
  ▼
checkpoint.checkpoint_status = VERIFIED
  │
  ▼
return verification_record (含 checkpoint_id, hash)
```

### 3.2 模块布局

```
src/runtime/checkpoint/                       # 新顶层包（与 src/runtime/projection 同级）
├── __init__.py
├── models.py                                 # 上面 §2.3 的所有数据类
├── builder.py                                # CheckpointBuilder
├── hasher.py                                 # SHA-256 哈希计算（content_hash + checkpoint_hash）
├── repository.py                             # CheckpointRepository（抽象 + InMemory 实现）
├── creator.py                                # CheckpointCreator（主流程协调：build + hash + save + 追事件）
├── credentials_guard.py                      # plaintext 凭据检测（§9 防御）
└── errors.py                                 # CheckpointError / InvalidHashError / InsufficientStateError
```

### 3.3 API 边界

**CheckpointCreator**（主入口）：

```python
class CheckpointCreator:
    """REQ-RT-005 §5 主入口"""
    
    def __init__(
        self,
        projection_readers: ProjectionReaderPort,    # 读 TaskProjection/WorkflowProjection 等
        event_store: EventStorePort,                # REQ-RT-003 EventStore 接口
        repository: CheckpointRepository,           # 本模块 repository
        hasher: CheckpointHasher,
        credentials_guard: CredentialsGuard,
    ): ...
    
    def create_running_checkpoint(
        self,
        workflow_id: str,
        source_event: dict,                         # 触发保存的事件（如 WorkflowStarted）
    ) -> WorkflowCheckpoint:
        """§5.1 RUNNING 保存路径"""
        ...
    
    def create_pause_checkpoint(
        self,
        workflow_id: str,
        source_event: dict,                         # WorkflowPaused 命令事件
        actor: str,                                 # 哪个用户触发的暂停
    ) -> WorkflowCheckpoint:
        """§5.1 PAUSE 保存路径"""
        ...
```

**CheckpointBuilder**：

```python
class CheckpointBuilder:
    """从投影 + 当前状态构建 Checkpoint 内容（不可变，且包含所有活跃 worker refs）"""
    
    def __init__(self, projection_reader: ProjectionReaderPort):
        self._projections = projection_reader
    
    def build(
        self,
        workflow_id: str,
        reason: CheckpointReason,
        source_event: dict,
    ) -> WorkflowCheckpoint: ...
```

**CheckpointHasher**：

```python
class CheckpointHasher:
    """REQ-RT-005 §4.1 checkpoint_hash / content_hash"""
    
    def compute_content_hash(self, content: WorkflowCheckpointContent) -> str: ...
    def compute_checkpoint_hash(self, checkpoint: WorkflowCheckpoint) -> str: ...
```

**CheckpointRepository**（抽象 + InMemory）：

```python
class CheckpointRepository(Protocol):
    """§5.3 存储抽象（同 REQ-RT-004 的 InMemoryStorage 接口风格）"""
    
    async def save(self, checkpoint: WorkflowCheckpoint) -> None: ...
    async def get(self, checkpoint_id: str) -> Optional[WorkflowCheckpoint]: ...
    async def list_for_workflow(self, workflow_id: str) -> list[WorkflowCheckpoint]: ...
    async def get_latest_verified(self, workflow_id: str) -> Optional[WorkflowCheckpoint]: ...

class InMemoryCheckpointRepository:
    """MVP 实现（PostgreSQL 实现留到 RT-005-P2）"""
    def __init__(self):
        self._checkpoints: dict[str, WorkflowCheckpoint] = {}  # by checkpoint_id
        self._by_workflow: dict[str, list[str]] = {}           # workflow_id → [checkpoint_id]
    
    # 实现 Protocol
    ...
```

### 3.4 保存路径的 10 步实现（§5.2）

每步对应一个测试用例：

| §5.2 步骤 | 实现位置 | 测试 |
|----------|---------|------|
| 1. 读取 Workflow 投影（事实） | `CheckpointBuilder._gather_state(workflow_id)` | `test_build_from_projection_*` |
| 2. 确认事件流无缺口 | `ProjectionReader.get_health_status()` | `test_save_requires_healthy_projection` |
| 3. 确认投影非 BLOCKED | `ProjectionReader.get_health_status().status != BLOCKED` | `test_save_rejects_when_blocked` |
| 4. 确认事实最新 | `check last_applied == source_event_sequence - 1` | `test_save_advances_source_seq` |
| 5. 确认 Artifact/Evidence 一致性 | 通过 projection 链接的 artifact 投影（P1 不实现，TODO） | 跳过 |
| 6. 确认 Workspace 哈希（如果有） | `ResourceSnapshot.workspace_state_hash` 校验（P1 不实现，TODO） | 跳过 |
| 7. 预字段分块计算 SHA-256 | `CheckpointHasher` | `test_hasher_*` |
| 8. 生成规范化内容 | JSON serialize + sort | `test_content_json_canonical` |
| 9. 持久化并校验 | `InMemoryCheckpointRepository.save` + `verify_hash` | `test_save_and_verify` |
| 10. 追加 CheckpointCreated 事件 | `event_store.append_event(...)` | `test_save_appends_event` |

---

## 4. 测试策略

### 4.1 单元测试（`tests/unit/runtime/checkpoint/`）

| 文件 | 测试数 | 覆盖目标 |
|------|--------|---------|
| `test_models.py` | 18-22 | 字段必填、不可变约束、敏感字段拦截、nested models 验证 |
| `test_hasher.py` | 4-6 | 内容哈希确定性、Checkpoint hash = SHA256(meta+content) |
| `test_builder.py` | 5-8 | 投影缺失时抛 InsufficientStateError、active worker refs 聚合、reason 注入 |
| `test_repository.py` | 4-6 | CRUD、并发安全（单线程原子）、by checkpoint_id 索引 |
| `test_credentials_guard.py` | 3-5 | 字段名匹配、值字符串匹配、嵌套扫描 |
| `test_creator.py` | 5-8 | RUNNING / PAUSE 两个完整流程、CheckpointCreated 事件被追加 |

**目标覆盖率**：行 ≥ 85%，与 RT-004 持平

### 4.2 集成测试（`tests/integration/runtime/checkpoint/`）

| 测试 | 验证 |
|------|------|
| `test_running_checkpoint_end_to_end` | 实际事件流 → RUNNING 边界 → checkpoint 落库 + 事件追加 |
| `test_pause_checkpoint_end_to_end` | Pause 命令 → checkpoint 落库 + checkpoint_status 周期 |
| `test_save_rejects_blocked_projection` | 投影 BLOCKED 时 create 调用抛 BlockedProjectionError |
| `test_restore_boundary_dry_run` | 加载 checkpoint（仅 dry run，不真恢复——留 P2） |

### 4.3 验证清单

```bash
pytest tests/unit/runtime/checkpoint/ tests/integration/runtime/checkpoint/ -v
pytest tests/  # 全量回归
ruff check src/runtime/checkpoint tests/unit/runtime/checkpoint
mypy src/runtime/checkpoint  # 预期：< 5 个 pre-existing no-untyped-def
```

---

## 5. 与现有模块的集成点

### 5.1 读侧——从 Projections 构建 Checkpoint

CheckpointBuilder 通过 `ProjectionReaderPort` 接口读 RT-004 的 Projection 状态：

```python
class ProjectionReaderPort(Protocol):
    def get_task_projection(self, task_id: str) -> TaskProjection | None: ...
    def get_workflow_projection(self, workflow_id: str) -> WorkflowProjection | None: ...
    def get_active_worker_projection_ids(self, workflow_id: str) -> list[str]: ...
    def get_worker_projection(self, worker_id: str) -> WorkerProjection | None: ...
    def get_health_status(self, partition_key: str) -> dict[str, Any]: ...
```

### 5.2 写侧——CheckpointCreated 事件追加入 RT-003 EventStore

```python
event = {
    "event_id": f"evt-{uuid4().hex[:12]}",
    "event_type": "CheckpointCreated",
    "event_type_version": "v1",
    "sequence": None,  # EventStore.append_event 自动分配
    "partition_key": f"workflow:{workflow_id}",
    "occurred_at": datetime.utcnow().isoformat(),
    "payload": {
        "checkpoint_id": checkpoint.checkpoint_id,
        "workflow_id": checkpoint.workflow_id,
        "task_id": checkpoint.task_id,
        "checkpoint_reason": checkpoint.checkpoint_reason.value,
        "checkpoint_status": checkpoint.checkpoint_status.value,
        "source_event_sequence": checkpoint.source_event_sequence,
        "source_event_id": checkpoint.source_event_id,
        "source_event_hash": checkpoint.source_event_hash,
        "checkpoint_hash": checkpoint.checkpoint_hash,
        "runtime_contract_version": checkpoint.runtime_contract_version,
        "workflow_template_version": checkpoint.workflow_template_version,
        "agent_profile_version": checkpoint.agent_profile_version,
        "toolset_version": checkpoint.toolset_version,
        # 注意：不要追加 credential / token / api_key 等敏感字段
    },
}
event_store.append_event(event)
```

### 5.3 与 Action 副作用模型的对接（前置约束）

`ActionCheckpointRef.side_effect_state` 和 `recovery_action` 字段在 REQ-RT-007（Idempotency）冻结前**保持为 Optional**，构造时不引入副作用值。

> 等 RT-007 文档冻结后，RT-005-P3 再为 `side_effect_state` 添加约束和默认值。

---

## 6. 风险与开放问题

### 6.1 风险

| 风险 | 缓解 |
|------|------|
| 恢复协议（§6）本轮不交付，未来 P2/P3 易出现 Design-Implementation Gap | 设计文档沉淀 §6 接口预期；本轮在 builder 加 `version_kind="v1_minimal"` 标记 |
| PostgreSQL 持久化层未实现，MVP 仅 InMemory | 在 Repository interface 留 PostgreSQL 实现位置，避免后续破坏契约 |
| ActionCheckpointRef.side_effect_state 依赖 RT-007 尚未冻结 | 字段占位为 None；P3 阶段再补 |

### 6.2 待您确认的开放问题

> 请您在复阅时一并回答以下问题，答案会写进最终实施记录：

1. **schema_version 字符串格式**（§4.1 提示 `"runtime.workflow-checkpoint.v1"`）
   - 选项 A：保持 `"runtime.workflow-checkpoint.v1"`（推荐，与 §4.1 一致）
   - 选项 B：改为 `"v1"`（更紧凑）
   - 期望答案：A

2. **§4.5 ResourceSnapshot 在 RUNNING 是否强制**？（§5.2 步骤 6 是 Workspace 哈希校验前置）
   - 选项 A：RUNNING 时**可选**（None 即跳过 Workspace 校验）
   - 选项 B：RUNNING 时**强制**（None 即拒绝保存）
   - 期望答案：A（与 §5.1 RUNNING 触发时机匹配——RUNNING 不强制 workspace 状态）

3. **CheckpointCreated 事件 sequence**——是否复用 RT-003 EventStore.append_event 自动分配？
   - 选项 A：**是**，让 EventStore 分配（同 RT-004 投影路径）
   - 选项 B：否，自己分配（破坏 EventStore 单调性约束）
   - 期望答案：A

4. **CheckpointCreated 事件是否要触发存储投影（如 CheckpointProjection）**？
   - 选项 A：是（新增 CheckpointProjection 用于查询 checkpoint 历史；推迟到 RT-005-P2）
   - 选项 B：否（通过 CheckpointRepository.list_for_workflow 查询即可，MVP 不需要专门投影）
   - 期望答案：B（最小 MVP）

---

## 7. DoR 验收清单（本轮交付完成时，您将看到）

✅ **代码交付**

- [ ] `src/runtime/checkpoint/` 完整目录，含 8 个文件（见 §3.2）
- [ ] `WorkflowCheckpoint`、`StateSnapshot`、`WorkerCheckpointRef`、`ActionCheckpointRef`、`BudgetSnapshot`、`ResourceSnapshot` 6 个核心数据类
- [ ] `CheckpointBuilder` 实现 RUNNING / PAUSE 两个 reason
- [ ] `CheckpointCreator.create_running_checkpoint` 与 `create_pause_checkpoint` 两个公共 API
- [ ] `CheckpointRepository` 接口 + `InMemoryCheckpointRepository` 实现
- [ ] `CheckpointHasher` 用 SHA-256
- [ ] `CredentialsGuard` 实施 §9 字段名 + 值内容的 plaintext 检测

✅ **测试交付**

- [ ] `tests/unit/runtime/checkpoint/` 至少 40 个单元测试（6 个测试文件）
- [ ] `tests/integration/runtime/checkpoint/` 至少 3 个集成测试
- [ ] 全仓库测试数从 540 → **600+**（预期新增 50-60 个）
- [ ] 行覆盖 ≥ 85%（in `src/runtime/checkpoint/` 模块本身）

✅ **文档交付**

- [ ] `docs/implementation/RT-005-checkpoint-protocol-completion-report.md`（交付报告）

❌ **明确声明 OUT-OF-SCOPE**

- 恢复协议（§6）的实际恢复逻辑——本轮不做
- APPROVAL / RECOVERY / HISTORY_BOUNDARY 三个 reason——本轮不做
- PostgreSQL 持久化层——本轮不做
- Action 副作用边界（§7）联动——本轮不做

---

## 8. 后续迭代计划（仅声明，不在本轮执行）

| 轮次 | 范围 | DoR 输出 |
|------|------|---------|
| **RT-005-MVP（本轮）** | 数据模型 + 保存路径 + 2 个 reason + InMemory 仓库 | 60 个测试 |
| RT-005-P2 | 恢复协议（§6）+ 3 个剩余 reason + PostgreSQL | 100+ 测试 |
| RT-005-P3 | Action 副作用边界（§7）+ 跨版本迁移 + 失败处理（§10） | 40+ 测试 |
| RT-005-P4 | 关键场景端到端集成（Kill Switch / 用户暂停 / 强高风险 Action 触发 APPROVAL 等） | 集成测试 |

---

**文档结束。本计划待您复阅并确认 §6.2 开放问题后，进入实施阶段。**
