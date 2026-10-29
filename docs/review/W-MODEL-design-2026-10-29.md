# W-MODEL：OpenAI Responses 单模型接入实施方案

日期：2026-10-29（Asia/Shanghai）；owner：`codex-grt-20261029-01a185ef`；状态：设计交付，待确认实施基线。

## 1. 已批准事项与本次范围

- 用户在本聊天对 [G-MODEL](../development/contracts/model.md) 交付回复“确认”，已通过台账 `accept` 登记契约文档及接口方案验收。G-MODEL 原文件保留交付时快照，最新批准状态以 [台账](../development/task-board.json) 的完成证据为准。
- 用户随后选择“OpenAI Responses API（沿用已核验协议）”作为首个供应商。此选择不指定具体付费模型、账号或价格。
- 已确认权限解释继续适用：已有有效授权/审批范围内可免重复审批；始终经过 Policy Gateway；越界或实质参数变化重新审批。
- 本次交付是实施方案与隔离原型。批准后实现统一网关、OpenAI 适配、旧 ModelClient 兼容适配、流式解析、预算预留/结算、超时取消、验证工具和环境配置说明；W-CODER 负责生产 Coder 装配，M1 负责真实 Issue → PR 汇合验收。

相关依据：[执行手册](../../项目开发执行手册.md)、[迭代规则](../../规则文档/AGENTS.md)、[需求分析](../需求分析报告.md)、[WKR-001](../design-specs/REQ-WKR-001-coder-worker-architecture.md)、[RT-001](../design-specs/REQ-RT-001-core-runtime-entities.md)、[RT-006](../design-specs/REQ-RT-006-Trace-传播和审计关联.md)、[RT-007](../design-specs/REQ-RT-007-idempotency-key.md)、[REL-002](../design-specs/REQ-REL-002-retry-policy.md)、[SEC-006](../design-specs/REQ-SEC-006-prompt-injection-malicious-repo-protection.md)。本方案不修改这些共享契约。

目标：一个可信任务上下文能通过明确配置的单模型得到完整、可验证的动作提议或完成摘要；预算、失败、取消及秘密边界可观察，并保持旧调用接口可用。前端、自动模型路由、供应商托管工具和多主机部署不在本次范围。

## 2. 现状、对标与选择

现有 `src/workers/coder/model_client.py` 仅有 `complete(messages, tools)` 和 Mock；`ModelResponse` 要求工具提议/完成摘要二选一。现有 Coder 把工具结果作为 user 文本回传；ReAct 有整体截止时间和使用量累计，但未传入模型客户端。Runtime `Budget` 已使用 `max_cost_microusd`，本方案统一复用微美元，不新增币种换算体系。G-MODEL 交付时的 64 项局部测试使用 Mock 模型，不能视为真实供应商证据。

2026-10-29 官方资料核验：

