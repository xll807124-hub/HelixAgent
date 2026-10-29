# 依赖驱动开发工作包目录

本目录说明范围；**实时状态、负责人、依赖、接口及验收标准以 [task-board.json](./task-board.json) 为唯一来源**。本文状态仅为2026-10-29迁移快照，领取前必须运行任务命令。工作包与60项REQ不是一对一关系，不能用工作包数量计算产品完成率。

`G-*` 是契约核对/评审工作包，implementation模式只允许交付契约文档；`implementation_ready=true` 不表示相关产品功能已获编码批准。其他工作包先领取design，方案确认后才能领取implementation。

| ID | 阶段 | 工作包 | 迁移状态 | 实现前置（全部满足） |
|---|---|---|---|---|
| G-RT | 0 | 运行时共享契约核对 | 待开发 | 无；仍须本任务实施基线确认 |
| G-SEC | 0 | 安全与租户共享契约 | 待开发 | 无；仍须本任务实施基线确认 |
| G-CTX | 0 | 索引与上下文契约 | 待开发 | 无；仍须本任务实施基线确认 |
| G-HAR | 0 | Worker与Harness契约 | 待开发 | G-RT |
| G-MEM | 0 | 记忆契约 | 待开发 | 无；仍须本任务实施基线确认 |
| G-OBS | 0 | 遥测与审计契约 | 待开发 | G-RT |
| G-EVA | 0 | 评估与发布契约 | 待开发 | 无；仍须本任务实施基线确认 |
| G-WEB | 0 | 控制台API与UI契约 | 待开发 | G-RT |
| G-MODEL | 0 | 模型网关契约 | 待开发 | 无；仍须本任务实施基线确认 |
| S0-SCHEMA | 0 | MCP工具批准与Schema变更复审 | 开发中 | 无；仍须本任务实施基线确认 |
| S0-MCP | 0 | MCP其余生产闭环 | 待开发 | G-SEC, S0-SCHEMA |
| S0-RED | 0 | 安全验证场景与红队框架 | 待开发 | G-SEC |
| S0-FREEZE | 0 | 阶段0补缺与冻结验收 | 待开发 | G-RT, G-SEC, S0-MCP, S0-RED |
| R-EVENT | 1.1 | PostgreSQL事件持久化 | 待开发 | G-RT |
| R-PROJ | 1.1 | 持久化投影与重放 | 待开发 | G-RT |
| R-CHECK | 1.2 | Checkpoint持久化与保留 | 待开发 | G-RT |
| R-IDEM | 1.2 | 跨进程幂等与写操作封装 | 待开发 | G-RT |
| R-QUERY | 1.2 | 事件查询留存权限完整闭环 | 待开发 | G-RT, G-SEC |
| R-FAIL | 1.2 | 失败分类与工具错误治理 | 待开发 | G-RT |
| R-RETRY | 1.2 | 重试策略与决策引擎 | 待开发 | R-FAIL |
| R-COMP | 1.2 | 恢复决策与补偿 | 待开发 | G-RT, R-FAIL |
| R-RECOVER | 1.2 | 运行时集成与故障恢复 | 待开发 | R-EVENT, R-PROJ, R-CHECK, R-IDEM, R-QUERY, R-RETRY, R-COMP |
| S-RBAC | 1.3 | 权限模型与策略网关补齐 | 待开发 | G-SEC |
| S-BOX | 1.3 | 沙箱隔离与资源控制 | 待开发 | G-SEC |
| S-CRED | 1.3 | 生产凭据签发与撤销 | 待开发 | G-SEC |
| T-FILE | 1.4 | 文件与Shell工具完善 | 待开发 | G-SEC, G-HAR |
| T-GIT | 1.4 | 真实GitHub与PR工具 | 待开发 | G-SEC, G-HAR |
| T-TEST | 1.4 | 多语言测试适配器 | 待开发 | G-HAR |
| W-MODEL | 1.5 | 模型网关与单模型接入 | 待开发 | G-MODEL |
| W-CODER | 1.5 | Coder执行与恢复接入 | 待开发 | G-HAR, G-MODEL |
| O-TRACE | 2.2 | 全链路Trace与关联 | 待开发 | G-OBS |
| O-AUDIT | 2.2 | 审计查询留存与完整性 | 待开发 | G-OBS, G-SEC |
| O-METRIC | 2.2 | 指标仪表盘与告警 | 待开发 | G-OBS |
| S-SCAN | 2.1 | 扫描与注入防护生产接入 | 待开发 | G-SEC |
| S-KILL | 2.3 | 完整Kill Switch | 待开发 | G-SEC, G-RT |
| S-TENANT | 2.4 | 多租户数据与计算隔离 | 待开发 | G-SEC, G-RT |
| E-DATA | 2.5 | Golden Dataset与标注 | 待开发 | G-EVA |
| E-SCORE | 2.5 | 评分器与失败归因 | 待开发 | G-EVA |
| E-GATE | 2.5 | 回归流水线与发布门禁 | 待开发 | E-DATA, E-SCORE |
| E-FEED | 2.5 | 生产反馈与回滚机制 | 待开发 | G-EVA |
| C-INDEX | 3.1 | 多语言索引与增量一致性 | 待开发 | G-CTX |
| C-SEARCH | 3.2 | 混合检索与权限过滤 | 待开发 | G-CTX, G-SEC |
| C-SELECT | 3.3 | 预算分层加载与压缩 | 待开发 | G-CTX |
| C-EVAL | 3.4 | 检索评测与A/B工具 | 待开发 | G-CTX, G-EVA |
| H-SDK | 4.4 | Harness生命周期工具Hook路由 | 待开发 | G-HAR |
| P-DAG | 4.1 | DAG调度与Artifact通信 | 待开发 | G-HAR |
| P-EXPERT | 4.2 | 五种专家Worker | 待开发 | G-HAR, G-MODEL |
| P-MEM | 4.3 | 记忆存储审批检索与生命周期 | 待开发 | G-MEM, G-SEC |
| WEB | MVP | Web任务控制台 | 待开发 | G-WEB |
| A-IDE | 5 | IDE与CLI集成 | 待开发 | G-WEB |
| A-SSO | 5 | SSO与SCIM | 待开发 | G-SEC |
| A-POOL | 5 | WarmPool优化 | 待开发 | S-BOX |
| A-ROUTE | 5 | 多模型路由优化 | 待开发 | W-MODEL, E-SCORE |
| A-ORGMEM | 5 | 长期组织记忆 | 待开发 | P-MEM, S-TENANT |
| M1 | 里程碑 | 可靠Issue到PR闭环验收 | 待开发 | R-RECOVER, S-RBAC, S-BOX, S-CRED, T-FILE, T-GIT, T-TEST, W-MODEL, W-CODER, O-TRACE, E-DATA, E-SCORE |
| M2 | 里程碑 | 可控上线验收 | 待开发 | M1, S0-FREEZE, O-AUDIT, O-METRIC, S-SCAN, S-KILL, S-TENANT, E-GATE, E-FEED, WEB |
| M3 | 里程碑 | 上下文接入评估与冻结 | 待开发 | M1, C-INDEX, C-SEARCH, C-SELECT, C-EVAL |
| M4 | 里程碑 | 多Worker与记忆平台验收 | 待开发 | M2, M3, H-SDK, P-DAG, P-EXPERT, P-MEM |
| DONE-ALIGN | 0 | 设计—代码对齐评审 | 已完成 | 无；仍须本任务实施基线确认 |
| DONE-LIFECYCLE | 0 | MCP生命周期发现与调用一致拒绝及扫描扩展 | 已完成 | 无；仍须本任务实施基线确认 |
| DONE-CREDENTIAL | 0 | 连接器级凭据失效与SEC-005撤销联动 | 已完成 | 无；仍须本任务实施基线确认 |
| DOC-ROUTE | 治理 | 执行手册依赖路线与多AI领取机制 | 开发中 | 无；仍须本任务实施基线确认 |

