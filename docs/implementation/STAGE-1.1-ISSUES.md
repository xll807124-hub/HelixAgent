# 阶段 1.1 - 6 个核心任务清单

以下是 6 个 GitHub Issue 的详细内容，可以复制到 GitHub Issues 页面创建。

---

## Issue #1: EventStore 基础实现

**标题**: `[STAGE-1.1] Task 1: EventStore 基础实现`

**标签**: `stage-1.1`, `enhancement`, `P0`, `week-1`

**内容**:

```markdown
## 任务描述

实现基于 PostgreSQL 的事件存储基础功能，支持事件追加、流读取和版本控制。

## 验收标准

- [ ] PostgreSQL schema 初始化脚本完成
- [ ] `EventStore.append()` 实现（支持乐观锁）
- [ ] `EventStore.read_stream()` 实现（支持分页）
- [ ] `EventEnvelope` 序列化/反序列化
- [ ] 单元测试覆盖率 > 80%
- [ ] 集成测试：并发写入、版本冲突

## 技术细节

### Schema 设计

```sql
CREATE TABLE events (
    id BIGSERIAL PRIMARY KEY,
    stream_id VARCHAR(255) NOT NULL,
    version INT NOT NULL,
    event_type VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(stream_id, version)
);

CREATE INDEX idx_events_stream_id ON events(stream_id);
CREATE INDEX idx_events_created_at ON events(created_at);
```

### 接口定义

```python
# src/runtime/event_store/postgres_store.py
class PostgresEventStore:
    def append(
        self, 
        stream_id: str, 
        events: List[Event], 
        expected_version: int
    ) -> int:
        """追加事件到流，返回新版本号"""
        
    def read_stream(
        self, 
        stream_id: str, 
        from_version: int = 0,
        limit: int = 100
    ) -> List[EventEnvelope]:
        """读取事件流"""
```

## 依赖

- 无前置依赖
- 被依赖: Task 2 (状态投影)

## 测试计划

### 单元测试
- [ ] `test_append_single_event_succeeds()`
- [ ] `test_append_with_wrong_version_fails()`
- [ ] `test_read_stream_returns_events_in_order()`
- [ ] `test_read_stream_with_pagination()`

### 集成测试
- [ ] `test_concurrent_append_with_optimistic_locking()`
- [ ] `test_large_payload_serialization()`

## 参考文档

- 设计文档: `docs/design-specs/REQ-RT-003-event-schema-versioning.md`
- 接口定义: `docs/design-specs/G01-RUNTIME-CONTRACT-INTERFACE-REFERENCE.md`

## 预估工时

- 预估: 2 天
- 实际: 

## 备注

- 使用 `asyncpg` 作为 PostgreSQL 驱动
- 事件序列化使用 `pydantic` 保证类型安全
```

---

## Issue #2: 状态投影基础

**标题**: `[STAGE-1.1] Task 2: 状态投影基础实现`

**标签**: `stage-1.1`, `enhancement`, `P0`, `week-1`

**内容**:

```markdown
## 任务描述

实现事件到状态的投影机制，支持状态重建和 Checkpoint。

## 验收标准

- [ ] `Projector` 基类实现
- [ ] `InMemoryStorage` 实现
- [ ] Checkpoint 读写机制
- [ ] `TaskProjector` 最小集实现（PENDING/RUNNING/COMPLETED）
- [ ] 投影重建测试通过

## 技术细节

### Projector 基类

```python
# src/runtime/projection/projector.py
class Projector(ABC):
    def __init__(self, event_store: EventStore, storage: ProjectionStorage):
        self.event_store = event_store
        self.storage = storage
    
    @abstractmethod
    def project(self, event: Event) -> None:
        """投影单个事件"""
    
    def rebuild_from(self, from_version: int = 0) -> None:
        """从事件流重建投影"""
        checkpoint = self.get_checkpoint()
        events = self.event_store.read_all_from(checkpoint)
        for event in events:
            self.project(event)
            self.save_checkpoint(event.version)
    
    def get_checkpoint(self) -> int:
        """获取当前检查点"""
