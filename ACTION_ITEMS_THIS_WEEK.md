# 【今周立即行动清单】2026-10-10 ~ 2026-10-18

> **文档版本**: v1.0  
> **创建日期**: 2026-10-10  
> **管理方式**: 每日检查 + 每周回顾  
> **更新频率**: 每日 10:00 AM 站会

---

## 一、今天（2026-10-10）必做项

### 优先级 P0（必须今天完成）

#### 1. 【轨 A】确认与会人员名单及会议时间

**任务**：架构组  
**操作**：
```
1. 准备邀请名单（7-8 人）：
   ✓ RT 模块代表（运行时基础）
   ✓ SEC 模块代表（安全威胁）
   ✓ REL 模块代表（可靠性）
   ✓ CTX 模块代表（上下文）
   ✓ EVA 模块代表（评估）
   ✓ HAR 模块代表（Harness）
   ✓ OBS 模块代表（可观测）
   ✓ 技术总负责人（架构决策权）

2. 发送邀请函 → 收集确认（截止 17:00）

3. 确定会议时间（推荐）：
   □ 2026-10-12（周日）上午 9:00-12:00 第 1 轮（P0 问题评审）
   或
   □ 2026-10-13（周一）上午 9:00-12:00 第 1 轮
   
4. 预约会议室 / 视频会议链接
```

**验收标准**：
- [ ] 7-8 人全部确认参加
- [ ] 会议时间确定（日历已同步）
- [ ] 会议链接/地点已发送

**交付物**：邮件确认 + 日历邀请

---

#### 2. 【轨 A】汇总 Runtime Contract v1.0 草稿

**任务**：架构组  
**操作**：
```
1. 合并 8 个文件的内容到单个文档：
   ├── docs/design-specs/REQ-RT-001-core-runtime-entities.md
   ├── docs/design-specs/REQ-RT-002-state-machines.md
   ├── docs/design-specs/REQ-RT-003-event-schema-versioning.md
   ├── docs/design-specs/REQ-RT-004-state-projections.md
   ├── docs/design-specs/REQ-RT-005-checkpoint-protocol.md
   ├── docs/design-specs/REQ-RT-006-Trace-传播和审计关联.md
   ├── docs/design-specs/REQ-RT-007-idempotency-key.md
   └── docs/design-specs/REQ-RT-008-event-query-retention-redaction-permission.md

2. 生成目录（Table of Contents）
3. 补充章节间的交叉引用
4. 生成依赖关系图（Mermaid）
5. 校验无遗漏 / 无冲突
```

**验收标准**：
- [ ] 合并文档 > 5000 字
- [ ] 包含完整目录
- [ ] 交叉引用正确
- [ ] 没有 TODO 或未完成章节

**交付物**：`docs/design-specs/runtime-contract-v1.0-draft.md`

---

#### 3. 【轨 A】汇总 Security Baseline v1.0 草稿

**任务**：安全组  
**操作**：
```
1. 合并 10 个文件的内容到单个文档：
   ├── docs/design-specs/REQ-SEC-001-threat-model-risk-scoring.md
   ├── docs/design-specs/REQ-SEC-002-rbac-resource-authorization.md
   ├── docs/design-specs/REQ-SEC-003-policy-gateway.md
   ├── docs/design-specs/REQ-SEC-004-sandbox-isolation-baseline.md
   ├── docs/design-specs/REQ-SEC-005-credential-proxy.md
   ├── docs/design-specs/REQ-SEC-006-prompt-injection-malicious-repo-protection.md
   ├── docs/design-specs/REQ-SEC-007-mcp-connector-governance.md
   ├── docs/design-specs/REQ-SEC-008-multi-tenant-data-governance.md
   ├── docs/design-specs/REQ-SEC-009-kill-switch.md
   └── docs/design-specs/REQ-SEC-010-security-control-validation-red-team.md

2. 生成目录（TOC）
3. 补充交叉引用
4. 校验完整性
```

**验收标准**：
- [ ] 合并文档 > 5000 字
- [ ] 四道防线清晰呈现
- [ ] 没有矛盾或遗漏

**交付物**：`docs/design-specs/security-baseline-v1.0-draft.md`

---

#### 4. 【轨 B】启动目录结构创建

