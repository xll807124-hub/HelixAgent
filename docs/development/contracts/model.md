# G-MODEL 模型网关契约评审方案

日期：2026-10-29（Asia/Shanghai）。负责人：`codex-grt-20261029-01a185ef`。
范围：仅本文件及脚本管理的台账记录；不修改生产代码、测试、依赖或冻结契约。本文区分已实现接口与建议接口，新增接口和 W-MODEL 实施基线尚待用户确认。G-* 的 implementation 模式仅授权契约文档交付。

## 1. 需求、现状和本轮计划

依据：[执行手册](../../../项目开发执行手册.md)、[需求分析报告](../../需求分析报告.md)、[WKR-001](../../design-specs/REQ-WKR-001-coder-worker-architecture.md)、[RT-001](../../design-specs/REQ-RT-001-core-runtime-entities.md)、[RT-006](../../design-specs/REQ-RT-006-Trace-传播和审计关联.md)、[RT-007](../../design-specs/REQ-RT-007-idempotency-key.md)、[REL-002](../../design-specs/REQ-REL-002-retry-policy.md)、[REL-003](../../design-specs/REQ-REL-003-retry-decision-engine.md)、[SEC-006](../../design-specs/REQ-SEC-006-prompt-injection-malicious-repo-protection.md)。designed 文档不因被引用自动冻结；历史 WKR implemented 标记不能替代实时台账或真实模型验收。

目标：为单模型 MVP 明确供应商无关的输入、输出、流式响应、资源预算、失败及取消边界，兼容现有 Coder；后续多模型扩展保持 Worker 接口稳定。

计划：读取既有接口和消费者 → 官方对标 → 形成兼容方案与安全决议 → 运行现有 Coder/ReAct 测试和文档检查 → 提交本工作包待验收。后续新增 SDK、配置、正式测试及生产适配器另由 W-MODEL 方案批准后实施。

现有代码核对：

| 对象 | 已存在接口/行为 | 剩余缺口 |
|---|---|---|
| `src/workers/coder/model_client.py::ModelClient` | `async complete(messages: Sequence[ModelMessage], tools: Sequence[ToolSpec]) -> ModelResponse` | 无 request context、截止时间、取消句柄或 stream 接口；只有 MockModelClient |
| ModelMessage/ToolSpec/ToolCall | role 为 system/user/assistant；content 为字符串；工具含 name/description/input_schema；调用含 name/arguments | 缺 provider call_id、结构化工具结果与多调用表示；不能把供应商原生工具历史直接塞入现有模型 |
| ModelResponse | `thought=""`、tool_call、final_summary、usage；校验工具提议与完成摘要恰好二选一 | 无拒绝、截断、流失败及 usage 未知状态；不能将任意供应商文本自动当作完成 |
| ModelUsage | 非负整数 tokens、cost_cents，默认 0 | 缺输入/输出拆分、币种、定价版本、已知/估算标识；默认 0 不代表真实零费用 |
| `src/workers/coder/worker.py::_reason` | 调用旧 complete，累加返回 usage，将工具输出作为 user 消息传回 | Observation 有预算字段，但调用没有传递预算/截止时间；模型调用与工具结果尚无原生 call_id 关联 |
| `src/workers/react_loop/loop.py` | 回调通过 wait_for 受剩余时间约束；有 token/成本累计 | observation.budget 当前含配置上限，consumed 单独存在，不能把 budget 直接解释为剩余额度；缺并发调用前原子预留 |
| `src/workers/coder/action_builder.py` | 工具白名单、Action 构造和资源推导 | 模型调用 ID 不能替代 Action ID/幂等意图；现有自定义哈希键与 RT-007 的统一闭环需 W-CODER/R-IDEM 评审 |
| `tests/integration/test_coder_e2e.py` | 真实 Git/工具 + MockModelClient 的局部集成 | 不证明真实模型、供应商取消/费用或真实远端 PR 闭环 |

