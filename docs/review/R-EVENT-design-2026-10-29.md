# R-EVENT 设计方案：PostgreSQL 事件持久化

- 任务：R-EVENT（阶段 1.1，REQ：RT-001、RT-003）
- 模式：design（仅文档，不改生产代码）
- 负责人：cursor-revent-20261029-7c3e91
- 日期：2026-10-29
- 实现硬依赖：G-RT（当前待验收；实施基线批准前需其契约稳定）
- 写入范围：`src/runtime/event_store`、`tests/unit/runtime/event_store`（实现阶段）；本文件为设计阶段唯一写入物

## 1. 问题与边界

### 1.1 要解决的问题
当前 `EventStore` 只有 `InMemoryEventStore`，进程重启后事件丢失，无法支撑 Checkpoint、重放、审计与恢复。R-EVENT 提供 PostgreSQL 持久化实现，保持 `EventStore` ABC 语义不变。

### 1.2 范围内
- 追加写（单条）、按 ID 读、分页过滤读、最新序号、计数、健康检查。
- 每任务单调、无空洞的 `sequence`，事务内分配。
- 事件信封校验与非法事件拒绝（schema 版本、必填字段、大小上限）。
- 重复 `event_id`、重复 `idempotency_key` 的区分处理。
- Schema 迁移（幂等、带锁）与 WORM 防篡改约束。

### 1.3 范围外（由其他任务承担）
- 投影与重放：R-PROJ。
- Checkpoint：R-CHECK。
- 跨进程幂等写操作封装：R-IDEM（本任务只提供存储层唯一约束与结果语义）。
- 查询权限、留存、脱敏闭环：R-QUERY。
- 分区、归档、冷热分层：MVP 之后。

### 1.4 已有实现（复用）
- `src/runtime/event_store/envelope.py`：`EventEnvelope`、`CausationRef`、`ProducerRef`、`ContentRef`、`compute_content_hash()`。
- `src/runtime/event_store/store.py`：`EventStore` ABC、`InMemoryEventStore`、`AppendResult`/`AppendStatus`。工作区已有未提交修改（`get_latest_sequence` 返回 `next_sequence - 1`），实现阶段必须保留。
- `tests/unit/runtime/event_store`：已有 41 个用例通过，作为行为对照基线。

### 1.5 剩余缺口
1. 无持久化后端。
2. 无并发下的序号分配保证。
3. 无迁移机制与防篡改约束。
4. 无真实数据库集成测试。

## 2. 对标分析

来源均为官方文档，查阅日期 2026-10-29。下表区分已验证事实与本项目的推断。

### 2.1 参考系统

| 系统 | 已验证做法（官方资料） | 借鉴 | 规避 |
| --- | --- | --- | --- |
| Temporal Event History | 工作流事件历史为追加写、按序号排列，重放依赖确定性（docs.temporal.io） | 每流单调序号；事件不可变；以历史作为恢复依据 | 其历史长度上限与 Continue-As-New 机制不适用于本项目 MVP |
| LangGraph Persistence | Checkpointer 按 thread 保存状态快照（docs.langchain.com） | 事件与 Checkpoint 分离，Checkpoint 由 R-CHECK 单独实现 | 不把状态快照当作事件源 |
| PostgreSQL 咨询锁与行锁 | `pg_advisory_xact_lock` 事务级释放；`UPDATE ... RETURNING` 行锁串行化（postgresql.org/docs） | 用流计数器行锁分配序号；迁移用咨询锁 | 不使用 SEQUENCE 分配每任务序号，因为序列回滚会产生空洞 |
| psycopg 3 | `AsyncConnection` 可被多个 asyncio 任务共享但访问被串行化；Windows 下不兼容默认 `ProactorEventLoop`（psycopg.org/psycopg3/docs/advanced/async.html） | 使用 `psycopg-pool`，每操作取一条连接 | 在 Windows 本地开发需显式使用 `SelectorEventLoop` |
| asyncpg | 纯 asyncio 协议实现，官方称平均比 psycopg3 快约 5 倍，Apache-2.0（pypi.org/project/asyncpg） | 作为性能备选 | 吞吐不是 MVP 瓶颈，暂不引入第二套驱动 |

### 2.2 推断（未经官方验证）
- 本项目事件体量在 MVP 阶段下，单表无分区即可满足；分区需要在后续基于实测数据决定。
- 产品内部实现（Codex、Cursor 等）未公开事件存储细节，本方案不据此推断。

