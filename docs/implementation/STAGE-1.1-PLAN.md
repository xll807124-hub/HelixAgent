# 阶段 1.1 - Walking Skeleton 开发计划

> **状态**: 进行中  
> **分支**: `feature/stage-1.1-infra`  
> **时间线**: 2026-10-09 ~ 2026-10-18 (2 周)  
> **策略**: 与跨模块评审并行推进

---

## 🎯 阶段目标

实现从 Issue 到 PR 的**最小可靠闭环**，验证核心架构设计的可行性。

**核心能力**：
- ✅ 事件驱动的状态管理
- ✅ Worker 崩溃恢复
- ✅ 端到端任务执行

---

## 📅 迭代计划

### Week 1: 基础设施（2026-10-09 ~ 10-13）

#### Task 1: EventStore 基础实现
- **负责人**: TBD
- **工时**: 2 天
- **验收标准**:
  - [x] PostgreSQL schema 初始化脚本
  - [x] EventStore.append() 实现
  - [x] EventStore.read_stream() 实现
  - [x] EventEnvelope 序列化/反序列化
  - [x] 基础单元测试（覆盖率 > 80%）

**技术栈**:
```python
# src/runtime/event_store/postgres_store.py
class PostgresEventStore:
    def append(self, stream_id: str, events: List[Event], 
               expected_version: int) -> int
    def read_stream(self, stream_id: str, 
                    from_version: int = 0) -> List[EventEnvelope]
```

---

#### Task 2: 状态投影基础
- **负责人**: TBD
- **工时**: 2 天
- **验收标准**:
  - [x] Projector 基类实现
  - [x] InMemoryStorage 实现
  - [x] Checkpoint 机制
  - [x] TaskProjector 最小集实现
  - [x] Projection 重建测试

**技术栈**:
```python
# src/runtime/projection/postgres_projector.py
class Projector:
    def project(self, event: Event) -> None
    def rebuild_from(self, from_version: int = 0) -> None
    def get_checkpoint(self) -> int
```

---

#### Task 3: FastAPI 基础框架
- **负责人**: TBD
- **工时**: 1 天
- **验收标准**:
  - [x] FastAPI 项目结构
  - [x] POST /tasks - 创建任务
  - [x] GET /tasks/{id} - 查询任务投影
  - [x] GET /health - 健康检查
  - [x] OpenAPI 文档生成

**技术栈**:
```python
# src/api/main.py
@app.post("/tasks", response_model=TaskResponse)
async def create_task(request: CreateTaskRequest) -> TaskResponse

@app.get("/tasks/{task_id}", response_model=TaskProjection)
async def get_task(task_id: str) -> TaskProjection
```

---

### Week 2: 核心执行流程（2026-10-14 ~ 10-18）

#### Task 4: Worker 最小实现
- **负责人**: TBD
- **工时**: 3 天
- **验收标准**:
  - [x] Worker 注册和生命周期管理
  - [x] ReAct 循环实现（Reasoning + Action）
  - [x] Tool Adapter 抽象层
  - [x] read_file/write_file 工具实现
  - [x] Action 执行结果写入 EventStore

**技术栈**:
```python
# src/runtime/worker/base_worker.py
class Worker:
    def execute_task(self, task_id: str) -> None
    def _react_loop(self, context: Context) -> None
    def _execute_action(self, action: Action) -> ActionResult
```

---

#### Task 5: Checkpoint 协议实现
- **负责人**: TBD
- **工时**: 2 天
- **验收标准**:
  - [x] Checkpoint 数据结构定义
  - [x] save_checkpoint() 实现
  - [x] restore_from_checkpoint() 实现
  - [x] 幂等性 Key 生成器
  - [x] 崩溃恢复集成测试

**技术栈**:
```python
# src/runtime/checkpoint/protocol.py
@dataclass
class Checkpoint:
    task_id: str
    action_sequence: int
    worker_state: Dict[str, Any]
    idempotency_keys: Dict[str, str]
    created_at: datetime
```

---

#### Task 6: 端到端测试
- **负责人**: TBD
- **工时**: 2 天
- **验收标准**:
  - [x] E2E 测试：创建任务 → 执行 → 完成
  - [x] E2E 测试：Worker 崩溃 → 恢复 → 继续
  - [x] E2E 测试：重复操作幂等性验证
  - [x] 性能基准测试（延迟、吞吐量）