```

### TaskProjector 实现

```python
# src/runtime/projection/task_projector.py
class TaskProjector(Projector):
    def project(self, event: Event) -> None:
        if event.event_type == "task.created":
            self._handle_task_created(event)
        elif event.event_type == "task.started":
            self._handle_task_started(event)
        # ...
```

## 依赖

- 依赖任务: #1 (EventStore)
- 被依赖: Task 3 (API), Task 4 (Worker)

## 测试计划

### 单元测试
- [ ] `test_project_task_created_event()`
- [ ] `test_project_task_started_event()`
- [ ] `test_checkpoint_saved_after_projection()`
- [ ] `test_rebuild_from_empty_store()`

### 集成测试
- [ ] `test_full_rebuild_from_event_store()`
- [ ] `test_concurrent_projection_and_query()`

## 参考文档

- 设计文档: `docs/design-specs/REQ-RT-004-state-projections.md`

## 预估工时

- 预估: 2 天
- 实际: 

## 备注

- Week 1 只实现 InMemoryStorage，PostgreSQL 存储在 Week 2
```

---

## Issue #3: FastAPI 基础框架

**标题**: `[STAGE-1.1] Task 3: FastAPI 基础框架`

**标签**: `stage-1.1`, `enhancement`, `P1`, `week-1`

**内容**:

```markdown
## 任务描述

搭建 FastAPI 项目框架，提供任务创建和查询的 REST API。

## 验收标准

- [ ] FastAPI 项目结构搭建
- [ ] `POST /tasks` - 创建任务
- [ ] `GET /tasks/{id}` - 查询任务投影
- [ ] `GET /health` - 健康检查
- [ ] OpenAPI 文档自动生成
- [ ] 基础错误处理和日志

## 技术细节

### 项目结构

```
src/api/
├── main.py           # FastAPI app
├── routers/
│   └── tasks.py      # 任务路由
├── schemas/
│   └── task.py       # Pydantic 模型
└── dependencies.py   # 依赖注入
```

### API 接口

```python
# src/api/routers/tasks.py
@router.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(
    request: CreateTaskRequest,
    event_store: EventStore = Depends(get_event_store)
) -> TaskResponse:
    """创建新任务"""
    task_id = generate_task_id()
    event = TaskCreatedEvent(
        task_id=task_id,
        description=request.description,
        created_by=request.user_id
    )
    event_store.append(f"task-{task_id}", [event], expected_version=0)
    return TaskResponse(task_id=task_id)

@router.get("/tasks/{task_id}", response_model=TaskProjection)
async def get_task(
    task_id: str,
    projector: TaskProjector = Depends(get_projector)
) -> TaskProjection:
    """查询任务状态"""
    projection = projector.get_task(task_id)
    if not projection:
        raise HTTPException(404, "Task not found")
    return projection
```

## 依赖

- 依赖任务: #1 (EventStore), #2 (Projector)
- 被依赖: Task 6 (E2E 测试)

## 测试计划

### 单元测试
- [ ] `test_create_task_returns_201()`
- [ ] `test_get_task_returns_projection()`
- [ ] `test_get_nonexistent_task_returns_404()`
- [ ] `test_health_check_returns_200()`

### 集成测试
- [ ] `test_create_and_query_task_flow()`

## 参考文档

- FastAPI 文档: https://fastapi.tiangolo.com/

## 预估工时

- 预估: 1 天
- 实际: 

## 备注

- 使用 `uvicorn` 作为 ASGI 服务器
- 日志使用 `structlog`
```

---

## Issue #4: Worker 最小实现

**标题**: `[STAGE-1.1] Task 4: Worker 最小实现`

