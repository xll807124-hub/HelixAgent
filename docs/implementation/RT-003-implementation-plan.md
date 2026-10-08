# REQ-RT-003 事件存储实现计划

> **任务编号**: RT-003  
> **任务名称**: Event Schema 与事件存储  
> **计划日期**: 2026-10-08  
> **预计工期**: 2-3天  
> **优先级**: P0 - 阻塞多个模块

---

## 一、实施方案

### 1.1 技术选型

**存储层**: PostgreSQL（MVP阶段）
- 理由：已有基础设施、ACID事务、JSONB支持、序列化
- 后续可迁移：EventStoreDB、Kafka等专用方案

**序列化**: JSON + JSON Schema验证
- 理由：可读性好、生态完善、便于调试
- 备选：Protobuf（性能优化阶段）

**消费模式**: Outbox + 轮询/通知
- 理由：简单可靠、与PostgreSQL集成好
- 备选：CDC（Change Data Capture）

---

## 二、模块设计

### 2.1 核心模块（6个文件）

```
src/runtime/event_store/
├── __init__.py              # 模块导出
├── envelope.py              # EventEnvelope 事件信封
├── store.py                 # EventStore 存储接口
├── postgres_store.py        # PostgreSQL实现（MVP）
├── outbox.py                # Outbox模式实现
└── schema_registry.py       # 事件Schema注册表
```

### 2.2 数据模型

#### EventEnvelope（事件信封）
```python
@dataclass
class EventEnvelope:
    # 元数据
    schema_version: str = "runtime.event-envelope.v1"
    event_id: EventId
    event_type: str
    event_type_version: str
    event_category: EventCategory
    
    # 业务坐标
    task_id: TaskId
    organization_id: EntityId
    project_id: EntityId
    repository_id: EntityId
    workflow_id: Optional[WorkflowId]
    worker_id: Optional[WorkerId]
    action_id: Optional[ActionId]
    
    # 追踪
    trace_id: TraceId
    span_id: Optional[SpanId]
    
    # 时序
    occurred_at: datetime
    recorded_at: datetime
    sequence: int  # 由存储层分配
    
    # 因果
    causation: CausationRef
    correlation_id: str
    idempotency_key: Optional[str]
    
    # 载荷
    payload_schema: str
    payload: Dict[str, Any]
    
    # 安全
    data_classification: DataSensitivity
    content_refs: List[ContentRef]
    
    # 生产者
    producer: ProducerRef
```

#### EventStore接口
```python
class EventStore(ABC):
    @abstractmethod
    async def append(
        self, 
        event: EventEnvelope
    ) -> AppendResult:
        """追加事件到存储"""
        
    @abstractmethod
    async def get_by_id(
        self, 
        event_id: EventId
    ) -> Optional[EventEnvelope]:
        """根据ID获取事件"""
        
    @abstractmethod
    async def query(
        self,
        task_id: TaskId,
        from_sequence: int = 0,
        to_sequence: Optional[int] = None,
        event_types: Optional[List[str]] = None,
        limit: int = 1000
    ) -> List[EventEnvelope]:
        """查询事件流"""
        
    @abstractmethod
    async def get_latest_sequence(
        self,
        task_id: TaskId
    ) -> int:
        """获取最新序列号"""
```

---

## 三、实现步骤

### Step 1: 数据模型层（envelope.py）
**预计时间**: 2小时

**任务**:
- [x] 定义 EventEnvelope Pydantic模型
- [x] 定义 EventCategory/CausationRef/ProducerRef
- [x] 添加序列化/反序列化方法
- [x] 添加内容哈希计算
- [x] 添加字段验证规则

**验收**:
- [ ] 创建合法EventEnvelope成功
- [ ] 必填字段缺失时抛出ValidationError
- [ ] 哈希计算可复现
- [ ] 单元测试覆盖率 ≥ 80%

---

### Step 2: 存储接口（store.py）
**预计时间**: 1小时

**任务**:
- [x] 定义抽象EventStore接口
- [x] 定义AppendResult/QueryOptions
- [x] 定义异常类型（DuplicateEventError/SequenceConflictError）
- [x] 添加接口文档

**验收**:
- [ ] 接口定义清晰完整
- [ ] 类型标注完整
- [ ] 文档覆盖所有公开方法

---

### Step 3: PostgreSQL实现（postgres_store.py）
**预计时间**: 4小时

**任务**:
- [x] 实现 append() - 追加式写入
  - 生成单调递增序列
  - 检查event_id重复
  - 检查idempotency_key冲突
  - 事务提交
- [x] 实现 get_by_id() - 单事件查询
- [x] 实现 query() - 流查询（支持分页、过滤）
- [x] 实现 get_latest_sequence() - 序列查询
- [x] 添加数据库连接池管理
- [x] 添加错误处理与重试

**数据库Schema**:
```sql
CREATE TABLE events (
    event_id UUID PRIMARY KEY,
    task_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    event_type_version VARCHAR(20) NOT NULL,
    event_category VARCHAR(20) NOT NULL,
    sequence BIGSERIAL,
    occurred_at TIMESTAMP NOT NULL,
    recorded_at TIMESTAMP DEFAULT NOW(),
    payload JSONB NOT NULL,
    envelope JSONB NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(255),
    
    UNIQUE(task_id, sequence),
    UNIQUE(idempotency_key)
);

CREATE INDEX idx_events_task_id ON events(task_id, sequence);
CREATE INDEX idx_events_type ON events(event_type, recorded_at);
CREATE INDEX idx_events_trace ON events((envelope->>'trace_id'));
```