**任务**：基础设施 Lead  
**操作**：
```bash
# 创建主目录
mkdir -p src/runtime/{entities,state_machine,event_store,projection,checkpoint,trace,idempotency}
mkdir -p src/security/{rbac,policy_gateway,sandbox,credential,kill_switch}
mkdir -p src/reliability/{failure_taxonomy,retry_policy,retry_decision_engine,compensation}
mkdir -p src/context/{indexing,retrieval,selector}
mkdir -p src/memory/{schema,approval,lifecycle}
mkdir -p src/harness/{identity,context,tools,execution,policy,evidence}
mkdir -p src/observability/{telemetry,audit,metrics}
mkdir -p src/evaluation/{dataset,scorer,regression}
mkdir -p src/workers/{coder,explorer,planner,common}
mkdir -p src/tools/{file,search,git,test,shell}
mkdir -p src/api/{schemas,endpoints,middleware}

mkdir -p tests/{unit,integration,e2e}
mkdir -p infra/{docker,kubernetes,terraform,scripts}
mkdir -p docs/{api,architecture,runbooks,development}

# 创建初始文件
touch pyproject.toml requirements.txt requirements-dev.txt
touch Makefile docker-compose.yml pytest.ini
touch .pre-commit-config.yaml .env.example .env.dev .env.test
mkdir -p .vscode
touch .vscode/settings.json .vscode/launch.json
```

**验收标准**：
- [ ] 34 个目录创建完成
- [ ] 初始配置文件已创建
- [ ] 无文件名拼写错误

**交付物**：项目目录树（可用 `tree` 命令或 PowerShell）

---

### 优先级 P1（今天尽量完成）

#### 5. 【轨 A】识别已知接口问题清单

**任务**：架构组  
**操作**：
```
已知 5 个问题（来自评审议程文档）：

P0 问题：
1. EVA-006/007 接口不对齐
   - 问题：EVA-007 依赖 Error Budget，但 EVA-006 未定义
   - 待决策：是否接受新增 Error Budget？
   - 责任人：EVA-006 负责人
   - 目标：2026-10-12 会议投票

2. SEC-009/EVA-007 Kill Switch 升级路径
   - 问题：应升至哪一档（M2 局部 vs M4 项目级）？
   - 责任人：SEC-009 负责人
   - 目标：2026-10-12 会议投票

3. Runtime Contract 版本管理规范统一
   - 问题：Bundle 定义、版本号格式、兼容性矩阵未统一
   - 责任人：架构组
   - 目标：2026-10-12 会议投票

P1 问题（可带入实现）：
4. OBS-003 指标字典是否含血缘维度
5. REL-009 红队报告与 EVA-006 核对

生成追踪表格式：
| # | 问题 | 优先级 | 状态 | 责任人 | 截止日期 | 备注 |
|----|------|--------|------|--------|---------|------|
```

**验收标准**：
- [ ] 5 个问题全部记录
- [ ] 每个问题有责任人
- [ ] 清晰的待决策项

**交付物**：`docs/design-specs/INTERFACE_ISSUES_TRACKER.md`

---

#### 6. 【轨 B】创建初始 Python 配置文件

**任务**：后端 Lead  
**操作**：
```
1. 创建 pyproject.toml（Python 项目配置）
   - 项目名称：ai-agent
   - Python 版本：3.11+
   - 依赖管理

2. 创建 requirements.txt（生产依赖）
   - fastapi==0.104.0
   - uvicorn==0.24.0
   - sqlalchemy==2.0.0
   - psycopg2-binary==2.9.0
   - pydantic==2.0.0
   - redis==5.0.0
   - python-dotenv==1.0.0
   - ...（更多根据需要）

3. 创建 requirements-dev.txt（开发依赖）
   - pytest==7.4.0
   - pytest-cov==4.1.0
   - black==23.0.0
   - ruff==0.1.0
   - mypy==1.5.0
   - pre-commit==3.4.0
   - ...
```

**验收标准**：
- [ ] pyproject.toml 格式正确
- [ ] requirements.txt 包含核心依赖（FastAPI、PostgreSQL、Redis）
- [ ] requirements-dev.txt 包含测试工具（pytest、black、ruff、mypy）

**交付物**：三个配置文件

---

## 二、本周关键路径日程

```
【周一 10-10】
├─ 上午：确认与会人员 + 会议时间
├─ 下午：汇总 Runtime Contract v1.0 + Security Baseline v1.0
└─ 晚上：整理接口问题清单

【周二 10-11】
├─ 上午：评审准备包定稿 + 分发
├─ 下午：项目目录结构创建完成
└─ 晚上：投票人预审阅

【周三 10-12】（可能的第 1 轮评审会）
├─ 上午：第 1 轮评审会 (2-4 小时)
│  ├─ P0 问题 1：EVA-006/007 → 投票
│  ├─ P0 问题 2：SEC-009/EVA-007 → 投票
│  └─ P0 问题 3：版本管理规范 → 投票
├─ 下午：会议纪要整理
└─ 晚上：各模块启动修改工作

【周四 10-13】
├─ 上午：各模块根据投票结果修改设计文档
├─ 中午：Python 环境配置完成
├─ 下午：继续修改 + Docker 配置
└─ 晚生：修改后的文档 commit 到 git

【周五 10-14】
├─ 上午：修改完整性检查 + 其他模块自检
├─ 下午：PostgreSQL + Redis 本地环境启动
├─ 晚上：周进度总结（完成度统计）
└─ 预期完成度：轨 A 60%，轨 B 80%

【周末 10-15】（可选补工作时间）
├─ 最终修改定稿
└─ 环境准备最后测试
```

