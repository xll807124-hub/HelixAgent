# G-OBS 遥测与审计契约：实施前设计

日期：2026-10-29。负责人：`codex-geva-20261029-01a185f6`。模式：design。

本文是任务专属评审稿，提交后状态为“待确认”；不修改或冻结 OBS/RT/SEC/EVA 共享契约，不构成生产实现批准。实时状态、负责人和依赖以[共享台账](../development/task-board.json)为准。本文的“建议”“拟定”接口均待用户确认；已有明确批准的规则直接沿用。

## 1. 本次范围与调度

本次解决 OBS-001～007 草稿、既有 Runtime 基线及观测代码之间的接口差异，为 G-OBS 后续契约整理提供可审阅基线。产物仅为本文，包含对标、缺口、接口、确认项和验证报告。

| 任务 | 检查时状态 / 负责人 | 实现硬依赖 | 当前阻塞及安排 |
|---|---|---|---|
| G-OBS 遥测与审计契约 | 开发中 / 本会话 | G-RT | design 可提前；实施须等 G-RT 验收及本文确认 |
| G-RT 运行时共享契约核对 | 待验收 / codex-grt-20261029-01a185ef | 无 | 仅只读引用其成果，不代填用户验收 |
| G-SEC 安全与租户共享契约 | 开发中 / codex-gmem-20261029-01a185f7 | 无 | 安全权限、留存例外和 Kill Switch 接口待汇合；不修改其文件 |
| G-EVA 评估与发布契约 | 待验收 / 本会话 | 无 | Q8 事件及指标血缘仍是待确认提案，不能当作冻结事实 |
| O-TRACE 全链路 Trace 与关联 | 待开发 / 无 | G-OBS | 后续模块需独立批准、领取和测试 |
| O-AUDIT 审计查询留存与完整性 | 待开发 / 无 | G-OBS、G-SEC | 后续真实存储、权限及完整性验收 |
| O-METRIC 指标仪表盘与告警 | 待开发 / 无 | G-OBS | 静态指标模块可独立；真实阻断联动在 M2 汇合 S-KILL |

遵循[执行手册](../../项目开发执行手册.md)“依赖驱动调度与多 AI 领取”及[迭代规则](../../规则文档/AGENTS.md)。检查到工作区存在多个其他会话的未提交修改，全部保留。本次仅写 `docs/review/G-OBS-design-2026-10-29.md`，台账通过 `scripts/task_board.py` 更新。未新增依赖，未改正式测试、生产代码、共享 REQ、README、环境配置或数据库。

后续 G-OBS 文档实施范围是 `docs/development/contracts/observability.md`。O-TRACE 台账范围尚未包括既有 `src/api/middleware/trace.py` 和 `src/observability/tracer.py` 等文件；将来修复这些基础设施前，须按台账锁规则协调写入范围，不能凭本文扩权。本文没有修改任务依赖或拆分工作包。

## 2. 需求映射、复用基础与剩余缺口

| 需求及原文 | 已有基础（只读核对） | 本次明确的缺口与后续验收 |
|---|---|---|
| [OBS-001 OTel](../design-specs/REQ-OBS-001-opentelemetry-semantic-conventions.md) | TracerProvider、Span 工厂、Context 桥接、Runtime ParentBased 采样和传播器 | HTTP 入口信任校验、实际 Span 与响应 Trace 一致性、低基数命名、认证加密导出、失败采样口径 |
| [OBS-002 关联 Schema](../design-specs/REQ-OBS-002-trace-event-evidence-schema.md) | Runtime EventEnvelope、AuditRecord、业务 ID/Trace ID 关联 | UUID 与 W3C ID 混写；Event 不能取代冻结事件信封；审计/Evidence 缺可验证的持久化关联 |
| [OBS-003 指标](../design-specs/REQ-OBS-003-metrics-dictionary.md) | 指标字典草稿，模型网关 usage 基线已有 | 自定义与 OTel 标准名称区分；attempt/逻辑请求去重；未知费用；评估事件与指标分离；指标后端未验收 |
| [OBS-004 脱敏和基数](../design-specs/REQ-OBS-004-redaction-cardinality-control.md) | RT-008 递归脱敏及回归用例 | 采集前脱敏、深度/字节/时间界限、跨 chunk 保护、FULL 绕过冲突、组合基数硬限 |
| [OBS-005 告警联动](../design-specs/REQ-OBS-005-alert-killswitch-linkage.md) | 告警与 SEC-009 设计草稿 | 两份三维矩阵不一致，M1 被写为“观察”；联动幂等、未知结果恢复、真实通知及阻断未验收 |
| [OBS-006 审计查询](../design-specs/REQ-OBS-006-audit-query-api.md) | RT 查询按 task/sequence、权限级别和脱敏已有 | 独立审计 API、绑定授权的游标、持久化多租户过滤、异步导出与撤权、统一响应 |
| [OBS-007 留存完整性](../design-specs/REQ-OBS-007-audit-retention-integrity.md) | 留存策略计算、审计关联模型 | 留存冲突、并发哈希链、外部锚定、真实分层存储、保全竞态、跨副本删除及恢复验证 |

