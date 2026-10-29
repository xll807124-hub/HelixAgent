# C-INDEX 多语言索引与增量一致性实施方案

日期：2026-10-29；owner：`codex-cindex-20261029-01a185f8`；候选基线：`cindex-20261029-r1`。

状态：设计交付待确认。仅设计模式；未修改生产代码、正式测试、生产依赖或共享 REQ。G-CTX 仍待验收，不能因本方案确认跳过该实现硬依赖。原型是隔离实验，不并入产品实现或正式验收套件。

## 1. 问题、范围及复用

目标：为已授权的固定 Git revision 构建可重放、可持久读取的 Python/TypeScript/Go 结构索引，增量更新与全量结果等价，失败及并发不破坏已有可用版本。

依据：[执行手册](../../项目开发执行手册.md)依赖驱动章节、[需求分析](../需求分析报告.md) §5.7、[G-CTX r2](../development/contracts/context.md)及下列源设计。需求分析中的旧版本为历史快照，当前设计版本按源页与 G-CTX §15核对。

| 源设计 | 本次覆盖 | 保留的未覆盖要求 |
|---|---|---|
| [CTX-001](../design-specs/REQ-CTX-001-index-entities-schema.md) v0.2-designed | File/Symbol/Dependency/Relation/IndexMetadata，快照坐标 | embedding 非本包实现，不伪造向量字段 |
| [CTX-002](../design-specs/REQ-CTX-002-language-repository-scale-benchmark.md) v0.1-designed | 三语言、SMALL/MEDIUM基准、版本固定 | 每语言≥10仓库及正式检索召回必须补真实数据，原型不满足 |
| [CTX-003](../design-specs/REQ-CTX-003-ast-lsp-dependency-parsing.md) v0.1-designed | Tree-sitter/LSP、符号与关系、直接和一层传递依赖 | 不执行包安装、不建立完整传递依赖闭包、不将正则当语义解析 |
| [CTX-007](../design-specs/REQ-CTX-007-incremental-index-consistency.md) v0.2-designed | 按路径Merkle差异、版本发布/MVCC/回退与任务引用 | Webhook公网入口、签名配置及真实队列接入需另行落实边界 |

现有 `src/context` 不存在。`src/runtime/common/types.py` 已有实体ID工具；`src/runtime/entities`、Trace和Checkpoint字段复用，不另造冻结实体或幂等算法。ID工具是否满足严格UUIDv7须实现前按测试核对，不能凭函数注释断定。已有Git/File/Sandbox工具只能经其授权入口使用；本包不直接开放仓库执行权限。

功能边界：单个已登记仓库的一次固定SHA构建；支持多个租户数据隔离，不扩成跨仓库语义关联。全量及增量都生成完整逻辑快照。BM25/向量检索、RRF和查询权限属于C-SEARCH；Token选择属于C-SELECT；正式检索指标属于C-EVAL/M3。不能把符号提取率称作召回率。

## 2. 官方对标与选择（访问日期2026-10-29）