**验收**:
- [ ] 追加事件成功并返回序列号
- [ ] 重复event_id被拒绝
- [ ] 序列号单调递增（同task_id内）
- [ ] 查询支持分页和过滤
- [ ] 并发追加安全

---

### Step 4: Schema注册表（schema_registry.py）
**预计时间**: 2小时

**任务**:
- [x] 定义事件类型注册机制
- [x] 实现Schema版本管理
- [x] 实现Schema验证（JSON Schema）
- [x] 添加迁移器注册接口
- [x] 添加MVP事件目录

**验收**:
- [ ] 注册的事件类型可查询
- [ ] Schema验证失败时抛出异常
- [ ] 支持多版本Schema共存

---

### Step 5: Outbox模式（outbox.py）
**预计时间**: 3小时

**任务**:
- [x] 实现Outbox表设计
- [x] 实现事件发布逻辑
- [x] 实现轮询消费者
- [x] 实现At-Least-Once语义
- [x] 添加重试与死信处理

**Outbox Schema**:
```sql
CREATE TABLE event_outbox (
    id BIGSERIAL PRIMARY KEY,
    event_id UUID NOT NULL REFERENCES events(event_id),
    published_at TIMESTAMP,
    retry_count INT DEFAULT 0,
    last_error TEXT,
    
    FOREIGN KEY (event_id) REFERENCES events(event_id)
);

CREATE INDEX idx_outbox_pending ON event_outbox(id) 
WHERE published_at IS NULL;
```

**验收**:
- [ ] 事件追加时自动进入Outbox
- [ ] 消费者可重复消费
- [ ] 失败事件进入重试队列
- [ ] 死信事件可人工处理

---

### Step 6: 集成测试
**预计时间**: 3小时

**任务**:
- [x] 测试完整事件流（append → query → consume）
- [x] 测试并发追加
- [x] 测试序列连续性
- [x] 测试幂等性
- [x] 测试故障恢复
- [x] 修复RT-004集成测试

**验收**:
- [ ] 所有集成测试通过
- [ ] RT-004模块测试从75%提升到≥90%
- [ ] 无数据竞争和死锁

---

## 四、测试策略

### 4.1 单元测试（每个模块）

**envelope.py** (15个测试):
- 创建合法事件
- 必填字段验证
- 字段类型验证
- 哈希计算一致性
- 序列化/反序列化

**postgres_store.py** (20个测试):
- 追加新事件
- 重复event_id拒绝
- 序列号生成
- idempotency_key冲突检测
- 查询过滤和分页
- 并发追加安全性

**schema_registry.py** (10个测试):
- 事件类型注册
- Schema验证
- 版本升级
- 未知事件处理

**outbox.py** (12个测试):
- Outbox入队
- 消费者轮询
- 重试机制
- 死信处理

### 4.2 集成测试（5个测试）

1. 端到端事件流测试
2. 多消费者并发消费
3. 故障恢复测试
4. 性能基准测试
5. RT-004状态投影集成

---

## 五、质量目标

| 指标 | 目标值 |
|------|--------|
| 单元测试覆盖率 | ≥ 85% |
| 集成测试通过率 | 100% |
| RT-004测试修复率 | 7/7 失败项全部修复 |
| Ruff检查 | 0 issues |
| Mypy检查 | 0 errors |
| 追加延迟p95 | < 100ms（目标） |
| 查询延迟p95 | < 50ms（目标） |

---

## 六、风险与依赖

### 6.1 技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| PostgreSQL性能瓶颈 | 中 | 预留序列优化、分区表方案 |
| 并发冲突 | 高 | 序列使用数据库SERIAL，事务隔离 |
| 事件体积膨胀 | 中 | ContentRef外部存储大型载荷 |

### 6.2 依赖项

**上游**:
- ✅ RT-001 核心实体（已完成）
- ✅ RT-002 状态机（已完成）

**下游（被阻塞）**:
- ⚠️ RT-004 状态投影（等待修复）
- ⏳ RT-005 Checkpoint
- ⏳ RT-006 Trace
- ⏳ REL-001 失败分类

---

## 七、交付检查清单

### DoD（Definition of Done）

#### 代码质量
- [ ] 全部代码通过Ruff检查
- [ ] 全部代码通过Mypy检查
- [ ] 单元测试覆盖率 ≥ 85%
- [ ] 集成测试全部通过

#### 功能完整性
- [ ] EventEnvelope模型完整
- [ ] PostgreSQL存储实现完整
- [ ] Outbox模式可用
- [ ] Schema注册可用
- [ ] 事件查询API可用

#### 测试验证
- [ ] 57个单元测试全部通过
- [ ] 5个集成测试全部通过
- [ ] RT-004的7个失败测试全部修复
- [ ] 并发测试通过
- [ ] 幂等性测试通过

#### 文档完整
- [ ] 模块文档完整
- [ ] API文档完整
- [ ] 实施日志完整
- [ ] 测试报告完整

#### 集成验证
- [ ] RT-004可成功消费事件
- [ ] 事件可被投影器消费
- [ ] 序列连续性验证通过

---

## 八、后续工作

完成RT-003后的下一步：

1. **立即修复**: RT-004集成测试（预计1小时）
2. **继续开发**: RT-005 Checkpoint Protocol（2天）
3. **并行开发**: RT-006 Trace传播（2天）
4. **性能优化**: 事件批量写入、查询优化（后续迭代）

---

**计划制定人**: AI Agent  
**计划日期**: 2026-10-08  
**开始执行**: 立即