补充依据：[需求分析报告](../需求分析报告.md)、[G-RT 核对](../development/contracts/runtime.md)、[RT-003](../design-specs/REQ-RT-003-event-schema-versioning.md)、[RT-006](../design-specs/REQ-RT-006-Trace-传播和审计关联.md)、[RT-008](../design-specs/REQ-RT-008-event-query-retention-redaction-permission.md)、[SEC-008](../design-specs/REQ-SEC-008-multi-tenant-data-governance.md)、[SEC-009](../design-specs/REQ-SEC-009-kill-switch-incident-response.md)、[G-MODEL](../development/contracts/model.md)、[G-EVA](../development/contracts/evaluation.md)。G-SEC 的最终交付文档在本次读取时尚不存在，以相关 REQ 为研究依据，不假定其在研方案已批准。

代码核对定位：`src/observability/{tracer,context,spans}.py`、`src/api/middleware/trace.py`、`src/runtime/trace/{context,propagation,sampling,audit_correlation}.py`、`src/runtime/query/{event_query,access_control,redaction_engine,retention_policy}.py`、`src/runtime/event_store/envelope.py`、`src/api/schemas/common.py`。

已验证的实现限制：

- `tracer.py` OTLP 分支显式使用 `insecure=True`，默认使用 SimpleSpanProcessor；不能据此声称已具备生产安全导出和有界异步重试。
- HTTP 中间件读取来访 ID，却未把解析出的远程 SpanContext 装入新建 OTel Span；响应 ID 与 SDK Trace 的一致性需专项验证。Span 名称直接包含 URL path。
- `AuditCorrelation` 创建记录不等于持久化提交成功。现有查询是 Runtime 任务事件查询，不等同于 OBS-006 的跨任务审计查询。
- 当前权限控制在 project/repository 未指定时采用简化放行，且存在 PLATFORM_ADMIN 跨组织分支；不能直接复用为审计平台的完整资源授权。
- 递归脱敏已有价值，但 FULL 策略允许保留敏感值，未提供 OBS 所需的深度、环引用、输出大小与跨 chunk 预算。旧访问级别不能直接映射为允许采集秘密。
- 当前 RetentionPolicies 对审计设置 `legal_hold_days=None`（永久）；它是实现现状，不是可以覆盖用户确认留存基线的依据。

## 3. 官方对标（访问日期均为 2026-10-29）

以下“事实”只来自当次查阅的官方公开页面，未验证产品内部架构；“本项目选择”是设计建议，不归因于竞品内部实现。