未发现已装配的统一模型网关；现有依赖有 httpx/aiohttp，无供应商 SDK 的生产声明。本轮不新增依赖、不选择模型或填写价格。

## 2. 官方对标与设计判断

来源访问日期均为 2026-10-29。只采用官方公开 API 行为，不推断厂商内部架构。

| 已验证事实与来源 | 优点 | 本项目借鉴/规避（建议） |
|---|---|---|
| [OpenAI 流式响应](https://developers.openai.com/api/docs/guides/streaming-responses)使用 SSE 和带类型的生命周期/增量/完成/错误事件 | 能区分展示中的增量与完整响应 | 归一化事件后再交给消费者；收到增量不能视作模型成功；传输断开不能伪造 completed |
| [OpenAI Function calling](https://developers.openai.com/api/docs/guides/function-calling)用 call_id 关联调用与结果，并可通过 parallel_tool_calls=false 限制每轮最多一个工具调用 | 调用配对明确，适合受控工具执行 | MVP 限制一次提议，保留 call_id 映射；多调用不静默取第一项；即便供应商提供 Schema 约束，本地仍校验并授权 |

上述示例参数不代表所有供应商支持相同功能。供应商能力必须显式声明，不能以“兼容 OpenAI”名称跳过协议验证。

## 3. 接口方案（建议 v1，未冻结、未实施）

保留旧 `ModelClient.complete(messages, tools)` 和 Mock 接口。新增网关接口由兼容适配器提供；不向旧接口强塞必填参数，不全仓替换历史类型。

建议接口：`complete(request: ModelRequest) -> ModelResult`；`stream(request: ModelRequest) -> AsyncIterator[ModelEvent]`。调用方通过任务取消令牌/协程取消终止活动调用；同一请求不同时消费 complete 与 stream。旧 Coder 使用适配器聚合完整结果再生成现有 ModelResponse。生产装配时必须注入可信调用上下文，不能从提示词或模型输出反推身份。

| 建议结构 | 必要字段及约束 |
|---|---|
| ModelRequest | schema_version、request_id、attempt、organization/project/repository/task/workflow/worker/step 坐标、trace_id/span_id；messages、受批准 tools/toolset_version、model_profile_ref、deadline_at（UTC）、remaining token/cost 配额、max_output_tokens、配置化响应字节/事件数上限 |
| 消息项 | system/user/assistant/tool 等有类型消息；文本和工具结果分开；工具结果含 call_id；外部内容来源/可信度独立标记，不能提升为 system 指令；仅文本 MVP，不暗中接受多模态输入 |
| 模型配置 | provider/model/version 引用、能力声明、固定服务端 endpoint 和 credential_ref；供应商专有参数只允许经校验的扩展，模型/用户内容不得任意指定 endpoint 或凭据 |
| ModelResult | schema_version、request_id、provider_request_id、provider/model 标识、finish_reason、usage；成功结果为 tool_proposal 或 final_summary，二者恰好一个；拒绝/截断通过显式非成功结果表达，不能伪装成 final_summary |
| ToolProposal | call_id、工具名称、完整 JSON object 参数、tool_schema_version；每轮至多一项；call_id 只用于会话配对，Action 及幂等键仍由 Runtime 创建 |
| Usage | input/output/total tokens（未知可为 null）、估算或实际标记、金额整数最小结算单位及 currency、pricing_version、provider_request_id；不能把未知填零 |
| ModelFailure | 规范错误类别、request_id、attempt、可脱敏诊断、retry_after（如有）、已收到输出/usage 是否完整；不得携带密钥、完整提示词或原始不可信异常正文 |

兼容适配规则：

1. 原调用 messages/tools 内容保持，新增上下文由可信装配层提供。旧 Coder 尚无 repository_id 等完整坐标时不能使用 org/task 代填；W-CODER 方案需明确上下文来源。
2. 原生工具模式由调用项与结果项按 call_id 配对；旧 user 文本历史只能采用显式结构化输出模式，不能假造供应商 call_id 或丢掉必要会话项。两种模式须按模型能力选择并测试，不混用历史。
3. 多调用、未知工具、非 object 参数、非法 JSON、超长字段或同时出现完成和调用均拒绝为输出错误；不能截取第一项、容错执行或自动降级自由文本。
4. `thought` 为兼容字段，适配器默认空值，最多存放经批准的简短可公开摘要；不请求、不存储或导出模型内部思维链。Worker 当前会把 thought 加入历史，须防止接入私有推理内容。
5. usage 转旧整数 cents 时，币种固定由部署策略明确，先在更细精度账本累计再保守换算，避免每轮舍入丢失成本。未知 usage 不生成零值成功；预算核对前禁止新的计费调用。
6. 多模型扩展通过 profile/能力/adapter 增加，旧 Worker 签名不变；不支持工具、流或上下文容量时返回能力错误。自动切换模型、价格策略和质量路由归 A-ROUTE，不能悄悄启用。

## 4. 流式状态、预算、取消和异常

建议状态：CREATED → RESERVED → IN_FLIGHT → STREAMING → COMPLETED；任一非终态可转 FAILED/CANCELLED/TIMED_OUT；未发出网络请求前预算不足进入 REJECTED。此为调用状态，不新增或替换 RT-002 的 Task/Action 状态。写入 Runtime 事件时须复用批准的事件 Schema，不能直接发明冻结事件类型。

建议 ModelEvent 公共字段为 schema_version、request_id、attempt、单次尝试内递增 sequence、type；类型为 started、text_delta、tool_arguments_delta、usage、completed、failed、cancelled、timed_out。终态只产生一次，终态后不再产生可执行结果；complete 聚合与 stream 成功终态得到同等结果。

工具参数仅在完整成功响应终态后组装、解析并按本地工具 Schema 校验，再生成 Action 经 Policy Gateway 执行。任意 partial、截断或失败不执行工具。供应商 provider_request_id/call_id 不可信，仅作关联；不授予权限。限制缓冲区字节数和单次事件数，慢消费者使用有界队列；溢出停止调用并报显式错误，不丢掉工具参数后继续执行。

超时：部署配置须提供 connect、first-byte、read-idle、total 上限，执行取各上限与任务剩余 deadline 的最小值。具体数值属于 W-MODEL 实施方案，需经用例验证；禁止以客户端默认无限等待代替。读取到增量不能无限延长 total deadline。

取消：检查任务取消及 Kill Switch 信号，撤销本地消费/重试/后续 Action，关闭连接并执行 finally 资源清理；迟到响应不触发动作。本地关闭流不保证供应商停止生成或免收费用；有远端取消能力时按能力调用，无能力时记录远端状态未知和待费用核对。恢复从已确认结果继续，不把半段工具参数写成可执行检查点。

预算：发请求前，按输入计数/安全估算、输出上限和版本化价格预留额度；并行调用使用原子配额预留。剩余为任务上限减已结算减在途预留，不能只读取旧 budget 字典。每次网络尝试都计入费用与时间预算；失败、超时和取消存在未知费用时保留相应预留并核对，不能立即全部释放。无有效定价/有限预算时拒绝新计费调用，不能把零值 usage 当作免费。输出 token 限制不能单独作为精确费用上限承诺。

| 规范失败建议 | 自动重试边界 |
|---|---|
| INVALID_REQUEST/UNSUPPORTED_CAPABILITY/OUTPUT_INVALID/REFUSAL | 不自动重试；模型修复输出须作为显式新请求并计入预算 |
| AUTHENTICATION/PERMISSION/POLICY_DENIED/BUDGET_EXCEEDED | 不自动重试，不降级放权或切换未经批准凭据 |
| RATE_LIMIT/TRANSIENT_NETWORK/PROVIDER_UNAVAILABLE | 仅在 REL 策略允许、总 deadline/配额足够时有界重试，遵守 Retry-After；SDK 与网关只能有一个重试所有者 |
| TIMEOUT/STREAM_INTERRUPTED/CANCELLED | 不将部分输出当成功；取消不自动重试；超时/中断按费用与响应状态核对后由显式策略决定，不能重放已执行工具 |

重试次数与退避采用 REL-002/003 批准后的策略；本文件不自行冻结新默认次数。网关内重试不执行工具，所有计费尝试有独立 attempt 和关联 request_id；Action 重试仍遵循 RT-007，不能把模型重试当作副作用重试。

## 5. 安全、权限和用户决议

凭据仅由环境/密钥服务在适配器边界读取，request 中保存引用；不放入消息、日志、前端或检查点。服务端配置 endpoint，限制出口及重定向，不接受模型提供的 URL 作为供应商地址。供应商输入需遵守组织数据出境/保留策略，未知策略拒绝发送；故障日志仅保留脱敏标识及计量元数据。

外部仓库内容、工具输出、模型工具提议均为不可信数据；网关不能直接执行供应商内置 Shell/计算机/MCP 工具。MVP 仅允许本项目受控函数提议，执行仍由 Action → Policy Gateway → Tool/Sandbox 链路承担。供应商 Schema 约束不能替代本地输入校验、授权和审批。对照 SEC-006 防注入、SEC-003 工具误用、SEC-005 凭据、RT-006 审计及 SEC-009 外部中止边界。

**真实用户确认记录（2026-10-29，本聊天）**：针对 WKR-001“任务分支内高风险操作自动通过，无需外部审批”的歧义，用户选择“采用上述限定解释（推荐）”。所确认内容为：**仅在已有有效授权和审批范围内免重复审批，始终经过 Policy Gateway，越界或实质参数变化重新审批。** 此决议直接沿用，不重复询问；本轮仅在本专属文档记录，不越权修改 WKR 原文或安全模块。它不批准本文其他新增接口或 W-MODEL 生产实现。

## 6. 影响面、依赖和实施准入

| 工作包/消费者 | 需要明确的衔接 |
|---|---|
| W-MODEL | 选定单一 provider/model、传输方式、端点/凭据策略、能力与 timeout/容量配置；优先复用现有 HTTP 依赖，新增 SDK 先确认；实现 adapter、错误映射和协议验证 |
| W-CODER/G-HAR | 可信调用坐标、剩余预算/截止时间传播、完整工具结果历史和适配器装配；不能只新增客户端后称真实闭环完成 |
| G-RT/R-IDEM | request_id、provider call_id、Action ID 和逻辑副作用意图分开；恢复与事件/Checkpoint 版本对齐；G-RT 当前待验收，本文不当作已完成依赖 |
| G-SEC/S-RBAC/S-CRED | 凭据/出口、审批和真实授权；按本节用户决议处理 WKR 旧表述 |
| R-FAIL/R-RETRY/G-OBS | 规范错误到失败分类、重试预算及脱敏审计关联；不能用未冻结的假定映射强迫调用方改变 |
| E-SCORE/A-ROUTE/M1 | 模型质量和回归分开评价；后续路由优化，真实模型到 PR、暂停/恢复/失败汇合验证 |

下游写入路径以台账为准；本文件不扩展 W-MODEL/W-CODER 范围。接口迁移需先新增类型/adapter及旧接口兼容用例，再修改装配消费者，最后真实联调；不删除旧 Mock 路径。跨团队共享字段变更须先确认。

**待用户确认的具体方案**：保留旧 ModelClient 的适配器迁移；本文件 ModelRequest/Result/Event/Failure 与单工具 MVP 语义；预算预留、未知费用核对和取消边界。供应商、模型、SDK及具体配置在 W-MODEL 方案确认，本文未指定。G-MODEL 验收不等于 W-MODEL 自动取得实施基线。

## 7. 验收标准和测试清单

以下用例为后续实现验收要求，不能把本轮设计检查写成这些能力通过。

| 编号 | 触发条件 → 必须响应 | 验证方式/归属 |
|---|---|---|
| M01 | 原 Coder/Mock 接口调用 → 行为保持；新 complete 与 stream 聚合 → 同等完整结果 | 旧用例回归 + adapter 契约；W-MODEL/W-CODER |
| M02 | 非法 JSON、未知工具、多调用、同时完成和调用、超长输出 → 拒绝且工具执行次数为零 | 确定性供应商响应 fixture；W-MODEL |
| M03 | 参数分片跨网络块、多字节字符、重复/乱序/缺失终态 → 正确组装或显式失败，无部分执行 | 流式传输故障服务；W-MODEL |
| M04 | 连接/首字节/空闲/总超时或弱网中断 → 有界退出、释放本地资源、费用未知可追踪 | 可控 HTTP 服务 + deadline；W-MODEL |
| M05 | 发前/流中/完成竞态时取消，或 Kill Switch 生效 → 后续动作零执行，迟到响应丢弃，终态唯一 | 取消及竞态集成；W-MODEL/W-CODER |
| M06 | 同任务并行调用/预算恰好耗尽/usage 缺失 → 原子预留、不透支新调用、未知不记零 | 账本并发/价格版本/计量对账；W-MODEL |
| M07 | 429/5xx、鉴权失败、审批拒绝 → 瞬态仅有界重试，永久错误零重试，预算含所有尝试 | 重试注入和请求计数；W-MODEL/R-RETRY |
| M08 | 工具结果与 call_id 不匹配、重试/恢复遇已执行动作 → 拒绝错误配对且不重复副作用 | 工具历史及幂等集成；W-CODER/R-IDEM |
| M09 | 恶意仓库指令/模型自带工具/伪造身份或 endpoint → 无越权、无任意出口、凭据不出现在日志 | 安全负向用例；W-MODEL/G-SEC |
| M10 | 单模型真实调用完成修复任务 → 真实工具/审批/证据/远端 PR 与恢复链路可审查 | W-MODEL 单供应商冒烟；完整闭环归 M1，Mock 不算 |

G-MODEL 文档验收范围：现有接口与建议可区分；供应商异常、凭据、预算、取消及兼容边界明确；官方对标可追溯；本轮验证如实记录。新增接口批准和生产验收分别记录。

## 8. 本轮验证、复核方法与剩余事项

| 测试项 | 用例 | 结果 | 修复动作/限制 |
|---|---|---|---|
| Coder/ReAct 局部回归 | `.venv/Scripts/python.exe -m pytest tests/unit/workers/coder tests/unit/workers/react_loop tests/integration/test_coder_e2e.py -q --no-cov --disable-warnings` | 64 通过，0 失败，17.20 秒 | 未改代码；集成使用 Mock 模型，不计真实供应商验收 |
| 文档链接与接口字段核对 | 检查本文件相对链接；使用 AST 核对 ModelClient.complete 参数与 ModelResponse 字段；检查四类建议结构和 M01～M10 | 9/9 本地链接通过；既有签名/字段核对通过；4 类结构与 10 组用例齐全 | 无失败修复；检查脚本即时执行，未新增正式测试 |
| 全量/覆盖率、Lint/typecheck、SAST/SCA/Secret | 本轮只交付专属文档，未更改可执行代码/依赖 | 未执行 | 不引用历史通过结果，不声称生产门禁通过 |
| 真实模型/弱网/流式/预算/取消/多模型 | M01～M10 | 本轮未执行 | 需要方案批准及实现、测试凭据和批准的真实环境 |

复核台账：仓库根目录运行 `.venv/Scripts/python.exe -X utf8 scripts/task_board.py show G-MODEL`；按上表命令运行已有测试。本轮无新增服务，无启动命令及环境模板变更；生产配置示例由获批准的 W-MODEL 实现交付。

剩余事项：本文方案确认；供应商/传输及实施基线；各下游真实装配、安全门禁和 M1 集成。用户尚未验收 G-RT，也未验收本工作包；不能自动解除对应硬依赖。复盘结论：预算字段名称不能代替实际剩余额度，模型输出提议不能代替授权决定，Mock 集成不能代替真实模型证据。