**标签**: `stage-1.1`, `enhancement`, `P0`, `week-2`

**内容**:

```markdown
## 任务描述

实现 Worker 的核心执行循环，支持基础工具调用和 Action 记录。

## 验收标准

- [ ] Worker 注册和生命周期管理
- [ ] ReAct 循环实现（Reasoning + Action）
- [ ] Tool Adapter 抽象层
- [ ] `read_file` 和 `write_file` 工具
- [ ] Action 执行结果写入 EventStore
- [ ] 基础错误处理

## 技术细节

### Worker 基类

```python
# src/runtime/worker/base_worker.py
class Worker:
    def __init__(self, worker_id: str, event_store: EventStore):
        self.worker_id = worker_id
        self.event_store = event_store
    
    def execute_task(self, task_id: str) -> None:
        """执行任务"""
        context = self._load_context(task_id)
        self._react_loop(context)
    
    def _react_loop(self, context: Context) -> None:
        """ReAct 循环：Reasoning → Action → Observation"""
        while not context.is_complete():
            # Reasoning
            action = self._decide_next_action(context)
            
            # Action
            result = self._execute_action(action)
            
            # Record
            self._record_action(action, result)
            
            # Update context
            context.add_observation(result)
    
    def _execute_action(self, action: Action) -> ActionResult:
        """执行 Action"""
        tool = self.tool_registry.get(action.tool_name)
        return tool.execute(action.parameters)
```

### Tool Adapter

```python
# src/runtime/worker/tools/base.py
class Tool(ABC):
    @abstractmethod
    def execute(self, params: Dict[str, Any]) -> ActionResult:
        """执行工具"""

# src/runtime/worker/tools/file.py
class ReadFileTool(Tool):
    def execute(self, params: Dict[str, Any]) -> ActionResult:
        path = params["path"]
        content = Path(path).read_text()
        return ActionResult(success=True, output=content)
```

## 依赖

- 依赖任务: #1 (EventStore), #2 (Projector)
- 被依赖: Task 5 (Checkpoint), Task 6 (E2E)

## 测试计划

### 单元测试
- [ ] `test_worker_executes_single_action()`
- [ ] `test_read_file_tool_returns_content()`
- [ ] `test_write_file_tool_saves_content()`
- [ ] `test_action_recorded_to_event_store()`

### 集成测试
- [ ] `test_worker_completes_simple_task()`
- [ ] `test_worker_handles_tool_error()`

## 参考文档

- 设计文档: `docs/design-specs/REQ-HAR-003-tool-adapter.md`

## 预估工时

- 预估: 3 天
- 实际: 

## 备注

- Week 2 只实现最基础的工具，更多工具在后续阶段
- LLM 调用暂时 mock，真实集成在阶段 1.2
```

---

## Issue #5: Checkpoint 协议实现

**标题**: `[STAGE-1.1] Task 5: Checkpoint 协议实现`

**标签**: `stage-1.1`, `enhancement`, `P0`, `week-2`

**内容**:

```markdown
## 任务描述

实现 Checkpoint 保存和恢复机制，支持 Worker 崩溃后从中断点继续执行。

## 验收标准

- [ ] Checkpoint 数据结构定义
- [ ] `save_checkpoint()` 实现
- [ ] `restore_from_checkpoint()` 实现
- [ ] 幂等性 Key 生成器
- [ ] 崩溃恢复集成测试通过

## 技术细节

### Checkpoint 数据结构

```python
# src/runtime/checkpoint/protocol.py
@dataclass
class Checkpoint:
    task_id: str
    worker_id: str
    action_sequence: int
    worker_state: Dict[str, Any]
    idempotency_keys: Dict[str, str]  # action_id -> key
    created_at: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化"""
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Checkpoint':
        """反序列化"""
```

### Checkpoint 管理器

```python
# src/runtime/checkpoint/manager.py
class CheckpointManager:
    def save_checkpoint(
        self, 
        task_id: str, 
        checkpoint: Checkpoint
    ) -> None:
        """保存 Checkpoint 到存储"""
        
    def load_checkpoint(self, task_id: str) -> Optional[Checkpoint]:
        """加载最新 Checkpoint"""
        
    def list_checkpoints(
        self, 
        task_id: str
    ) -> List[Checkpoint]:
        """列出所有 Checkpoint（调试用）"""
```

### Worker 集成

```python
# src/runtime/worker/base_worker.py (扩展)
class Worker:
    def execute_task(self, task_id: str) -> None:
        checkpoint = self.checkpoint_mgr.load_checkpoint(task_id)
        if checkpoint:
            context = self._restore_context(checkpoint)
        else:
            context = self._load_context(task_id)
        
        self._react_loop_with_checkpoint(context)
    
    def _react_loop_with_checkpoint(self, context: Context) -> None:
        while not context.is_complete():
            action = self._decide_next_action(context)
            
            # 生成幂等性 Key
            idempotency_key = generate_idempotency_key(
                task_id=context.task_id,
                action_sequence=context.action_count
            )
            
            # 保存 Checkpoint（Action 执行前）
            self.checkpoint_mgr.save_checkpoint(
                context.task_id,
                Checkpoint(
                    task_id=context.task_id,
                    worker_id=self.worker_id,
                    action_sequence=context.action_count,
                    worker_state=context.to_dict(),
                    idempotency_keys={action.id: idempotency_key}
                )
            )
            
            result = self._execute_action(action)
            self._record_action(action, result)
            context.add_observation(result)
```

## 依赖

- 依赖任务: #4 (Worker)
- 被依赖: Task 6 (E2E 测试)

## 测试计划

### 单元测试
- [ ] `test_save_checkpoint_persists_data()`
- [ ] `test_load_checkpoint_returns_latest()`
- [ ] `test_idempotency_key_generation()`

### 集成测试
- [ ] `test_worker_restores_from_checkpoint()`
- [ ] `test_duplicate_action_skipped_by_idempotency_key()`

## 参考文档

- 设计文档: `docs/design-specs/REQ-RT-005-checkpoint-protocol.md`
- 幂等性设计: `docs/design-specs/REQ-RT-007-idempotency-key.md`

## 预估工时

- 预估: 2 天
- 实际: 

## 备注

- Week 2 使用文件系统存储 Checkpoint，生产环境考虑 Redis/S3
```

---

## Issue #6: E2E 测试

**标题**: `[STAGE-1.1] Task 6: 端到端测试`

**标签**: `stage-1.1`, `enhancement`, `P0`, `week-2`

**内容**:

```markdown
## 任务描述

编写端到端测试，验证从任务创建到完成的完整流程，包括崩溃恢复场景。

## 验收标准

- [ ] E2E 测试：创建任务 → 执行 → 完成
- [ ] E2E 测试：Worker 崩溃 → 恢复 → 继续
- [ ] E2E 测试：重复操作幂等性验证
- [ ] 性能基准测试（延迟、吞吐量）
- [ ] 所有测试 100% 通过

## 技术细节

### 测试场景

```python
# tests/e2e/test_task_lifecycle.py

def test_simple_task_execution():
    """场景 1：简单任务执行成功"""
    # Given: 一个简单的文件修改任务
    task_id = create_task({
        "description": "修改 README.md 的第一行",
        "target_file": "README.md"
    })
    
    # When: Worker 执行任务
    worker = Worker("worker-1", event_store)
    worker.execute_task(task_id)
    
    # Then: 任务成功完成
    projection = projector.get_task(task_id)
    assert projection.status == "COMPLETED"
    assert len(projection.actions) == 2  # read + write
    assert Path("README.md").read_text().startswith("修改后的内容")


def test_worker_crash_recovery():
    """场景 2：Worker 崩溃后恢复"""
    # Given: 一个多步骤任务
    task_id = create_task({
        "description": "依次修改 3 个文件",
        "files": ["file1.txt", "file2.txt", "file3.txt"]
    })
    
    # When: Worker 执行 2 个 Action 后崩溃
    worker = Worker("worker-1", event_store)
    worker.execute_task_with_crash_after(task_id, crash_after_actions=2)
    
    # 检查 Checkpoint 已保存
    checkpoint = checkpoint_mgr.load_checkpoint(task_id)
    assert checkpoint.action_sequence == 2
    
    # When: 重启 Worker 并恢复
    worker2 = Worker("worker-2", event_store)
    worker2.execute_task(task_id)
    
    # Then: 任务从第 3 个 Action 继续并完成
    projection = projector.get_task(task_id)
    assert projection.status == "COMPLETED"
    assert len(projection.actions) == 6  # 3 个 read + 3 个 write
    
    # 验证所有文件都已修改
    assert Path("file1.txt").exists()
    assert Path("file2.txt").exists()
    assert Path("file3.txt").exists()


def test_idempotency():
    """场景 3：幂等性保证"""
    # Given: 一个任务和一个已执行的 Action
    task_id = create_task({"description": "写入文件"})
    action_id = "action-1"
    idempotency_key = "task-123:action-1"
    
    # When: 同一个 Action 执行两次（模拟重试）
    result1 = execute_action_with_key(task_id, action_id, idempotency_key)
    result2 = execute_action_with_key(task_id, action_id, idempotency_key)
    
    # Then: 第二次执行返回缓存结果，不重复执行
    assert result1 == result2
    assert get_action_execution_count(action_id) == 1


def test_performance_baseline():
    """场景 4：性能基准测试"""
    # 测试单任务延迟
    start = time.time()
    task_id = create_task({"description": "简单任务"})
    worker.execute_task(task_id)
    latency = time.time() - start
    assert latency < 5.0  # 5 秒内完成
    
    # 测试吞吐量
    start = time.time()
    task_ids = [create_task({"description": f"任务 {i}"}) for i in range(10)]
    for task_id in task_ids:
        worker.execute_task(task_id)
    throughput = 10 / (time.time() - start)
    assert throughput > 1.0  # 每秒至少 1 个任务
```

## 依赖

- 依赖任务: #1~#5 (所有前置任务)

## 测试计划

### E2E 测试
- [ ] `test_simple_task_execution()`
- [ ] `test_worker_crash_recovery()`
- [ ] `test_idempotency()`
- [ ] `test_performance_baseline()`

### 压力测试
- [ ] `test_concurrent_tasks()`
- [ ] `test_large_file_handling()`

## 参考文档

- 测试策略: `CONTRIBUTING.md` - 测试要求

## 预估工时

- 预估: 2 天
- 实际: 

## 备注

- 使用 `pytest-asyncio` 支持异步测试
- 使用 `pytest-benchmark` 进行性能基准测试
```

---

## 创建指南

### 方式 1：手动创建（推荐）

1. 访问 https://github.com/xll807124-hub/HelixAgent/issues/new
2. 选择 "阶段 1.1 任务" 模板
3. 复制上述内容到 Issue 正文
4. 添加对应标签和里程碑

### 方式 2：使用 GitHub CLI（需要安装 gh）

```bash
# 创建 Issue #1
gh issue create --title "[STAGE-1.1] Task 1: EventStore 基础实现" \
                --body-file task-1-eventstore.md \
                --label "stage-1.1,enhancement,P0,week-1"

# 创建 Issue #2
gh issue create --title "[STAGE-1.1] Task 2: 状态投影基础实现" \
                --body-file task-2-projector.md \
                --label "stage-1.1,enhancement,P0,week-1"

# ... 以此类推
```

---

**下一步**: 创建完 6 个 Issue 后，在 GitHub Projects 中创建看板跟踪进度。