| 来源 | 已验证公开事实 | 优点及本项目选择 |
|---|---|---|
| [Claude Code Monitoring](https://code.claude.com/docs/en/monitoring-usage) | 分别导出指标、事件及可选 Trace；提示词/工具内容默认受采集开关控制；提供指标维度开关 | 借鉴信号分离及显式内容控制。项目继续禁止 session/user/task ID 作指标标签，不照搬其全部默认维度 |
| [Cursor Compliance and Monitoring](https://cursor.com/docs/enterprise/compliance-and-monitoring) | 管理审计记录成员、权限、设置等变更；公开文档明确审计载荷不包含提示词、生成代码或凭据 | 借鉴管理审计与内容分离，保留稳定主体及操作坐标；不据此推断其存储、哈希链或脱敏分词算法 |
| [OTel GenAI events 官方仓库](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-events.md) | `gen_ai.evaluation.result` 是事件；有评估名称、评分、标签和关联字段；页面标记 Development | 评估明细保留为事件/评估记录，聚合指标另行定义；固定本项目 schema 版本，不能自动追随 main |
| [OTel Sampling](https://opentelemetry.io/docs/concepts/sampling/) | 头部采样不能保证保留后来出现错误的完整 Trace；尾部采样需要更多状态和资源 | 保留已确认 15% 基线，明确失败事实审计必存；不声称头部采样能补回已丢 Span |

上述来源没有证明“Cursor 的具体 key 词素算法”“竞品都默认 7 年留存”“SHA 哈希链可阻止管理员改写”。原草稿中的这些推断不作为本项目证据。外部 GenAI 文档仍在变化，正式契约实施需记录实际采用的上游版本/提交及映射表；本轮没有升级 SDK 或宣布全部 `gen_ai.*` 为标准指标。

## 4. 沿用事项与需要确认的实质性差异

直接沿用：Runtime 已冻结实体与 EventEnvelope 版本策略；默认 15% Trace 采样；必需审计独立且不可采样丢失；默认内容关闭；审计默认热 30 天、冷 180 天；授权和租户隔离不可由 Trace ID 代替。这里不重新申请已确认事项。

下表 Q1～Q8 是本次新增或存在冲突的实施提案，均尚未批准；批准范围包括引用章节的接口、边界和验收口径。未确认时继续保留原文件，不静默选择某份草稿覆盖另一份。

| ID | 原文差异 / 风险 | 建议及影响面 |
|---|---|---|
| Q1 关联与事件适配 | OBS-002/007 把 trace_id 写为 UUID；RT 使用 32 hex；RT `TaskFailed`、OBS `task.failed`、EVA 示例 `task.execution.failed` 不同 | 采用 §5 的观测视图和显式来源版本映射；不改 Runtime wire schema，不合成别名业务事件。影响 O-TRACE、O-AUDIT、E-FEED |
| Q2 内容与调试 | OBS-001 FULL 上限 7 天且要求脱敏；OBS-004 为 24h，但流程第 5 步写“跳过脱敏” | 建议单 task、管理员批准、最长 24h 可撤销；始终先脱敏，凭据和隐藏推理永不捕获；调试内容独立 TTL 最长 7 天。影响 O-AUDIT、Worker/Tool 采集边界及管理入口 |
| Q3 失败采样 | 草稿“失败 Trace 100%”无法由现有 ParentBased 头部采样保证 | 保持正常 15%，已知高风险在创建根 Span 前提升；事后失败必存审计但不承诺完整 Trace。若必须完整失败 Trace，另批尾部采样部署与成本。影响 O-TRACE 及性能验收；不能把此项当作已接受降标 |
| Q4 指标口径 | 任务完成数含失败又另列失败；哈希/单标签限制不能约束组合基数；评估结果混作指标 | 采用 §7 的计数/单位/未知值/组合上限；内部历史 `gen_ai.*` 名称标为项目指标。影响 O-METRIC、W-MODEL、EVA；不改变费用账本 |
| Q5 查询和权限 | OBS-006 流程只允许管理员、表格又含审计员；跨租户空结果与权限错误并存；返回体不符合统一 envelope | 采用 §8：能力授权加资源约束，显式越租户过滤拒绝，列表只含授权资源；保留统一 envelope；游标绑定权限版本。影响 O-AUDIT、API 调用方及 G-SEC |
| Q6 留存和保全 | RT 默认 30/180，OBS 写 7 年，代码永久；孤儿数据 90 天删除可能误删审计 | 保留已确认默认；7 年仅作经批准的扩展 profile；保全独立于分类 TTL，迁移不刷新期限，关联缺失不缩短审计期限。影响 O-AUDIT、G-SEC、备份/恢复；不触发历史清理 |
| Q7 告警与安全模式 | OBS-005 将 M1 标为观察；与 SEC-009 三维矩阵不同；数字大小比较不能代表权限包含关系 | M0 才是 OBSERVE；OBS 产出信号与建议，由 G-SEC 确认的一份版本化矩阵决定模式。§9 定义幂等请求和未知结果；冲突规则不得自动执行。影响 O-METRIC、S-KILL、M2 |
| Q8 完整性与删除 | payload-only 哈希漏掉主体/关联字段；同库根哈希不能抵抗整链重写；tombstone/计数差不能证明物理删除 | 采用 §10 的完整规范化记录、租户序列、独立签名锚点和分存储删除回执。对未清副本、未过对象锁、未过保全如实记未完成。影响 O-AUDIT、G-SEC、恢复验证 |

Q1/Q4 与 G-EVA Q8 有交集，本文确认也不会自动批准 G-EVA 的其他待定项。Q5/Q6/Q7/Q8 需要与 G-SEC 的最终方案汇合，不能让正在开发的安全任务被迫追随本草案。

## 5. 关联模型与接口（Q1）

### 5.1 事实与投影视图

运行事实由冻结 Runtime EventEnvelope 表达，观测模型仅投影和关联。版本化适配器建议接口：

```text
project_event(envelope, authenticated_scope, mapping_revision)
  -> ObservationEvent | UNREGISTERED_EVENT | SCOPE_MISMATCH | INVALID_REFERENCE
append_audit(record, authenticated_scope, idempotency_key)
  -> AuditReceipt{audit_id, organization_id, sequence, committed_at, integrity_hash}
read_evidence(evidence_id, principal, purpose)
  -> AuthorizedEvidence | NOT_FOUND | PERMISSION_DENIED | UNAVAILABLE
```

接口为逻辑契约，非已发布 HTTP API 或生产类。现有 Envelope 不加字段、不换 event_id、不重置 sequence，不将审计模型直接继承为新的 Runtime 信封。

| 字段组 | 约束 |
|---|---|
| 版本 | `schema_version=obs.observation.v1`（拟）；独立 `mapping_revision`、`redaction_policy_revision`，不复用 EventEnvelope 版本号 |
| 原始事件 | `source_event_id/source_event_type/source_event_version/source_payload_schema` 原样引用；`event_name` 是观测名，不驱动 Task 状态机 |
| 租户与资源 | `organization_id` 必填且来自认证范围；task 事件继承 project/repository/task 坐标；组织级管理事件显式 `scope_kind=ORGANIZATION`，不伪造 task_id |
| 主体 | 复用 ActorRef/ResourceRef；服务验证委托链，客户端提交的 actor_id 不是身份凭据；无法确定主体时记录受限的 system/unknown 原因 |
| Trace | 非零 32 位小写 hex；Span 非零 16 位小写 hex；不使用带连字符 UUID。无 Trace 时允许 null 并记原因；未采样但已有合法 Context 时保留 ID |
| 时间与顺序 | occurred_at/recorded_at 均带 UTC；保留原始业务序列，另用审计提交序列排序；不能按时间或 Trace ID 推断业务先后 |
| 内容与证据 | 仅 allowlist metadata 和受控 evidence_refs；引用必须同租户且资源权限可验证，禁止直接返回存储 URI/长效签名 URL |

建议映射键为 `(source_system, source_event_type, source_event_version)`，值为观测名、分类及显式字段转换。已核对候选：Runtime `TaskFailed` → 观测 `task.failed`；EVA 文档的 `task.execution.failed` 只在 EVA 来源及版本确认后登记。未知映射拒绝进入派生指标/业务消费，记录不含原始载荷的错误；不丢弃已经提交的源审计事实。

兼容流程：先增加独立视图/适配器和读取能力，针对已登记来源校验，再切换观测消费者。迁移前后的同一 source_event_id 在同一映射版本内只计一次；不得双写新旧事件后重复统计。旧 Runtime 读写和历史证据 ID 保持有效。

Trace 汇总状态是投影，不决定 Task 终态；可有 `OPEN/CLOSED/INCOMPLETE` 的观测完整性状态，与业务 `COMPLETED/FAILED/CANCELLED` 分字段保存。缺失父 Span 保留引用并标注未关联，不伪造父级，不按“任一子 Span ERROR”直接判整个 Task 失败。

Evidence 元数据至少含组织/资源范围、evidence_id、来源事件/Span、脱敏后内容 hash 和大小、媒体类型、策略版本、创建时间、保留 profile、存储引用。hash 证明对象一致性，不证明内容真实或操作成功；高敏证据签名引用 algorithm/key_id，不把 HMAC 共享密钥验证描述为公开不可抵赖。

### 5.2 审计提交与副作用

必需审计类别沿用 RT-006 §6.1，覆盖开始、拒绝、成功、失败、超时、取消、恢复及结果未知。采集点位于平台控制点和执行器，不接受模型自述充当事实。

`append_audit` 返回 receipt 必须表示事务已持久提交，内存入队或仅构造 AuditRecord 不算成功。同一租户和幂等键、同一规范化内容重试返回原 receipt；内容不一致返回冲突，不能覆盖旧事实。

受保护动作先提交 intent/授权证据，再执行副作用，再追加 outcome。若结果提交失败，保留未决 intent，暂停新的相关副作用并走查询/对账；不能盲目重试业务调用。将重启、网络超时和取消区分为 `UNKNOWN` 或可证明终态，只有对账事实可关闭未决记录。

## 6. Trace、传播与内容控制（Q2/Q3）

- 统一由 SDK 实际 Context 产生响应、审计和下游传播 ID。内部已认证边界按策略提取，外部未登记入口新建根 Trace；`X-Trace-Id` 仅为相关性输入，不是信任或授权。非法格式、全零 ID、超长 header、未知受限版本安全拒绝提取，不让解析异常导致服务崩溃。
- Baggage 先白名单、长度/数量限制及值校验；org/project 等值只能来自服务端已验证范围，不能据来访 baggage 授权。对模型供应商、GitHub、MCP 等外部端点，只有明确登记且获准才传播；否则保留本地 client Span 和受控 provider_request_id。
- Span 名称使用固定操作或路由模板，task_id/原始路径不拼入名称。业务 ID 放入访问受控属性，不提升为指标标签。异步/重试/恢复使用真实父关系或 Span Link；link 包含目标 trace_id 和 span_id。
- 默认 root 采样率 0.15，已知高风险/批准诊断在根 Span 创建前设高优先级；子级保持链路决定。事后失败独立审计必存；未采到的历史 Span 不可恢复，禁止宣称完整失败 Trace 已留存。
- Trace 导出采用有界异步队列；候选上限 10,000 spans、退避 1/2/4/8/16 秒并加抖动、耗尽丢弃并计数。导出超时不拖住业务；审计提交失败遵守 §5.2，不与 Trace fail-open 混用。TLS/端点认证/租户出口由安全配置提供，禁止失败后自动把正文打到 console。

内容策略：`DISABLED` 默认只允许经过校验的元数据；`FEEDBACK_ONLY` 允许评分/受控归因，开放解释正文仍需脱敏；`FULL` 仅批准的 task、用途及期限内有效。Q2 建议最长 24h，撤销立即生效且在缓存边界复核，超时恢复 DISABLED。

脱敏在序列化到队列、日志、文件或 exporter **之前**执行，Collector 过滤为第二道防线。PUBLIC 标记也不能跳过凭据/PII 检测；未知键默认删除。凭据值、授权 header、隐藏推理不因管理员权限或 FULL 放行。日志异常正文也只允许受控错误类别。

候选资源预算：递归深度 32，流捕获累计最多 1 MiB；检测器超时预算 100ms，记录总处理预算另行压测确定。环引用、深度/大小/时间超限或规则不可用时丢弃整段内容，保留固定错误类别和安全元数据，不能返回原文兜底。流式内容先缓冲完成后整体扫描，超限放弃本次捕获，不发送未经验证的 chunk。

`token_count` 等统计字段通过“字段路径 + 数值类型”白名单保留；`api_key/accessToken/Authorization` 等始终遮蔽。统计后缀不是放行任意字符串的理由。HMAC 仅用于需关联的受限字段，必须绑定租户与 key_id；哈希会保留唯一性，不能作为降低基数的措施。

调试授权记录只存主体引用、task、用途代码、批准者、起止时间、策略版本；调试内容按独立 profile 最长 7 天清理。Legal Hold 等例外按 §10 处理，不把“到期”写成已完成物理删除。

## 7. 指标、血缘与基数（Q4）

保留 OBS-003 原有字典作为待映射的项目指标，避免无评审改名。每个指标登记 `name/type/unit/temporality/allowed_dimensions/aggregation/source_event/dedup_key/version`。标准属性映射、单位转换和 Prometheus 名称转换只在 exporter 适配层进行；同一事实不能因兼容导出重复计量。

| 指标族 / 现有名称 | 建议明确的计量口径 |
|---|---|
| `gen_ai.task.completed.total` | 计已结束的 success+failure；cancelled 单列。`failed.total` 是其中 failure 子集，错误率分母不能再加 failed；零分母为 NO_DATA，不记 0% |
| `gen_ai.task.duration`、`gen_ai.tool.duration` | 保持内部字典 ms，使用单调时钟；跨进程时钟不直接相减；若导出标准秒单位，只转换一次并标明映射版本 |
| `gen_ai.tool.calls.total`、success/failure/timeout | 每次工具 attempt 一次，按已提交终态去重；超时是失败子集还是独立结果须在登记表固定，建议 result 互斥为 success/failure/timeout/cancelled/unknown |
| `gen_ai.model.requests.total`、errors、latency、ttft | 请求数按实际 attempt，逻辑 request 成功率另算；未收到 token 的 TTFT 不填零；重试次数和失败尝试不吞掉 |
| `gen_ai.token.*` | 以 G-MODEL 已确认 usage 语义为准；unknown 不填 0；reasoning/cache 是否为 input/output 子集由 provider 映射注明，不能把子集全部再相加得到 total |
| `gen_ai.cost.*` | 使用账本给定币种/最小单位与定价版本；不同币种不直接聚合；估算与已核对金额分开。Prometheus 展示不能充当授权预算或账单事实 |
| `gen_ai.evaluation.result` | OTel 事件，至少评估名和适用的分值/标签；项目血缘保存 evaluation/report/evidence/config 引用，正文解释遵守脱敏。聚合 pass/fail 或评分分布使用另登记的项目指标 |
| 审计与观测健康 | 拟定审计提交失败、未决 intent、出口丢弃、规则异常、基数溢出、传播拒绝和关联缺失计数；固定原因枚举，不能用异常全文作标签 |

指标使用全量业务计数来源，不从 15% Trace 样本直接计算精确任务成功率。业务计数需要持久化水位/去重；SDK Counter 重启重置与后端 rate 的关系写入部署说明，不能声称任意网络重试下恰好一次导出。

拟定基数策略：每个 instrument、租户资源分区、采集实例的活跃属性组合上限为 10,000，含一个固定 overflow 聚合桶；可用正常槽位最多 9,999。记录 SDK 内存上限，同时在 collector/backend 配置租户总序列配额（包含 instance/resource 及 Histogram buckets），前者不等于后者。

标签先黑名单再白名单，值只允许登记枚举或受限目录（provider/model/tool/status/error_category 等）。trace/span/request/task/workflow/session/user/evidence/raw_url/prompt/异常正文不得成为指标标签，哈希后也不允许。org/project 不天然低基数，不把多个租户合成可被租户读取的 overflow 桶。

新组合超限时，将非租户维度折叠到该分区唯一 overflow 桶，并计量降级；不再增长标签集合。管理态估计器可预警，但 hard limit 要在实际分配时原子执行。例：100 models × 100 tools × 2 statuses = 20,000，单维度都不超限也必须被组合限制拦截。Histogram 额外 bucket 序列数必须加入后端预算。

## 8. 审计查询、授权与导出（Q5）

保留草稿路径 `/api/v1/audit-logs`，另有 `/api/v1/audit-logs/exports` 和 `/{export_id}` 状态查询。冻结的 Runtime `/tasks/.../events` 查询不原地换成此接口。

查询参数沿用草稿 filters：organization/team/project/repository/user/task/trace、event_types、categories、severity、source、时间、关键词、排序、cursor/page_size/include_payload。默认 page_size=50、上限500；起止 UTC 且 start≤end，最大窗口90天，端点包含；event_type 值通过 §5 登记表解析，不接受任意 SQL/动态字段。默认 timestamp DESC，event_id 为稳定 tie-breaker。组织过滤只能缩小当前服务端授权范围。

成功统一为现有 `{code:0,message:"ok",data,trace_id}`，其中 data 为 `{items,pagination:{next_cursor,has_more},meta:{query_id,storage_tier,executed_at}}`；total 不默认全表扫描，可在明确 exact/estimated 语义后扩展。错误沿用 `{code,message,data:null,trace_id}`，不回显原始 cursor、SQL、凭据或敏感搜索文本。

| 条件 | HTTP / 现有业务码 | 是否可重试 |
|---|---|---|
| 无认证 / 无能力或越租户过滤 | 401 / 40301；403 / 40302 | 先重新认证/授权，不能自动跨租户重试 |
| 参数、窗口、签名游标错误 | 422 / 42201 | 修正参数或重新从首页查 |
| cursor 过期、授权/规则版本变化、幂等内容冲突 | 409 / 40901 | 重新发起查询或处理冲突 |
| 不可见或不存在的单项 export/evidence | 404 / 40401 | 不揭示他租户资源存在性 |
| 超导出大小 / 查询限流 | 413 / 40001；429 / 40001 | 缩小范围；按 Retry-After 等待 |
| 后端不可用 / 超时 | 503 / 50301；504 / 50301 | 有界退避，保持查询快照或安全重启 |

以上复用当前 APIErrorCode，不擅加共享枚举。HTTP 细分与前端处理仍是 Q5 的接口变更内容，需要调用方评审。

权限建议采用 `audit.read/audit.export/audit.payload/audit.hold/audit.delete` 独立能力加资源范围，角色只映射能力；G-SEC 最终决定角色映射。Organization Admin 限组织、Team Admin 限团队，Security Auditor 按明确授予范围；Platform Admin 需显式租户范围及审计化提权，不默认通读。查询先在存储侧约束组织和资源，再复核记录范围；payload 另过敏感级别及内容策略，不因 ADMIN 返回秘密。

cursor 使用版本化签名或服务端随机 opaque handle。若采用签名载荷，至少绑定主体、组织、资源授权摘要、filters SHA-256、排序和最后键、提交上界 snapshot_sequence、权限/脱敏版本、签发/过期时间及 key_id；HMAC-SHA256 常量时间验证。Base64 不是加密，载荷不能放关键词原文或内部资源清单。候选 TTL=15分钟；每页重新授权；同一快照排除后到事件并允许调用者新查询获得晚到事件。

查询本身写最小访问审计（query_id、主体、范围摘要、时间、数量和结果），不递归审计内部 append 操作。快照水位在查询访问审计前确定，避免分页被自己的访问记录持续改变。完整性验证访问同样要授权。

导出：POST 支持幂等键；每次最多100,000条及1GiB压缩文件，超过即显式拒绝/拆分，不静默截断。状态 `PENDING → RUNNING → COMPLETED | FAILED | CANCELLED`，到期 `EXPIRED`；`cancel_export(export_id, principal)` 是建议逻辑接口，HTTP 路由在正式契约中登记后才实现。取消先停止后续批次，清理临时对象后确认 CANCELLED。

创建、执行每批和下载都重新授权；撤权立即停用下载并取消剩余批次。候选导出访问有效期24h、临时对象最长7天，下载经受控网关鉴权，不把长效裸对象链接当权限。CSV 做公式注入保护；导出只包含脱敏投影，校验大小、数量及内容 hash。冷层资料统一异步导出，在线查询遇冷层返回明确的使用导出提示，不给不完整200成功；恢复耗时是实测指标，不能承诺对象存储一定60秒可读。

## 9. 告警与 Kill Switch 接口（Q7）

OBS 负责检测、去重、通知、证据与状态展示，SEC 负责风险模式状态机和阻断权限。M0=OBSERVE、M1=READ_ONLY、M2=APPROVALS_REQUIRED，M3/M4/M5 使用 SEC-009 命名；观察期另有字段，不能把 M1 改名为观察。

```text
AlertSignal:
  schema_version, alert_id, organization_id, resource_scope
  rule_id, rule_revision, fingerprint, opened_at, evaluated_at
  severity, confidence, blast_radius_estimate, signal_freshness
  evidence_refs, metric_snapshot_ref, state
MitigationRequest:
  request_id, idempotency_key, alert_id, organization_id, scope
  recommended_mode, matrix_revision, signal_refs, approval_refs
  expected_state_revision, deadline_at
MitigationResult:
  request_id, decision(accepted/rejected/pending/unknown)
  operation_id, effective_mode, state_revision, reason_code
```

以上为候选消息，不新增 Runtime event_type；正式注册经 G-RT/G-SEC 评审。key 建议绑定租户、alert、rule_revision、scope 和目标操作；超时查询 operation_id/幂等键结果，使用同键重发，不新造业务请求。结果只接受经认证的 SEC 控制面响应。

告警状态 `INACTIVE → PENDING → FIRING → ACKNOWLEDGED/RESOLVED`；通知、静默及 mitigation 状态分字段保存。通知成功不代表阻断成功，信号消失不代表可以解除已有保护。规则评估超时或关键指标缺失生成 `NO_DATA/telemetry_blind_spot`，不当作系统健康或授权解除依据。

单一矩阵由安全契约确定，OBS/SEC 草稿冲突项在确认前只产出建议与审计，不自动触发。自动范围同时验证租户数量与连接器作用范围，不能用“只一个连接器”绕过它影响大量租户的风险；实际数字与独立信号要求由 G-SEC 确认。M4/M5 人工 quorum 不可绕过。

禁止用 `current_mode >= target_mode` 判断安全强度：READ_ONLY 与 APPROVALS_REQUIRED 等模式权限并非简单总序。由 SEC 状态机检查允许迁移和有效限制，OBS 不执行降级。M1/M2/M3 的5/15/30分钟仅作为现有安全草稿候选解除窗口，实际解除仍由安全服务验证条件、审计和24h观察规则；OBS 不持有绕过控制面的“到点开锁”定时器。

规则重复触发按租户/资源/rule_revision/fingerprint 去重；通知 429 按 Retry-After，5xx 有界退避、带抖动；消息只发脱敏摘要和受控详情链接。本次未连接或发送 Slack、邮件、PagerDuty。真实触发延迟、送达率和阻断时限在 M2 实测，模拟通知不能作为完成证据。

## 10. 留存、完整性、保全与恢复（Q6/Q8）

留存默认沿用 RT-006/008：以记录生成时间计龄，hot≤30天，冷层默认截止180天；不能迁移一次就再延长180天。OBS 的 warm/cold 是部署层级名称，不自动延长逻辑 TTL。高风险/调查/客户批准的扩展 profile 显式记录有效期限、授权和用途，7年不是全量默认，也不是本文件给出的法律结论。

保留期、Legal Hold、存储 Object Lock、证据引用保护分别建模；None 不再同时代表“未配置”和“无限期保全”。既有永久策略记录迁移前先盘点来源及审批；禁止上线后批量自动清理。孤儿 Trace 可以遵循诊断 profile，关联缺失不得缩短审计或受保全 Evidence 的期限。

拟定完整性方案：

1. 每租户链使用 `chain_id/epoch/sequence`，事务分配单调提交序列并校验前一 hash；唯一约束与幂等键一起解决并发/重试，不能先返回成功再异步排号。
2. 规范化整个不可变事实核心，包括租户/资源、actor、source_event、发生/提交时间、类型/版本、trace/span、脱敏后的 payload、evidence_refs、策略版本；排除可变存储 tier 和查询投影。冻结 UTF-8 编码、键排序、时间格式和数值规则（禁止 NaN/Infinity；精确金额用规范字符串或整数）。具体 canonicalization_version 在实现基线中固定。
3. 用版本/用途前缀及长度明确的编码，对 canonical record 与 previous_hash 求 SHA-256；只哈希 payload 不合格。哈希链能检出相对可信锚点的修改/缺失，不能阻止同权限管理员重写整链。
4. 每1,000条或固定封存窗口生成带计数、区间、首尾 hash 的 Merkle checkpoint，空批不生成根；奇数叶处理固定规则。独立受控签名 key_id 签署根及租户/epoch/范围，写到不同管理权限的锚点存储；保留密钥轮换与验证材料。具体签名算法和锚点部署由 G-SEC 确认，不擅引新依赖。
5. 出口/归档采用 copy → hash/数量校验 → 提交 manifest → 切读 → 策略允许后清理源。迁移失败保留源，重试不改原事件字节及序列。完整性状态区分 VERIFIED/UNANCHORED/INCOMPLETE/FAILED，未锚定不能显示为可信链验证通过。

Legal Hold 的 scope、发起者、审批证据、创建/释放时间及版本通过追加事件记录；支持多个重叠 hold，只有全部解除且 TTL/对象锁均允许才进入删除。删除与 hold 创建使用同一版本栅栏/事务检查，执行各存储分段前重新检查；恢复环境先重放 hold 和删除 manifest 再开放查询。未知保全状态时暂停删除。

删除状态建议 `REQUESTED → APPROVED → EXECUTING → COMPLETED`，分支为 `BLOCKED_BY_HOLD/WAITING_RETENTION/PARTIAL/FAILED/CANCELLED`。双人审批与等待窗口按 G-SEC 确认策略执行。回执逐项列主库、归档、对象版本、索引、缓存、导出副本及备份的处理状态/完成时间/证明引用，不含被删除内容；不可把 tombstone、向量计数变化或仅签名操作请求称为物理删除完成。

若保留了链位置和 hash，删除 manifest 记录被删区间及可信锚点；后续验证明确显示“内容已按策略删除，仅剩承诺与回执”，不能声称仍可逐字验证内容。备份未过期、对象锁未解除、存储服务未确认时为 PARTIAL/WAITING_RETENTION，待实际完成后追加终态；不能改写旧回执。回执与残留摘要本身也纳入敏感级别、访问控制和批准的保留策略。

本设计不引用原稿的具体法规条款解释，不宣称本技术方案自动满足某司法辖区要求。法定期限和删除例外由具备权限的治理流程确认；本轮只定义可执行、可验证的技术状态。

## 11. 验收标准与里程碑汇合

以下是后续实现必须提交的验收用例，**本轮未执行这些新增系统能力**。各项都需给出环境、版本、输入/故障注入、原始结果及修复复测证据。

| ID | 触发条件 → 必须响应 | 责任及真实验证位置 |
|---|---|---|
| AC01 | 合法内部 Context 跨 API/Worker/Tool/恢复 → 关联一致；不可信/全零/畸形 header → 新根且不越权、不抛未处理异常 | O-TRACE；M1/M2 真实链路 |
| AC02 | 默认15%或采样0、Collector宕机 → 必需 intent/outcome 审计仍完整提交；失败 Trace 是否完整如实标记 | O-TRACE+O-AUDIT；M1/M2 |
| AC03 | 同源事件重复、未知版本、异租户 Evidence → 已登记重复只计一次，未知不消费、异租户拒绝，Runtime旧消费者不退化 | O-TRACE/O-AUDIT/E-FEED |
| AC04 | 保护动作审计提交失败、结果未知、进程重启 → 阻止无审计继续执行；查询对账，不重复不可逆副作用 | O-AUDIT+执行器；真实持久化故障测试 |
| AC05 | 默认/FULL/过期/撤权以及跨chunk凭据、深度33、环引用、检测超时 → 凭据始终不输出，失败只保留安全元数据 | O-AUDIT+采集端；实际队列/exporter检查 |
| AC06 | 输入token_count数值和伪装统计字段的secret字符串 → 前者保留、后者拦截；权限提升不旁路脱敏 | O-AUDIT；边界测试 |
| AC07 | 9,999常规组合后再产生新组合、Histogram多bucket、两租户 → 分区不超过10,000、overflow可计量且不串租户，后端配额另受控 | O-METRIC；固定负载+实际后端 |
| AC08 | 一个逻辑模型请求重试两次、usage未知、reasoning为output子集 → attempt正确、未知不记零、total不重复累加；精确成本仍来自账本 | O-METRIC+W-MODEL |
| AC09 | 相同时间的多条记录、晚到事件、cursor篡改/过期/跨主体/撤权 → 排序稳定且快照可复现，非法cursor拒绝，任何页不越权 | O-AUDIT；真实索引与授权存储 |
| AC10 | 导出超限、取消、下载前撤权、CSV公式、冷层不可用 → 明确失败/取消，无未授权文件或不完整成功，无泄密错误正文 | O-AUDIT；真实对象存储 |
| AC11 | 相同告警重发、控制面超时、旧矩阵、无数据、已有更严格限制 → 幂等对账，未知不写成功，不自动解除、不以数字模式比较覆盖 | O-METRIC+S-KILL；M2 |
| AC12 | 修改actor/租户/关联字段、删一条、重排或重写整链 → 本地hash/序列及独立锚点检测；未锚定明确未验证 | O-AUDIT；真实存储权限隔离 |
| AC13 | TTL边界、归档中断、重叠hold与删除竞态 → 期限不刷新、源数据保全、有效hold阻止删除，孤儿审计不提前删除 | O-AUDIT+S-TENANT；M2 |
| AC14 | 备份未清、对象锁未过、删除后恢复旧备份 → 回执不写完成；开放读前重放删除/hold，不复活不可见数据 | O-AUDIT+恢复任务；M2及适用恢复里程碑 |
| AC15 | 满载/弱网/429/超时/重启 → 有界队列和退避、准确丢弃与未决计数；CPU、查询p95、通知/阻断延迟报告实测条件 | 相关模块；M1/M2性能与质量验证 |

M1 汇合实际 API→Runtime→工具/模型链及独立审计、失败/恢复；M2 汇合真实审计存储、指标后端、通知、S-KILL、租户隔离与恢复。O-METRIC 单测通过不能完成 S-KILL 或 M2；O-AUDIT 内存适配通过不能完成留存/删除/不可变验收；G-OBS 文档确认不自动完成 OBS 七项 REQ。

## 12. 本次验证报告与复现

### 12.1 测试项 → 用例 → 结果 → 修复动作

| 测试项 | 用例 / 方法 | 本次结果 | 修复动作或限制 |
|---|---|---|---|
| 台账和范围 | 核对 G-OBS owner/mode、G-RT依赖、相邻任务及工作区 | 领取有效；仅写本文 | 本次不变更共享scope/deps；正式提交前再次校验 |
| 需求与对标 | 七项OBS、相关RT/SEC/EVA/G-MODEL及4个官方来源 | 完成对照，Q1～Q8标出冲突/建议 | 未确认项不写生产实现，不沿用无证据的产品内部实现说法 |
| 既有 Trace/查询基础回归 | 下面pytest命令 | **188 passed，0 failed，0 skipped，2 warnings，0.55s** | 通过的是当前代码，不能覆盖本文新增能力 |
| Trace ID边界探针 | HTTP `is_valid_trace_id('0'*32)` | **发现缺口：返回True** | O-TRACE实施时修复并复测，本轮未修改生产代码 |
| traceparent版本探针 | HTTP `_parse_traceparent('ff-'+合法hexID)` | **发现缺口：返回解析结果** | O-TRACE补版本/信任边界验证与正式回归 |
| 传播器格式探针 | `TracePropagator.extract` 输入32个z的ID且trusted=True | **发现缺口：抛ValidationError** | 实施时统一为安全拒绝提取；本轮保留现状及复现证据 |
| 文档静态检查 | 本地链接、围栏闭合、Q1～Q8和AC01～15覆盖、空白检查 | 待最终校验后补记 | 文档结果不是产品功能验收 |
| 输入文件保全 | OBS/RT文档及相关源代码/测试48文件SHA-256前后比较 | 待最终校验后补记 | 若其他会话并行修改，仅报告差异，不回滚 |
| 新系统真实测试 | OTLP/TLS、PostgreSQL、对象锁、外部锚定、通知、S-KILL、灾备、负载 | **未执行** | 尚未实施；依照AC清单在下游任务及里程碑执行 |
| 生产质量门禁 | 全仓lint/mypy、SAST/SCA/Secret、覆盖率 | **本轮未执行** | 本轮只交设计文档，未宣称生产门禁或任何新增模块通过 |

两条 warning 为现有 Starlette/FastAPI 的 httpx 与 AnyIO API 弃用提示；未更改依赖，不写成已修复。

### 12.2 启动与验证方式

在项目根目录使用现有虚拟环境；本次没有新服务可启动或部署。执行的是现有回归，禁用 pytest 缓存，无 coverage 文件写入：

```powershell
.venv/Scripts/python.exe -X utf8 -m pytest -q -o addopts='' -p no:cacheprovider tests/unit/observability tests/unit/runtime/trace tests/unit/runtime/query tests/integration/runtime/trace tests/unit/api/test_trace_middleware.py
python -X utf8 scripts/task_board.py show G-OBS
```

只读边界探针（均为合成输入，不访问外部服务）：

```python
from src.api.middleware.trace import is_valid_trace_id, _parse_traceparent
from src.runtime.trace.propagation import TracePropagator
print(is_valid_trace_id('0' * 32))  # 当前 True；目标拒绝
print(_parse_traceparent('ff-' + '1'*32 + '-' + '2'*16 + '-01'))  # 当前非空
try:
    TracePropagator().extract({'traceparent': '00-' + 'z'*32 + '-' + '2'*16 + '-01'}, trusted=True)
except Exception as exc:
    print(type(exc).__name__)  # 当前 ValidationError；目标安全拒绝提取
```

### 12.3 交付结论与恢复条件

本文交付的是可确认的 G-OBS 设计、接口候选、官方对标和当前代码检查证据；三个新增探针暴露的产品缺口仍未修复，真实持久化/安全/恢复/性能未验收。不能将188条旧测试通过写成OBS已完成。

下一步需真实用户确认 Q1～Q8（可分组：Q1/Q3/Q4观测语义，Q2/Q5/Q6数据边界，Q7/Q8安全联动与证据），并完成 G-RT 用户验收；随后按台账进入 G-OBS 文档实施。涉及 G-SEC/G-EVA 的共享边界先汇合确认，不能自行修改其他负责人文件。O-* 生产实现仍需各自任务的实施基线与领取，本文不代为批准。

确认要求来自执行手册：“design模式仅允许任务专属方案文档及隔离原型，不改生产代码、正式测试或冻结共享契约。”以及用户规则：“其他实质性冲突需向我确认。”因此本轮提交设计为待确认，不调用 approve-design、accept，不将 G-RT/G-EVA 等任务自动标记完成。