**测试场景**:
```python
# tests/e2e/test_task_lifecycle.py
def test_simple_task_execution():
    """任务执行成功"""
    task_id = create_task("修改 README.md")
    wait_for_completion(task_id)
    assert get_task(task_id).status == "COMPLETED"

def test_worker_crash_recovery():
    """Worker 崩溃后恢复"""
    task_id = create_task("多步骤任务")
    kill_worker_after_actions(2)  # 执行 2 个 Action 后杀死
    restart_worker()
    wait_for_completion(task_id)
    assert get_task(task_id).status == "COMPLETED"
```

---

## 🛡️ 风险控制

### 接口抽象策略

**未冻结接口使用配置层**：

```python
# config/interfaces.py
def get_failure_classifier():
    """获取失败分类器（评审可能改变实现）"""
    if feature_flags.is_enabled("new_classifier"):
        return NewFailureClassifier()
    return LegacyFailureClassifier()
```

### 每日同步机制

**时间**: 18:00（评审会后）  
**渠道**: Slack #stage-1.1-dev

**格式**:
```markdown
## 同步 - 2026-10-10

### 🚨 阻塞问题
- C-1: EVA-006 触发器类型未确定
  - 影响: Task 5 的 checkpoint 元数据结构
  - 应对: 使用 JSON 占位字段

### ✅ 已解决
- Task 1 EventStore 基础实现完成

### 📊 进度
- Week 1: 30% (Task 1 完成，Task 2 进行中)
```

---

## 📊 度量指标

### 开发进度

| 任务 | 预估 | 实际 | 状态 |
|------|------|------|------|
| Task 1: EventStore | 2天 | - | 🔜 待开始 |
| Task 2: Projector | 2天 | - | 🔜 待开始 |
| Task 3: FastAPI | 1天 | - | 🔜 待开始 |
| Task 4: Worker | 3天 | - | 🔜 待开始 |
| Task 5: Checkpoint | 2天 | - | 🔜 待开始 |
| Task 6: E2E 测试 | 2天 | - | 🔜 待开始 |

### 质量指标

| 指标 | 目标 | 当前 |
|------|------|------|
| 单元测试覆盖率 | > 80% | - |
| 集成测试通过率 | 100% | - |
| E2E 测试通过率 | 100% | - |
| Ruff 检查通过 | ✅ | - |

---

## 🔄 检查点

### Day 3 检查（2026-10-11）

**检查项**:
- [ ] 评审会是否发现结构性缺陷？
- [ ] Task 1-2 是否按计划完成？
- [ ] 是否有阻塞问题？

**决策**:
- ✅ 无问题 → 继续
- ⚠️ 有风险 → 调整优先级
- 🚨 重大问题 → 暂停等待评审结论

### Week 1 检查（2026-10-13）

**检查项**:
- [ ] Runtime Contract v1.0 是否冻结？
- [ ] Task 1-3 是否完成验收？
- [ ] Week 2 是否可以启动？

**Go/No-Go 决策**:
- ✅ 冻结完成 + Task 1-3 验收通过 → **Go Week 2**
- ⚠️ 部分冻结 → 调整 Task 4-6 优先级
- 🚨 评审延期 → 暂停 Week 2，补充 Task 1-3 测试

---

## 📝 开发规范

### Git 工作流

```bash
# 1. 从 feature/stage-1.1-infra 创建任务分支
git checkout feature/stage-1.1-infra
git pull origin feature/stage-1.1-infra
git checkout -b task/1-eventstore-impl

# 2. 开发 + 提交
git add src/runtime/event_store/
git commit -m "feat(runtime): implement EventStore append and read

- Add PostgreSQL schema for events table
- Implement append with optimistic locking
- Implement read_stream with pagination
- Add unit tests (coverage 85%)

Task: #1"

# 3. 推送 + 创建 PR
git push origin task/1-eventstore-impl
gh pr create --base feature/stage-1.1-infra \
             --title "feat(runtime): implement EventStore" \
             --body "Closes #1"
```

### PR 检查清单

- [ ] 单元测试覆盖率 > 80%
- [ ] Ruff + Black 检查通过
- [ ] MyPy 类型检查通过
- [ ] PR 描述清晰（背景、实现、测试）
- [ ] 关联 Issue 编号

---

## 📞 联系方式

| 问题类型 | 联系方式 |
|---------|---------|
| 阻塞问题 | Slack #stage-1.1-dev |
| 技术讨论 | GitHub Discussions |
| 评审同步 | 每日 18:00 例会 |

---

**最后更新**: 2026-10-08  
**负责人**: 开发团队