---

## 三、立即可执行的 shell 命令

### 创建目录结构

```powershell
# PowerShell 命令
cd 'g:\项目\Ai_agent'

# 创建所有目录
$directories = @(
    "src/runtime/entities",
    "src/runtime/state_machine",
    "src/runtime/event_store",
    "src/runtime/projection",
    "src/runtime/checkpoint",
    "src/runtime/trace",
    "src/runtime/idempotency",
    "src/security/rbac",
    "src/security/policy_gateway",
    "src/security/sandbox",
    "src/security/credential",
    "src/security/kill_switch",
    "src/reliability/failure_taxonomy",
    "src/reliability/retry_policy",
    "src/reliability/retry_decision_engine",
    "src/reliability/compensation",
    "src/context/indexing",
    "src/context/retrieval",
    "src/context/selector",
    "src/memory/schema",
    "src/memory/approval",
    "src/memory/lifecycle",
    "src/harness/identity",
    "src/harness/context",
    "src/harness/tools",
    "src/harness/execution",
    "src/harness/policy",
    "src/harness/evidence",
    "src/observability/telemetry",
    "src/observability/audit",
    "src/observability/metrics",
    "src/evaluation/dataset",
    "src/evaluation/scorer",
    "src/evaluation/regression",
    "src/workers/coder",
    "src/workers/explorer",
    "src/workers/planner",
    "src/workers/common",
    "src/tools/file",
    "src/tools/search",
    "src/tools/git",
    "src/tools/test",
    "src/tools/shell",
    "src/api/schemas",
    "src/api/endpoints",
    "src/api/middleware",
    "tests/unit",
    "tests/integration",
    "tests/e2e",
    "infra/docker",
    "infra/kubernetes",
    "infra/terraform",
    "infra/scripts",
    "docs/api",
    "docs/architecture",
    "docs/runbooks",
    "docs/development",
    ".vscode"
)

foreach ($dir in $directories) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

# 创建初始文件
@("pyproject.toml", "requirements.txt", "requirements-dev.txt", "Makefile", "docker-compose.yml", "pytest.ini", ".pre-commit-config.yaml", ".env.example", ".env.dev", ".env.test") | ForEach-Object {
    New-Item -ItemType File -Force -Path $_
}

Write-Host "✓ 所有目录和初始文件已创建"
```

---

## 四、每日站会模板（10:00 AM）

### 2026-10-10（今天）

```
【参加者】架构组、轨 A 负责人、轨 B 负责人

【昨天完成】
- 无（第一天）

【今天完成】
- [ ] 确认 8 人与会 + 会议时间
- [ ] Runtime Contract v1.0 草稿汇总
- [ ] Security Baseline v1.0 草稿汇总
- [ ] 接口问题清单整理
- [ ] 项目目录结构创建开始

【今天计划（预期）】
- [ ] 汇总工作完成定稿
- [ ] 评审准备包分发
- [ ] Python 配置文件创建

【阻塞项】
- 无

【明天重点】
- [ ] 项目目录结构创建完成
- [ ] Docker 配置文件编写
- [ ] 投票人开始预阅读评审材料
```

---

## 五、关键联系方式（待填写）

| 角色 | 名称 | 邮箱 | 手机 |
|------|------|------|------|
| 架构组 Lead | [待填] | [待填] | [待填] |
| 运行时负责人 | [待填] | [待填] | [待填] |
| 安全负责人 | [待填] | [待填] | [待填] |
| 可靠性负责人 | [待填] | [待填] | [待填] |
| 上下文负责人 | [待填] | [待填] | [待填] |
| 基础设施 Lead | [待填] | [待填] | [待填] |
| 后端 Lead | [待填] | [待填] | [待填] |
| QA Lead | [待填] | [待填] | [待填] |

---

## 六、常见问题 FAQ

### Q1：如果 P0 问题在会议中无法解决怎么办？

**A**：延迟评审 1 周。记录具体分歧点，邀请外部评审专家或技术委员会介入。

### Q2：环境搭建遇到 Docker 问题怎么办？

**A**：提供临时云端 DevBox（AWS/Azure）。同时调试本地 Docker 配置。

### Q3：某个模块负责人缺席会议怎么办？

**A**：提前分配代理人。会前收集书面意见，代理人在会上表决。

### Q4：投票结果 < 80% 怎么办？

**A**：否决当前版本。记录反对意见，2-3 天内召集反对者修改设计，周内重新投票。

---

**负责人**：项目管理办公室  
**紧急联系**：[待填写]  
**下次更新**：2026-10-11 17:00（每日）