## 拆分规则

每一行是可领取工作包，不是限制并行数量的固定泳道。可将专家Worker、三种检索、AST/LSP、测试适配器、记忆等继续拆成子任务；父任务改为汇总验收，依赖子任务；子任务必须分别有接口、验收和不重叠写入范围。拆分须使用台账锁，检查无环并保留历史；不得让父子任务同时修改相同代码。

## 实现与验收依赖

implementation_dependencies为实现硬依赖；design模式可提前研究、拟定契约和使用隔离原型，不允许修改生产代码、正式测试或共享契约。依赖只到契约的工作包可使用契约替身独立开发；真实组件接入在M1～M4汇合测试，禁止把替身测试当成端到端验收。

M1不必等待完整阶段0或阶段2，但必须具备本闭环实际使用的安全控制；M2才要求阶段0余项关闭和可控上线能力到位。M3不等M2；DAG和专家可早开发，其检索增强平台整体验收在M4等待M3。阶段5独立功能各自验收，性能优化需要真实测量；不存在等待阶段5全部完成的统一发布门。

## 正式需求覆盖

全部60项正式REQ已映射到台账requirements；WEB、WKR-001、ADV-*为额外范围，不计入60项。一次实现未覆盖整项REQ时必须记录剩余条件并增补任务，禁止用工作包完成自动标记整项REQ完成。历史Prompt、扫描适配器和RT-008局部修复继续保留手册证据，在相关补齐工作包中复用。