| 官方来源 / 已验证内容 | 优点 | 本方案借鉴与限制 |
|---|---|---|
| [Sourcegraph精确导航](https://sourcegraph.com/docs/code-navigation/precise-code-navigation)：使用语言无关SCIP索引协议 | 将索引生产与消费分开 | 保留实体/版本协议；本包不声称已实现SCIP导入或编译器精度 |
| [py-tree-sitter官方仓库](https://github.com/tree-sitter/py-tree-sitter)：提供Python绑定、语言wheel和传入旧树的增量解析方式 | 三语言可共用解析生命周期 | 每种grammar单独版本化，实际ABI/平台兼容须安装后测试；不推断调用目标语义 |
| [LSP 3.17规范](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/) | 通过能力协商统一语言服务调用 | 记录协商的位置编码，显式转换坐标；不把tsserver私有协议当LSP |
| [PostgreSQL事务隔离](https://www.postgresql.org/docs/current/transaction-iso.html)：READ COMMITTED每条命令取得快照，多条查询可见不同提交 | 可用事务/锁保护发布一致性 | 读固定index_version，发布锁定仓库头并CAS；不能仅靠默认隔离实现整次构建快照 |

以上只支持公开协议/行为；不宣称厂商采用本方案的数据库、增量算法或耗时。Cursor等历史资料不作为本轮未验证的性能依据。没有前端页面，不触发UI Skill。

## 3. 依赖与实施准入

现环境：Python3.13.18、Windows、Node/npm/Git/Docker命令可定位；Go、gopls、pyright-langserver、typescript-language-server未找到；Tree-sitter各包及psycopg/asyncpg均未安装。仅存在Docker命令不证明daemon或数据库可用。本次未读取凭据、安装软件或启动服务。

从PyPI官方JSON元数据读取以下候选精确版本（只读查询，尚无安装/ABI实证）：

| 生产依赖候选 | 精确版本 | 用途/许可证情况 | 批准后的验证 |
|---|---|---|---|
| tree-sitter | 0.26.0 | Python绑定；官方仓库MIT，PyPI license字段为空 | CPython3.13/Windows及部署Linux wheel、ABI兼容 |
| tree-sitter-python | 0.25.0 | Python grammar；元数据MIT | 语法样本及升级回归 |
| tree-sitter-typescript | 0.23.2 | TypeScript/TSX grammar；元数据MIT | 两种grammar入口及Unicode范围 |
| tree-sitter-go | 0.25.0 | Go grammar；元数据MIT | receiver、接口、泛型、别名 |
| psycopg | 3.3.6 | PostgreSQL驱动；LGPL-3.0-only | 部署许可证核对、libpq/TLS、事务与异步取消 |

不自动选择binary extra或引入另一驱动；libpq属于部署环境准入，不能靠下载未知二进制绕过。元数据来源为 `https://pypi.org/pypi/<package>/json`，Python版本要求分别≥3.10/3.10/3.9/3.10/3.10；不把“有wheel”当作当前环境可用证明。

依赖文件pyproject.toml、requirements.txt目前由W-MODEL占用。获得本方案批准后，须协调该文件写入边界/交接，在锁内扩展本任务范围；在此之前只实现不涉及共享依赖文件的允许工作，不私装依赖或修改他人锁定文件。生产依赖及许可证需用户随本方案明确批准；若实际兼容性要求改版本，再记录实证和影响，不静默替换。

LSP按组织批准且固定版本/镜像摘要的pyright、typescript-language-server和gopls提供。候选工具具体版本尚未完成平台验证，不在本方案中假称批准；第一实施切片只允许AST基础能力，完整LSP切片须先提交可核验工具版本清单。LSP不可用时明确AST_ONLY，不宣称TIER_1全能力已验收。

## 4. 模块、接口和数据结构

建议在`src/context/indexing`内按职责建立models、snapshot、parsers、dependencies、merkle、repository、service模块；按实际需要逐步增加，不先搭空壳框架。对外为内部Python API，不在本轮新增HTTP入口或共享Gateway错误码。

| 接口（新提案） | 输入与输出 | 不变量 |
|---|---|---|
| SnapshotReader.read(scope, revision, limits) | 可信租户/仓库范围、固定完整SHA → 文件路径/blob哈希/源码流 | 只读Git对象；不checkout到共享工作区，不跟随仓库符号链接 |
| Parser.parse(source, path, language) | 受限源码 → 源ParseResult +诊断/能力 | 不import项目模块、不执行仓库代码；错误节点明确记录 |
| Parser.parse_incremental(old_tree, edits) | 同grammar/编码旧树与编辑 → 新结果 | 树不可跨版本误复用；失败允许回全量解析并报告 |
| DependencyResolver.resolve(snapshot) | 包声明/锁文件 → 已解析DependencyNode、未解析诊断 | 仅直接+一层传递；无网络解析或包安装 |
| IndexService.build(request, cancellation) | BuildRequest → BuildResult | 构建幂等、受限、取消可传播；未激活不得冒充可读active |
| IndexRepository.acquire/read_page/release | 显式授权scope、index_version、分页/租约 → 快照句柄与实体页 | 不隐式latest；持久引用保护活跃任务读取 |
| IndexRepository.activate(candidate, expected_head) | 验证产物+当前头CAS → 发布或冲突 | 状态、头、必需审计/outbox同事务；不覆盖他人新头 |

BuildRequest：organization_id/project_id/repository_id、source_revision、optional base_index_version、build_mode(full/incremental)、parser_config_digest、policy_revision、correlation_id/trace_id、已授权任务坐标；request ID只关联，不替代RT-007逻辑意图和键持久化规则。BuildResult：index_version、source_revision、源IndexState、quality(AST_ONLY/SEMANTIC/DEGRADED)、diagnostics、统计、root_hash、duration、是否真正激活。质量标记置于适配层/metadata，不改冻结Runtime枚举。

实体保留CTX-001字段和schema_version。存储键包含organization_id、repository_id、index_version、entity_id，不能因不同租户同名文件串读。FileNode的UUIDv7实体ID按文件身份映射持久复用；与content hash、symbol ID分别处理，不用随机重生ID比较增量等价性。

Symbol qualified_name提案：规范化文件模块路径+嵌套作用域+种类+同名声明区分符。重载保留签名分支，不能按短名称合并；动态调用无法解析时保留未解析诊断，不臆造CALLS边。符号名/范围对同样源码、grammar、配置应确定。若需要跨文件重命名身份保持，则显式别名映射；MVP按删除/新增处理，不假定文件名变更就保留语义身份。

SourceRange具体坐标提案：0-based行、UTF-8字节列、end-exclusive；Tree-sitter/Python/LSP适配在边界转换，保留原编码诊断。G-CTX保留SourceRange字段但未冻结坐标含义，本提案必须获确认后才作为本包基线；不静默修改共享REQ。重点验证emoji/组合字符、CRLF、文件末尾、空文件和跨行范围。

DependencyNode.version必须来自可核验精确锁定版本。仅有范围、无完整lockfile/依赖边时返回UnresolvedDependency诊断并标记依赖图不完整，不把约束或`unknown`伪装成实际版本。Go的go.sum是完整性信息，不能单凭其中条目推断直接依赖边或构建完整传递关系；缺证据保持未解析。拒绝执行requirements的外部包含、可编辑安装或包管理器生命周期脚本。

## 5. 固定快照与安全边界

可信入口必须提供可验证read/index授权与已成功加载的完整敏感路径规则；缺少、失效或故障一律拒绝本次读取。只支持显式资源范围，不信模型给出的租户、路径、仓库地址。索引写入是平台资源变更，须由批准的任务操作触发并捕获审计；不赋予索引器仓库写权限。

Git以固定参数数组只读对象，禁止shell拼接、仓库hooks、LFS自动下载、子模块递归、凭据继承、外网fetch。未取得本地完整对象时明确REVISION_UNAVAILABLE；网络同步走独立批准的连接器。路径规范化后拒绝绝对路径、`..`越界、NUL、符号链接/gitlink；Windows大小写/Unicode冲突在导出前检测并拒绝，不静默合并文件。

配置/宏/脚本均视为数据。LSP在独立低权限隔离实例中读取专用快照，网络默认拒绝、无宿主密钥、不执行项目构建/安装或自动下载插件；工具插件/可执行路径只能来自受信配置。若无法证明安全隔离则禁用LSP并如实降级，不在宿主上随意运行仓库配置。威胁面：ASI01外部内容、ASI02工具调用、ASI03租户授权、ASI04 grammar/LSP供应链、ASI05解析/语言服务执行、ASI08失败传播；不新增模型自主调用链。

限额提案：第一切片≤1000个符合规则的源码文件、单文件≤2MiB、源码总量≤256MiB；解析工作进程每个内存512MiB/CPU受限、并发4；单文件2s，LSP单请求5s（源设计），构建硬截止120s；SMALL<5s、MEDIUM<30s仍为完整流水线验收目标，不把120s超时当达标。达到上限明确诊断且不得认定完整TIER_1索引成功。取消后不激活；已发布结果不回滚为不存在。

策略更新只使旧内容停止授权访问，不静默篡改历史快照；读取总要复核当前访问范围。构建日志只含安全诊断、哈希摘要、计数和trace，敏感源码/原始配置/凭据不入日志。

## 6. 增量、状态和发布事务

清单采用Git树和文件内容哈希；目录哈希对按规范化名称排序的`(name,type,child_hash)`编码后计算，包含类型以区分文件/目录，不按数组位置配对。差异遍历old/new名称并集，删除整个子树与新增子树都展开；改名MVP按删+增，重排不产生变更。并非所有仓库都可保证O(log N)，扁平目录可能退化，报告访问节点和建树成本。

新增/修改文件重建自身实体；删除文件清理旧声明及相关边。反向引用可受目标改名/导出变更影响，不能只重解析变更文件就保证一致：第一实现使用确定性全仓关系再解析，文件语法解析可增量复用；后续若引入受影响闭包需用全量oracle证明等价。配置/grammar/权限规则/依赖锁版本变化触发保守全量，基础版本缺失或跨repo也全量，不复用无法证实的旧树。

未变化文件仅复用不可变解析内容；新快照实体必须标记目标source_revision，不能把旧FileNode的revision原样搬过来。比较oracle使用规范化语义清单（路径/源码哈希/限定符号/范围/边），排除indexed_at/build ID等非语义坐标；身份映射另验稳定性，不用忽略所有ID掩盖丢边。

状态沿用pending→building→validating→active，失败→failed，旧active在新版本发布后stale，历史归档archived。应用层构建诊断与持久状态分开；未实现真实审计装配前不把日志当审计通过。

PostgreSQL提案：index_builds、file_identity、index_entities、index_relations、index_heads、index_task_refs、index_outbox；表均带租户/仓库坐标，唯一约束涵盖这些坐标；`one active per tenant/repository`作为唯一约束/发布事务不变量。用户隔离由服务强制授权加DB范围约束，RLS方案须与G-SEC共同核对，不能仅凭传入org_id放行。

构建数据先落不可见candidate事务批次；验证完整性、owner/edge引用及hash后，短事务锁仓库head，校验expected_head和构建租约fencing token，以CAS切换head并将旧active置stale、candidate置active、写outbox；失败全回滚。取消/进程崩溃仅留下不可见candidate供清理，不暴露半份索引。数据库写超时结果未知时按持久幂等键查已发布状态，不盲目再写。

读者在开始时固定版本并登记租约/引用，后续分页只读该版本且每页重新授权，默认READ COMMITTED多条查询不会影响不可变版本。归档清理要检查持久任务引用，不能只用进程内计数；崩溃后引用按可验证任务/租约状态处理，不按超时直接删除可能仍使用的版本。回退激活仅允许同SHA的验证版本，或任务显式切回旧代码SHA；不能让代码/索引漂移。archived版本保持只读，不违反源状态机重新激活。

## 7. 错误及恢复

内部错误分类提案：INVALID_INPUT、ACCESS_DENIED、POLICY_UNAVAILABLE、REVISION_UNAVAILABLE、LIMIT_EXCEEDED、PARSER_UNAVAILABLE、PARSE_ERROR、LSP_TIMEOUT、DEPENDENCY_UNRESOLVED、VERSION_CONFLICT、INTEGRITY_FAILURE、STORAGE_UNAVAILABLE、CANCELLED。尚非共享HTTP码，不更改RT/SEC错误枚举。

| 触发条件 | 必须响应 |
|---|---|
| 无权限/策略故障/跨租户读取 | 读取源码前拒绝，不返回存在性或路径计数 |
| 单文件有语法错误 | 保留诊断和能证实的部分结构；DEGRADED，不能伪装全质量成功 |
| LSP超时/崩溃 | 终止或清理实例、保留AST能力和错误；SEMANTIC/TIER_1不通过 |
| AST失败后的正则提取 | 仅调试诊断，绝不生成已验证语义边或计为正式符号召回 |
| 数据库故障/重复构建/租约失效 | 固定幂等意图恢复，拒绝旧fencing token，不覆盖新head |
| 构建取消/校验失败 | 不发布；旧active和旧任务读句柄保持可用 |
| 未知schema/grammar不兼容 | 拒绝复用该产物，走明确兼容/重建路径 |

远程重试有界且沿用REL/RT策略；第一切片不对权限拒绝、解析错误或审批等待自动重试。存储瞬态重试最多2次且不超过构建截止时间，提交结果未知先核查，不能重复创建外部可见资源。

## 8. 隔离实验与实测

文件：[spike.py](../development/prototypes/C-INDEX/spike.py)、[results.json](../development/prototypes/C-INDEX/results.json)。假设：按名称/类型匹配的Merkle差异等价全量清单比较；否证条件是任一差异漏报/误报或重放不等价。原型仅用标准库，不接产品、数据库或解析器。

最终执行环境Python3.13.18/Windows，15次中位数；8类正确性用例全部通过：不变、新增、删除、改名、重排、内容改动、变为空、文件变目录。额外复现旧伪代码仅遍历旧children数量时遗漏新增同级文件。原型在输出JSON旁写报告，无其他写入。

| 合成清单 | 单次改动 | Flat差异中位ms | 预建Merkle差异中位ms | 全树构建中位ms | 访问节点 | 建树Python峰值 |
|---|---|---|---|---|---|---|
| 1000文件 | 1 | 0.0680 | 0.0235 | 0.9117 | 111 | 297284 bytes |
| 10000文件 | 1 | 1.2525 | 0.0425 | 12.6837 | 201 | 3259048 bytes |

选择：坚持Merkle可复用设计；初期正确性oracle为平面全清单差异，生产复用树只作为优化。实验未计算磁盘、Git读取、AST/LSP、数据库、建索引和网络成本；峰值为tracemalloc Python分配，不是进程RSS。未在本轮对Tree-sitter与语言原生解析器做实际性能比较，不能据此批准它们性能达标或推断<30秒。无此环境的三语言选型实测保留为安装后准入，不以资料数字替代。

## 9. 实施顺序及验收

1. **真实最小闭环**：批准依赖/完成文件边界交接后，固定SHA→Python解析→PG候选写入→验证→原子激活→重新连接读取同版本；带权限拒绝、失败及取消用例。SQL迁移放本包内，可重入且只新增本包表；迁移授权、DSN模板和真实DB环境须明确，不删除既有表。
2. **三语言结构与一致性**：TS/TSX/Go grammar、范围转换、直接/一层传递依赖、保守关系重建，增量与全量对照；未完成LSP则交付仅AST切片并保留其余条件。
3. **真实语义与恢复**：批准固定LSP工具链后接入隔离LSP、进程故障、跨进程CAS/引用/审计与恢复测试；完整TIER_1不能提前验收。
4. **规模/质量汇合**：三语言各≥10基准仓库和可判定oracle；SMALL/MEDIUM端到端计时，C-SEARCH/C-EVAL真实检索Recall@10>90%按源指标复核，M3接入真实组件。

各步是本任务实施顺序而非已登记的新任务/批准事实。需拆分时在台账锁内创建明确接口/范围/依赖的子包；没有拆分前不能把第一步完成标作C-INDEX完成。

| 验收用例 | 触发 → 必须响应 / 证据 |
|---|---|
| CI01 范围/编码 | 三语言Unicode/CRLF/重载/嵌套作用域 → 范围精确且实体无错误合并 |
| CI02 增量 | 新增/删除/改名/重排/导出变更/锁文件变化 → 增量语义清单等价全量，身份映射可核对 |
| CI03 持久发布 | 真实PG两构建并发/提交超时/取消/断电恢复 → 单一head，无半份数据或静默重复发布 |
| CI04 隔离 | 同名repo/文件/ID跨租户、策略失败、符号链接越界 → 源码读取前拒绝，无数据/计数泄漏 |
| CI05 崩溃与引用 | 旧任务读取时新版本激活、归档与恢复 → 旧句柄正确，仍被使用资产不删除 |
| CI06 LSP与依赖 | 缺工具/超时/不完整lock/无匹配定义 → 显式降级/未解析，不伪造TIER_1和调用边 |
| CI07 性能 | 规定语言/规模固定数据、冷热缓存及并发 → 完整流水线SMALL<5s/MEDIUM<30s，不仅计AST或diff |
| CI08 正式质量 | 真实检索集→按语言/血缘报告Recall@10>90%，拒绝/失败分母明确，不以符号检出率替代 |

覆盖要求沿用迭代规则：总体行≥70%、核心≥90%、分支≥60%；授权/幂等/Checkpoint/审计等关键路径100%行覆盖。功能实现后运行Ruff/mypy/实际SAST/SCA/Secret、适用全量测试/真实数据库与故障注入，所有跳过和失败明确记录。当前已有测试不能证明新索引器通过。

## 10. 本轮检查报告与写入边界

| 测试项 | 用例 | 结果 | 修复动作/限制 |
|---|---|---|---|
| 实验正确性 | 8类清单变更+重放，旧例新增遗漏 | 全通过/旧例缺陷已复现 | 原型修正方案，不改源REQ或产品 |
| 原型静态检查 | ruff check 隔离spike.py | 初检5个B023，绑定partial后复测通过 | 重跑原型仍8/8通过，JSON使用最终运行 |
| 可复现计时 | 两种diff、建树、Python峰值 | 2种规模×15次，结果见§8 | 不能外推实际仓库SLO |
| 文档/台账 | 本地引用、围栏、路径范围、validate | 9/9本地引用有效、无未配对围栏/尾空格；计时表与JSON一致；owner/design状态正确；台账62项依赖无环 | 未宣称生产门禁通过 |
| AST/LSP/PG/真实召回/生产扫描 | 新依赖和环境尚未获准且未安装 | 未执行 | 等待实施批准、G-CTX验收及环境准入 |

本轮写入：本任务设计文件和`docs/development/prototypes/C-INDEX`，台账经脚本locked/read/validate/write更新。计划生产范围仍仅`src/context/indexing`、`tests/unit/context/indexing`；共享依赖、真实集成测试、DSN模板需锁内登记且无冲突后扩展，不因文中列举路径就获得写入授权。未新增UI、未修改其他AI成果、未commit/push。

复现：仓库根目录运行 `.venv/Scripts/python.exe -X utf8 docs/development/prototypes/C-INDEX/spike.py`；原型会覆盖自己的results.json。静态检查 `.venv/Scripts/python.exe -m ruff check docs/development/prototypes/C-INDEX/spike.py`。产品启动方式在最小真实切片交付时提供，本设计不提供假服务入口。

## 11. 请求确认的具体基线

确认`cindex-20261029-r1`：同意单仓库固定SHA、三语言Tree-sitter+独立LSP增强、PG不可变快照与CAS发布、上述错误/安全/范围/验收及分步实施；同意§3候选精确Python依赖及许可证验证路径；同意SourceRange坐标和未解析依赖的显式语义。解析器ABI/平台、LSP工具链版本和生产环境仍需准入验证；依赖文件先协调占用后修改。

该确认不代替G-CTX工作包用户验收，也不取消每语言10仓库、正式召回、真实数据库、LSP及里程碑剩余验收。未确认前维持design；即使方案确认，G-CTX未完成时仍不能claim implementation。真实准入齐备后直接执行已批准范围，不重复请求同一方案批准。