## 3. 关键设计决策

| 编号 | 决策 | 理由 |
| --- | --- | --- |
| D1 | 使用 psycopg 3 + `psycopg-pool`（异步） | 仓库已安装 3.3.6/3.3.3；同步与异步 API 一致，便于迁移脚本复用；性能足以满足 MVP |
| D2 | 单表 `runtime_events`，不分区 | PostgreSQL 分区表的唯一约束必须包含分区键；草案 `PRIMARY KEY (event_id)` 配合 `PARTITION BY LIST (organization_id)` 无法创建 |
| D3 | 每任务序号由 `runtime_event_streams` 计数器行分配 | 同事务内 `UPDATE ... RETURNING`，回滚则计数器同回滚，保证无空洞 |
| D4 | `event_id`、`idempotency_key` 独立唯一约束 | 区分「同一事件重复提交」与「同一业务操作重复提交」 |
| D5 | WORM：撤销 UPDATE/DELETE 权限 + 触发器兜底 | 角色权限是主防线，触发器防止误用高权限账号 |
| D6 | 迁移使用 `pg_advisory_xact_lock` 串行 | 多实例同时启动时避免重复建表 |
| D7 | 不使用 RLS `USING (FALSE)` | 草案该策略会阻断所有读取；租户隔离由 S-TENANT 统一设计 |

## 4. 接口设计

### 4.1 类与文件（实现阶段）

| 文件 | 内容 |
| --- | --- |
| `src/runtime/event_store/postgres_store.py` | `PostgresEventStore(EventStore)` |
| `src/runtime/event_store/migrations.py` | `apply_migrations(pool)`、版本表读写 |
| `src/runtime/event_store/sql/0001_init.sql` | DDL |
| `src/runtime/event_store/errors.py` | 存储层异常 |
| `tests/unit/runtime/event_store/test_postgres_*.py` | 单元测试与集成测试 |

不改动 `EventStore` ABC 的方法签名，也不改动 `EventEnvelope` 字段。

### 4.2 `PostgresEventStore`

```python
class PostgresEventStore(EventStore):
    def __init__(self, pool: AsyncConnectionPool, *, max_payload_bytes: int = 1_048_576) -> None: ...

    async def append(self, envelope: EventEnvelope) -> AppendResult: ...
    async def get_by_id(self, event_id: UUID) -> EventEnvelope | None: ...
    async def query(self, *, task_id: UUID, after_sequence: int = 0,
                    limit: int = 100, event_types: Sequence[str] | None = None) -> list[EventEnvelope]: ...
    async def get_latest_sequence(self, task_id: UUID) -> int: ...
    async def count(self, task_id: UUID | None = None) -> int: ...
    async def health_check(self) -> bool: ...
```

实现前须对照现有 ABC 的真实签名，以 ABC 为准；上面仅表达语义。

### 4.3 `append` 语义

| 场景 | 结果 |
| --- | --- |
| 新事件 | `AppendStatus.CREATED`，返回分配的 `sequence` |
| `event_id` 已存在且 `content_hash` 相同 | `DUPLICATE`，返回原 `sequence`，不写入 |
| `event_id` 已存在但 `content_hash` 不同 | 抛 `EventConflictError`（疑似篡改或 ID 复用） |
| `idempotency_key` 已存在且 `idempotency_digest` 相同 | `DUPLICATE`，返回原事件 |
| `idempotency_key` 已存在但 digest 不同 | 抛 `IdempotencyConflictError` |
| 校验失败 | 抛 `EventValidationError`，不触达数据库 |
| 连接失败、超时 | 抛 `EventStoreUnavailableError`，不吞异常、不返回成功 |

### 4.4 校验规则（入库前）
- `schema_version` 属于受支持集合；未知主版本拒绝，同主版本的较新次版本接受并保留未知字段在 `payload`。
- `event_type`、`task_id`、`occurred_at`（须带时区）、`producer` 必填。
- `payload` 序列化后不超过 `max_payload_bytes`，超出则要求使用 `content_refs`。
- `recorded_at` 由数据库 `now()` 写入，忽略调用方值。
- 不接受 `sequence` 由调用方指定。

## 5. 数据结构（DDL 概要）