| 来源及事实 | 优点 | 本方案选择/限制 |
|---|---|---|
| [Responses 迁移指南](https://developers.openai.com/api/docs/guides/migrate-to-responses)：支持 `store:false`、typed output 和工具调用配对 | 供应商协议职责明确 | 固定 `/v1/responses`，不使用 Conversations/后台模式或服务器会话延续；每轮显式输入历史 |
| [流式响应](https://developers.openai.com/api/docs/guides/streaming-responses)：SSE 区分增量与终态 | 能提供增量进度及失败状态 | 只在完整 completed 后产生可执行提议；断流显式失败 |
| [结构化输出](https://developers.openai.com/api/docs/guides/structured-outputs)：`text.format` 支持 JSON Schema；需处理拒绝和不完整输出 | 降低自由文本解析歧义 | 旧接口采用结构化动作提议模式，正文仍做本地验证；原生函数模式只接受完整 call_id 历史 |
| [数据控制](https://developers.openai.com/api/docs/guides/your-data)：应用状态与滥用监测留存分别管理 | 能明确数据边界 | `store:false` 不宣传为零留存；生产仓库数据需经过已批准的数据策略，真实冒烟仅用合成输入 |
| [jsonschema 官方项目](https://pypi.org/project/jsonschema/)与[引用解析文档](https://python-jsonschema.readthedocs.io/en/stable/referencing/)：4.26.0，MIT；Registry 默认不自动抓取远程引用 | 可完整验证工具参数，避免自造不完整校验器 | 建议新增精确锁定依赖 `jsonschema==4.26.0`，仅允许本地 Schema 资源，拒绝远程引用 |

本方案不采用产品内部实现推断；官方资料只支持表中的公开行为。OpenAI SDK 不新增，复用现有 `httpx==0.27.2`；Pydantic 沿用当前版本。jsonschema 的新增、传递依赖许可证与实际 SCA 结果在实施前核验；当前仓库 README 的 License 为“待定”，不能仅凭依赖为 MIT 宣称整仓已完成许可审计。此次批准限定为内部开发使用并保留依赖许可信息，正式分发前仍须确定项目许可证及完成兼容核查。

## 3. 模块与文件边界

当前台账允许的实现路径为 `src/workers/common/model_client.py` 和 `tests/integration/model`。为避免将传输、账本与类型堆进一个文件，提出以下**待批准的范围扩展**；设计阶段不改这些路径，批准后使用台账脚本 locked/read/validate/write 在同一把锁内更新本任务范围，并重新检查冲突再领取 implementation。

| 路径 | 职责 |
|---|---|
| `src/workers/common/model_client.py` | 统一客户端导出、旧 ModelClient 兼容适配；不修改旧 Coder 文件 |
| `src/workers/common/model_gateway/`、`src/workers/common/__init__.py` | types/config、OpenAI transport、SSE decoder、gateway、budget ledger；模块按实际逻辑建立，不创建空框架 |
| `tests/unit/workers/model_gateway/` | 输入/Schema/终态/计费/取消/异常确定性测试 |
| `tests/integration/model/` | 本地 HTTP 故障服务、SQLite 双进程及真实供应商冒烟；专属 `.env.example`、运行说明和验证报告 |
| `pyproject.toml`、`requirements.txt` | 仅新增 jsonschema 精确版本及必要的一致性更新；保留已有未提交修改 |
| `docs/review/W-MODEL-design-2026-10-29.md`、`docs/development/prototypes/W-MODEL/` | 本任务设计和隔离试验；不被生产代码导入 |

共享 `.env.example`、API 主入口、W-CODER、Runtime 事件 Schema 和其他任务文件不在本次写入范围。已有用户修改须逐段保留；依赖文件若被其他任务占用，先交接该文件边界，不覆盖。G-MODEL 已完成；W-CODER/G-HAR/G-RT 的状态不因本次推进改变。

## 4. 接口落地

沿用已确认的 `complete(ModelRequest) -> ModelResult` 与 `stream(ModelRequest) -> AsyncIterator[ModelEvent]`。complete 复用同一流状态机聚合，避免两套失败语义。类型版本初始为 `model.request.v1`、`model.result.v1`、`model.event.v1`；它们是网关内部 DTO，不是 RT 事件版本。

| 结构 | 实施约束 |
|---|---|
| RequestContext | 可信调用方提供 org/project/repository/task/workflow/worker/step、trace/span、request_id、attempt、UTC deadline、预算账户引用和取消令牌；缺失拒绝，不能从模型消息读取 |
| ModelRequest | context + profile_ref + typed messages + 已批准 tools/toolset_version + max_output_tokens；强类型、额外字段拒绝、长度/字节限制；模型无权修改 profile、身份、预算 |
| ModelProfile | 固定 provider=`openai`、明确 model_id/model_revision、能力声明、context_window、输入/输出微美元价格及 pricing_version/有效期；配置缺项或到期拒绝发送，无默认“最新模型”别名替换 |
| ModelResult | request/provider request/model 标识、finish_reason、usage；成功结果恰好一项 tool_proposal 或非空 final_summary；拒绝、截断、usage 不完整保持非成功结果 |
| ModelEvent | request_id/attempt/sequence/type + 有界数据；started、text_delta、tool_arguments_delta、usage、completed/failed/cancelled/timed_out；每个 attempt 至多一个终态 |
| Failure | G-MODEL 已确认错误类别、可重试性建议、脱敏 request 标识及 retry_after；不给用户输出原始服务器异常、提示词或 HTTP Authorization |

适配器实现旧 `complete(messages, tools)`；构造时注入 `context_provider` 和网关。每次调用读取真实剩余配额及当前 deadline，缺上下文拒绝生产调用。usage 先在微美元账本累计，再按累计向上取整差额转成旧 `cost_cents`，避免逐轮丢失小额成本；`thought` 返回空值。旧 Mock 类型和旧接口保持可用。

两种输入模式明确隔离：

- **旧接口兼容模式**：采用 Responses 结构化输出生成 `{kind, tool_name, arguments_json, final_summary}`，四个字段必有、不允许未知字段；非当前分支字段为 null。`arguments_json` 经大小/深度限制、拒绝重复键/NaN 的 JSON 解析后，使用原始 ToolSpec Schema 完整校验。工具只有提议能力，返回值并非原生 function call，不编造 provider call_id；本地 proposal_id 使用独立命名空间。
- **原生函数模式**：使用供应商 function tools，`parallel_tool_calls=false`，只接受结构化历史及真实 call_id 配对。对不满足供应商 strict 子集的已批准 Schema 显式设 `strict:false`，保留原 Schema 的必填/可选语义并在本地完整校验；不能为迎合 strict 将可选参数偷偷改为必填。响应同时包含最终摘要与工具调用，或多工具调用时拒绝。需要供应商额外私有推理续接项的配置不纳入此 MVP，返回能力不支持，不悄悄丢弃必要历史。

Schema 的本地 `$ref` 只在注册的版本化资源内解析；禁用网络检索。JSON Schema 的注解型 format 不自动当作断言；如工具要求格式校验，能力表必须声明支持并测试，未知断言不能忽略。工具数、Schema 字节与深度均有上限，注册时校验以避免执行期无界解析。

## 5. 传输、流式、取消与重试

HTTP 固定 `https://api.openai.com/v1/responses`；TLS 校验开启，重定向关闭，不继承环境代理（`trust_env=False`），不接受请求内容覆盖 base URL。凭据从服务端环境 `OPENAI_API_KEY` 读取，使用 SecretStr/受控提供者，禁止进入 DTO、日志及账本。mock transport 只由测试注入；生产配置不得选择回环/任意域名。

默认参数建议：connect 5s、首个有效业务事件 30s、read-idle 15s、total 120s，全部再受任务剩余 deadline 限制；每次锁等待也受 deadline 限制。SSE keepalive/comment 不重置首业务事件或总截止时间。默认 body ≤256 KiB、单事件 ≤256 KiB、完整响应 ≤2 MiB、事件数 ≤10,000、工具 ≤32、Schema 深度 ≤32、max_output_tokens=2048（且不超过 profile 能力）。这些是部署初值，真实验证失败时只能在批准的边界内调整并留证据。

SSE 在字节层有界累积，再按事件分隔解析，覆盖 CRLF/LF、跨块 UTF-8、多行 data、注释/空块、重复/乱序和错误事件。未知事件只有明确列入可忽略的纯元数据事件才能忽略；可能影响结果完整性的未知事件失败。部分 JSON 可供内部进度，但不产生 Action。completed 后校验完整结果和 usage、完成结算后才能向调用方暴露成功终态。

采用独立读取任务和有界队列（32 项）监控 total deadline；消费者停止/关闭/取消时关闭响应及读取任务。队列满失败并保留未知费用，不无限等待慢消费者。显式取消信号在发送前、每次响应处理和结果返回前检查；调用协程被取消时先在有界清理段记录账本状态、关闭连接，再传播 CancelledError；已取消协程无法再 yield 事件，终态以账本记录为准，不能为了发送 cancelled 事件吞掉取消。

MVP 默认**单次网络尝试**，向上返回规范错误和 retry_after；避免在 REL-002/003 尚未完成生产装配时另建自动重试引擎。这符合已确认契约中“仅在批准策略允许时重试”的边界。任何重试必须显式新 attempt、重新原子预留预算，并受总截止时间限制；不实施自动模型切换。429/5xx 不伪装成功，401/403/无权限/无预算/非法输出不重试。

选择前台 `store:false`，不假设支持远端取消；本地断开后供应商是否继续计费可能未知。迟到响应不触发工具；失败、超时和取消不得自动重发。

## 6. 预算账本：本机 MVP 的具体方案

新增轻量 BudgetLedger 接口及标准库 SQLite 实现，**只服务本机网关的模型预算**，不代替项目 PostgreSQL 事件/Checkpoint/Action 幂等账本。实例、进程共用同一个明确配置的本机绝对 DB 路径；不支持网络共享盘或多机器各一份副本。配置声明多主机时拒绝启用本实现。转入多主机或 M1 的 PostgreSQL 持久化汇合前必须完成 BudgetLedger 的 PostgreSQL 适配/迁移验收；此项明确保留在后续集成清单，不能把本机试验外推为集群隔离完成。

数据最小集：

| 表 | 主键/字段 | 不变量 |
|---|---|---|
| budget_accounts | org_id+task_id；scope_digest、limit tokens/microusd、settled、reserved、locked_reason、version | 限额只由可信任务初始化一次；普通调用不能提高；同 task 不同 scope 拒绝 |
| reservations | org_id+task_id+request_id+attempt；request_digest、reserved/actual tokens/cost、pricing_version、status、provider_request_id、timestamps | 相同标识不同摘要冲突；相同标识绝不二次发送；成功、未知、失败可区分 |

使用事务 `BEGIN IMMEDIATE` 和唯一约束进行预留及状态更新；账本连接显式关闭，阻塞 DB 操作移出事件循环并设置有限锁等待。参数绑定 SQL，不记录 prompt、工具参数原文、凭据或内部思维链。

状态：RESERVED（发送前已持久化）→ DISPATCHED（发网络前持久化）→ SETTLED；未发送可转 RELEASED；DISPATCHED 后崩溃/断流/无 usage 转 UNKNOWN。进程重启后 RESERVED/DISPATCHED 均保守保留预留，不能仅因进程消失释放；同 request 不重发，调用方收到待核对状态。UNKNOWN 锁住该预算账户的新计费调用，直到可信费用核对或明确人工处理，不能以新 request_id 绕过。

预留策略：不用字符数假装精确 token 数，也不增加 tokenizer 依赖。首版按已核验 profile 的模型输入上下文上限和输出 token 上限保守预留；缓存命中不预先折扣。此方案会拒绝部分实际可能低成本的请求，优先保证有限预算，后续可用供应商计数或经验证 tokenizer 改进。profile 不提供可信容量/价格时拒绝发送。以微美元整数和向上取整计算，收到 usage 后按版本化标准价格结算；reasoning/cached 子项不重复加入 total。供应商实际费用最终以账单为准，当前为保守额度计量，不承诺是精确账单。

费用大于预留或 token 超出批准边界时记录实际使用并锁定账户，不能把账本做成负数后继续调用。usage 未知、价格失效或响应内容不完整时不返回成功；不能填 0。取消/失败只有明确证明未发送，或可信结算证明无费用时才释放预留。

## 7. 配置与验证入口

实施时在本任务 `tests/integration/model/.env.example` 交付无密钥值模板；独立文档说明生产装配读取配置，不直接改共享 API 配置。关键项：`OPENAI_API_KEY`、`AI_MODEL_ID`、`AI_MODEL_REVISION`、`AI_MODEL_CONTEXT_WINDOW`、`AI_MODEL_PRICE_INPUT_MICROUSD_PER_MTOKEN`、`AI_MODEL_PRICE_OUTPUT_MICROUSD_PER_MTOKEN`、`AI_MODEL_PRICING_VERSION`、`AI_MODEL_PRICING_VALID_UNTIL`、`AI_MODEL_BUDGET_DB`、有限任务 token/microusd 预算及 deadline。

模型 ID 与价格无需现在选择；按用户账号权限配置，真实冒烟前核验能力和当前价格。缺密钥只报告缺失变量名，不读取输出其值。真实测试必须显式启用，提供有限预算，使用合成任务/只读虚拟工具，禁止发送仓库源码或真实秘密；缺配置时准确记为“未执行/未验收”，不作为绿色交付。

实施验证命令预期（路径将在实施阶段创建，当前不可视为已有测试）：

```powershell
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m mypy src
.venv/Scripts/python.exe scripts/security_gate.py --output-dir .security-reports/W-MODEL
.venv/Scripts/python.exe -m pytest tests/unit/workers/model_gateway tests/integration/model -q
.venv/Scripts/python.exe -m pytest --cov=src --cov-branch --cov-report=term-missing
```

公开接口和新增边界触发全量回归，单独报告真实模型执行情况、Harness 局部契约、故障注入与总体/核心覆盖；预算扣减、权限闸门和审计写入关键方法按项目更严标准验证。安全扫描结果不能沿用上轮记录。

## 8. 可观察验收与实施顺序

| 项 | 条件 → 必须响应 | 验证证据 |
|---|---|---|
| A1 主链 | 合法上下文、配置及足够预算 → 一次真实 API 调用，返回已验证提议/摘要及非零或明确实际 usage | 真实模型冒烟、provider request ID 脱敏摘要；实际工具执行不属于网关 |
| A2 兼容 | 旧消息/ToolSpec 调用 → 返回旧 ModelResponse；原生模式错误 call_id → 拒绝 | 原 64 项回归 + adapter 测试；不修改旧接口 |
| A3 输出 | 非法/重复键/NaN/深度超限/不符合工具 Schema/多调用/拒绝/截断 → 无工具执行且明确失败 | 参数化负向与 Schema 引用无网络验证 |
| A4 流与超时 | UTF-8 分片/多行 SSE/错误/无终态/乱序/持续 keepalive → 正确聚合或有界失败 | 本地真实 HTTP 分块服务、可注入时钟；不靠长 sleep |
| A5 取消 | 发前/流中/结算竞态取消、关闭迭代器、慢消费者 → 本地连接/任务释放，保留必要费用，零后续动作 | 资源计数、迟到响应、端口连接、终态次数 |
| A6 预算 | 双进程竞争/同键重复或异参/未知费用/零额度/过期价格 → 原子拒绝或一次预留；重启不放大额度 | SQLite 真实进程、故障点注入、重开与租户隔离 |
| A7 错误 | 429/5xx/401/403/坏 JSON/超大响应 → 正确分类、无自动重试、诊断无秘密 | 请求次数与日志/异常内容断言 |
| A8 安全 | 伪造 endpoint/身份/工具名/远程 Schema ref/提示注入 → 无额外出口或执行权限 | 本地拒绝测试与真实 SAST/SCA/Secret |
| A9 使用范围 | 多主机配置或缺完整 profile → fail-closed；费用超预留 → 锁定并报告 | 边界配置和异常 usage 测试 |

实施顺序：①确认本方案及写入边界，领取 implementation；②最小完整请求→额度预留→响应校验→结算→旧适配器链路；③SSE、取消/超时和异常；④本地 HTTP/数据库恢复验证；⑤真实合成冒烟；⑥全量/静态/安全/覆盖门禁及交付。真实模型不可用时保留未验收项，不能把 Mock 路径标记整包完成。

## 9. 本轮设计验证报告

隔离原型：[budget_probe.py](../development/prototypes/W-MODEL/budget_probe.py)。不被 src 导入，只使用标准库和临时数据库；不调用模型，不访问凭据。

| 测试项 | 用例 | 结果 | 修复动作/限制 |
|---|---|---|---|
| 预算原型首次运行 | SQLite 事务、两个真实进程竞争、临时目录清理 | 首跑失败：Windows 文件被占用，连接 context manager 未关闭连接 | 改为显式 closing；保留事务上下文；未改生产代码 |
| 原型复测 | 竞争唯一成功、重开预留、同请求不二扣、异额冲突、租户同键独立、UNKNOWN 保留、回滚/零额度边界 | 最终 7/7 通过；0.188s | 仅证明该隔离事务原型；未覆盖真实计费、突然断电、网络共享盘或生产授权 |
| 文档链接、路径冲突 | 本文件相对链接；拟新增范围与所有占用任务比对；owner/mode 检查 | 12/12 本地链接通过；未发现与占用任务的路径重叠；G-MODEL 已完成、W-MODEL 为本 owner 的 design | 检查时快照，实施领取前必须复核；依赖文件已有他人未提交修改，须逐段保留；本轮不修改范围或生产文件 |
| 原型静态检查 | `.venv/Scripts/python.exe -m ruff check docs/development/prototypes/W-MODEL/budget_probe.py` | 首次 2 条 E501；格式调整后 0 诊断 | 修复长行，重新运行原型仍 7/7 通过 |
| 首跑残留清理 | 删除首次失败原型留下的临时 budget.sqlite3 和空目录 | 自动审批审查以 `blocked by policy` 拒绝执行 | 未绕过限制；残留在 `C:/Users/93478/AppData/Local/Temp/w-model-budget-probe-qt0zbyfx`，仅含合成整数预算，无凭据或仓库内容；后续成功运行的临时目录已正常自动清理 |
| 真实 API、完整测试、SAST/SCA/Secret、覆盖率 | 实施前无生产变更 | 本轮未执行 | 本轮不声称生产门禁通过；上轮 64 项结果仅作历史证据 |

复核原型：`.venv/Scripts/python.exe -X utf8 docs/development/prototypes/W-MODEL/budget_probe.py`。

本轮提出的具体新增决策：本机 SQLite 预算账本及多主机/M1 前迁移限制；新增 jsonschema 生产依赖；扩展为职责分离的模块与测试路径；上述超时/容量初值和默认单次网络尝试。用户批准本方案后视为 W-MODEL 的限定实施基线，不再重复请求上述事项。供应商选择、G-MODEL 接口及审批限定解释已经确认，不在待批范围内。