```sql
CREATE TABLE runtime_schema_migrations (
    version     integer PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now(),
    checksum    text NOT NULL
);

CREATE TABLE runtime_event_streams (
    task_id        uuid PRIMARY KEY,
    next_sequence  bigint NOT NULL DEFAULT 1 CHECK (next_sequence >= 1)
);

CREATE TABLE runtime_events (
    event_id            uuid PRIMARY KEY,
    task_id             uuid NOT NULL,
    sequence            bigint NOT NULL CHECK (sequence >= 1),
    event_type          text NOT NULL,
    event_type_version  integer NOT NULL,
    schema_version      text NOT NULL,
    tenant_id           text NOT NULL,
    organization_id     text,
    project_id          text,
    repo_id             text,
    trace_id            text,
    span_id             text,
    occurred_at         timestamptz NOT NULL,
    recorded_at         timestamptz NOT NULL DEFAULT now(),
    causation           jsonb,
    producer            jsonb NOT NULL,
    content_refs        jsonb NOT NULL DEFAULT '[]'::jsonb,
    data_sensitivity    text NOT NULL,
    idempotency_key     text,
    idempotency_digest  text,
    content_hash        text NOT NULL,
    payload             jsonb NOT NULL,
    UNIQUE (task_id, sequence),
    UNIQUE (idempotency_key),
    CHECK ((idempotency_key IS NULL) = (idempotency_digest IS NULL))
);

CREATE INDEX runtime_events_task_type_idx ON runtime_events (task_id, event_type, sequence);
CREATE INDEX runtime_events_tenant_time_idx ON runtime_events (tenant_id, recorded_at);
```

说明：
- 最终列名以 `EventEnvelope` 实际字段为准，实现阶段逐字段对照；若字段缺失，先走共享契约变更评审，不在本任务内改信封。
- `UNIQUE (idempotency_key)` 的作用域（全局或按租户）需用户确认，见开放问题 Q2。
- WORM 触发器：`BEFORE UPDATE OR DELETE` 行级触发器与 `BEFORE TRUNCATE` 语句级触发器，均 `RAISE EXCEPTION`。应用角色仅授予 `INSERT, SELECT`；流计数器表需授予 `UPDATE`。

## 6. 状态与事务流程

`append` 单事务步骤：

1. 本地校验信封。
2. `BEGIN`。
3. `INSERT INTO runtime_event_streams (task_id) VALUES ($1) ON CONFLICT (task_id) DO NOTHING`。
4. `UPDATE runtime_event_streams SET next_sequence = next_sequence + 1 WHERE task_id = $1 RETURNING next_sequence - 1`，得到本事件序号，同时持有该任务行锁，同任务并发追加被串行化。
5. `INSERT INTO runtime_events ...`。唯一冲突则回滚，回到步骤 2 之前的状态，再按 4.3 查询既有行判定重复或冲突。
6. `COMMIT`。

不同任务互不阻塞。重复提交回滚会连带回滚计数器，因此序号不会出现空洞。

## 7. 权限与安全边界
- 应用角色只有 `INSERT/SELECT`，迁移使用独立高权限角色，两者连接串分开配置。
- 全部 SQL 参数化，不拼接字符串。
- 连接串只从环境变量读取（`AI_DATABASE_URL`），`.env.example` 增加占位条目，不写入真实值；日志与异常信息不得包含连接串或 payload 内容。
- `data_sensitivity` 原样保存，脱敏与访问控制在 R-QUERY。
- 本任务不暴露网络端点，因此无新增认证面。

## 8. 异常处理与恢复

| 情形 | 处理 |
| --- | --- |
| 连接池耗尽、超时 | 抛 `EventStoreUnavailableError`，调用方（R-RETRY）决定重试 |
| 事务中途连接断开 | 事务整体回滚；调用方用相同 `event_id` 重试，由 D4 保证幂等 |
| 序列化冲突或死锁 | 存储层有限次重试（默认 3 次，带抖动）；仍失败则抛不可用异常 |
| 进程取消（`CancelledError`） | 依 psycopg 文档，取消会请求服务端中止语句；事务回滚，不吞取消异常 |
| 迁移并发 | 咨询锁串行；校验已应用版本的 checksum，不一致则拒绝启动 |
| Windows 事件循环 | 文档化要求 `SelectorEventLoop`；测试夹具显式设置 |

## 9. 测试方案

| 测试项 | 用例 | 环境 |
| --- | --- | --- |
| 信封校验 | 缺字段、未知主版本、时区缺失、超大 payload 均被拒 | 纯单元 |
| 序号分配 | 同任务 50 并发追加，序号为 1..50 无重复无空洞 | 真实 PG |
| 回滚无空洞 | 重复事件提交后，下一个事件序号连续 | 真实 PG |
| 幂等区分 | 同 `event_id` 同 hash、同 `event_id` 不同 hash、同 key 不同 digest | 真实 PG |
| 重启持久化 | 写入后关闭连接池重建，数据仍在，序号继续递增 | 真实 PG |
| WORM | 应用角色 UPDATE/DELETE/TRUNCATE 均失败；高权限角色被触发器拦截 | 真实 PG |
| 分页过滤 | `after_sequence`、`limit`、`event_types` 组合 | 真实 PG |
| 迁移 | 重复执行幂等；并发执行仅一次生效；checksum 篡改被拒 | 真实 PG |
| 故障 | 连接中断、语句超时、任务取消后数据一致 | 真实 PG |
| 行为一致 | 同一套契约测试同时跑 `InMemoryEventStore` 与 `PostgresEventStore` | 两者 |

规则：
- 真实 PG 测试由 `AI_TEST_DATABASE_URL` 控制；未设置时标记 skipped 并如实报告，不得算作通过。
- 当前机器 Docker 守护进程未运行，真实 PG 验证在环境就绪前保持未执行状态。
- 覆盖率目标沿用《迭代开发规则》：整体 ≥70%，核心路径 ≥90%，幂等与序号分配 100%。
- 执行 `ruff`、`mypy`、`pytest` 与 `scripts/security_gate.py`。

## 10. 依赖与影响
- 新增运行时依赖：`psycopg[binary]`、`psycopg-pool`（实现阶段在 `requirements.txt` 固定版本，现有环境为 3.3.6 与 3.3.3，须确认与 `pyproject.toml` 一致）。
- 共享契约：不改 `EventStore` ABC 与 `EventEnvelope`；若发现字段缺口，先出影响评审。
- 下游：R-PROJ、R-CHECK、R-IDEM、R-QUERY 依赖本任务的表结构与 `AppendResult` 语义，基线确认后冻结 `0001_init.sql`。
- 上游：G-RT 目前待验收，若其验收引起事件信封变化，本方案需复核。

## 11. 验收标准（对应台账）
1. 重启后数据不丢失（真实 PG 验证）。
2. 非法事件被拒绝且不落库。
3. 并发追加序号连续无重复。
4. 版本兼容：同主版本较新次版本可写入并读回，未知主版本被拒。
5. WORM 约束生效。
6. 两个实现通过同一套契约测试。
7. 质量门禁通过，未执行项如实标注。

## 12. 限制与剩余事项
- 无分区、无归档、无保留清理（R-QUERY 及后续）。
- 无投影、无重放、无 Checkpoint。
- 真实 PG 测试依赖可用数据库，当前环境未就绪。
- `idempotency_key` 作用域待定。

## 13. 开放问题（需用户确认）

| 编号 | 问题 | 建议 |
| --- | --- | --- |
| Q1 | 驱动选择 | psycopg 3 + psycopg-pool |
| Q2 | `idempotency_key` 唯一性作用域：全局，或 `(tenant_id, idempotency_key)` | 按租户，与 S-TENANT 方向一致 |
| Q3 | 单事件 payload 上限 | 1 MiB，超出走 `content_refs` |
| Q4 | 真实 PG 测试环境：本地 Docker、CI service container，或已有实例 | CI service container，本地用 Docker |
| Q5 | G-RT 仍待验收，是否在其验收前先确认本基线 | 可先确认，G-RT 变更时复核 |

## 14. 来源与日期
- psycopg 3 并发与 asyncio：https://www.psycopg.org/psycopg3/docs/advanced/async.html（2026-10-29 读取，已验证 Windows 事件循环限制与取消语义）。
- asyncpg：https://pypi.org/project/asyncpg/（2026-10-29 读取，v0.32.0，Apache-2.0）。
- Temporal、LangGraph、PostgreSQL 咨询锁与行锁官方文档：本任务前期调研已查阅，引用为概念层面，未在本文逐页复核；实现阶段如依赖具体行为再补充链接。

