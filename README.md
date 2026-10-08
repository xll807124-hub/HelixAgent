# AI Agent 平台项目

> **项目状态**: 设计阶段  
> **最后更新**: 2026-09-27

---

## 📋 项目简介

这是一个面向软件研发团队的 AI Agent 平台项目，旨在帮助开发人员完成从需求理解、代码分析、任务规划、代码修改、测试验证到 Pull Request 创建的完整研发闭环。

**核心承诺**:
> 用户提交一个 Issue 或研发任务，Agent 能够理解项目上下文，生成实施计划，在隔离环境中完成代码修改并运行验证，最后生成可供人工审查的 Pull Request。

---

## 🚀 快速开始

### 核心文档

- **[需求设计方案](./需求设计方案.md)** - 项目总体需求、架构设计和开发路线图
- **[详细设计规范目录](./docs/design-specs/README.md)** - 所有详细设计文档的入口

### 项目目标

第一阶段建设一个**可控、可审查、可恢复、可审计的研发 Agent 平台**:

```text
Issue / 用户需求
    ↓
代码库理解
    ↓
实施计划 → [人工确认]
    ↓
隔离工作区
    ↓
Agent 执行
    ↓
测试与质量检查
    ↓
Diff 与证据汇总
    ↓
Pull Request → [人工评审与合并]
```

---

## 📚 文档结构

```
Ai_agent/
├── README.md                    # 本文件 - 项目入口
├── 需求设计方案.md              # 统一需求设计方案
└── docs/
    └── design-specs/           # 详细设计规范目录
        ├── README.md           # 设计规范总览
        ├── INDEX.md            # 功能点快速索引
        ├── 00-integrated-design-baseline.md          # 统一设计基线
        ├── PENDING-REQUIREMENTS.md                   # 未完成需求清单
        ├── 01-runtime-contracts.md                   # 运行时基础契约
        ├── 02-security-threat-model.md               # 安全威胁模型
        ├── 03-failure-recovery-retry.md              # 失败恢复与重试
        ├── 04-context-and-code-indexing.md           # 上下文管理与代码索引
        ├── 05-evaluation-system.md                   # 评估体系
        ├── REQ-RT-001-core-runtime-entities.md       # 核心实体 Schema
        ├── REQ-RT-002-state-machines.md              # 状态机与迁移约束
        ├── REQ-RT-003-event-schema-versioning.md     # Event Schema 与版本
        ├── REQ-RT-004-state-projections.md           # 状态投影
        └── REQ-RT-005-checkpoint-protocol.md         # Checkpoint Protocol
```

---

## 🎯 设计进度

### 已完成详细设计（60/60 项正式基线，均待跨模块评审与冻结）

| 模块 | 需求编号 | 需求数量 | 版本 | 状态 |
|------|---------|---------|------|------|
| **运行时基础** | REQ-RT-001~008 | 8 项 | v0.1/v0.2-designed | ✅ 待跨模块冻结 |
| **安全体系** | REQ-SEC-001~010 | 10 项 | v0.1/v0.2-designed | ✅ 待跨模块冻结 |
| **可靠性** | REQ-REL-001~009（含子需求 008A） | 9 项 | v0.1/v0.2-designed | ✅ 待跨模块冻结 |
| **上下文管理** | REQ-CTX-001~009 | 9 项 | v0.1/v1.0-designed | ✅ 待跨模块冻结 |
| **记忆管理** | REQ-MEM-001~004 | 4 项 | v0.1-designed | ✅ 待跨模块冻结 |
| **Harness 工程** | REQ-HAR-001~006 | 6 项 | v0.1-designed | ✅ 待跨模块冻结 |
| **可观测性** | REQ-OBS-001~007 | 7 项 | v0.1/v1.0-designed | ✅ 待跨模块冻结 |
| **评估体系** | REQ-EVA-001~007 | 7 项 | v0.1-designed | ✅ 待跨模块冻结 |

**最新进展**（2026-10-08）：
1. `REQ-EVA-007`（生产反馈、数据集更新和版本回滚）已完成详细设计，补齐评估体系从"发布前质量门禁"到"生产态持续反馈"的结构性缺口。核心内容包括：生产漂移检测（distribution drift）、失败案例采集与入集流程、Golden Dataset 动态更新协议、Capability eval → Regression suite 转换规则、模型/评估集版本回滚触发器。对标 Anthropic《Demystifying evals for AI agents》的评估方法分阶段部署理念、MLflow Model Registry 的版本管理机制。
2. EVA 模块全部 7 项需求已完成详细设计（100%），详见专项文档。

**完成率**: 60/60 = 100%（**全部正式基线需求已完成详细设计，可进入跨模块评审与冻结阶段**）

**关键里程碑**：
- ✅ 运行时基础契约（RT-001~008）全部完成详细设计
- ✅ 安全体系（SEC-001~010）全部完成详细设计
- ✅ 可靠性体系（REL-001~009）全部完成详细设计
- ✅ 上下文管理（CTX-001~009）全部完成详细设计
- ✅ 记忆管理（MEM-001~004）全部完成详细设计
- ✅ Harness 工程（HAR-001~006）全部完成详细设计
- ✅ 可观测性（OBS-001~007）全部完成详细设计
- ✅ 评估体系（EVA-001~006）全部完成详细设计

### 待完成专项设计（数量以待办清单唯一编号为准）

详见 [未完成需求清单](./docs/design-specs/PENDING-REQUIREMENTS.md)

**按优先级分布**:
- P0/P1 待设计数量以 [未完成需求清单](./docs/design-specs/PENDING-REQUIREMENTS.md) 中的唯一需求编号为准；历史汇总存在口径差异，待全量盘点

**下一步行动**: 
运行时基础契约（REQ-RT-001 至 REQ-RT-008）已全部完成详细设计，建议进入 [Runtime Contract v1 跨模块冻结阶段](./docs/design-specs/PENDING-REQUIREMENTS.md#里程碑-1runtime-contract-v1-冻结)。

---

## 🏗️ 总体架构

### 核心设计原则

1. **控制平面与执行平面分离** - Agent 决策与代码执行环境严格隔离
2. **零信任架构** - 权限判断先于上下文加载，默认拒绝
3. **事件事实源** - 所有状态变化追加到不可变事件流
4. **可恢复执行** - Worker 崩溃后从检查点继续
5. **可审计追踪** - 每个 Action 关联用户、任务、策略版本和 Trace

### 六层 Harness 架构

1. **Identity Harness** - 用户、组织、项目、仓库和任务身份
2. **Context Harness** - 按权限和预算加载上下文
3. **Tool Harness** - 按 Worker 能力暴露工具
4. **Execution Harness** - 工作区、沙箱、网络和资源限制
5. **Policy Harness** - 风险、审批、预算和输出校验
6. **Evidence Harness** - 事件、Trace、Artifact、Evidence 和指标记录

### 专家 Worker 类型

- **Explorer** - 代码库探索、依赖分析（只读）
- **Planner** - 生成实施计划、风险评估（只读）
- **Coder** - 按计划修改代码（可写，限任务分支）
- **Tester** - 执行测试、分析失败（只读）
- **Reviewer** - 检查 Diff、质量和安全（只读）
- **Resolver** - 处理测试或评审失败（可写，限任务分支）
- **Release** - 生成 PR 和发布说明（只读）

---

## 🛣️ 开发路线图

### 阶段 0: 设计冻结（4-6 周）- 当前阶段

**已完成**:
- ✅ REQ-RT-001 至 REQ-RT-006 详细设计

**进行中**:
- ⏳ Runtime Contract v1 跨模块评审
- ⏳ 威胁模型和控制矩阵设计
- ⏳ 失败分类和重试策略设计
- ⏳ Golden Dataset 构建（目标 50 个任务）

**门禁条件**:
- [ ] 所有 Schema 已冻结并通过评审
- [ ] 威胁模型和控制矩阵已完成
- [ ] 失败分类和重试策略已定义
- [ ] Golden Dataset v0.1 完成

### 阶段 1: 最小可靠闭环（8-10 周）

**目标**: Issue 到 PR 的基本闭环

**关键交付**:
- 事件存储和状态投影
- Docker 沙箱隔离
- 基础工具集（文件、Git、测试）
- RBAC 和 Policy Gateway
- Agent ReAct 循环

**门禁条件**:
- [ ] 一个真实任务能从 Issue 到 PR
- [ ] 任务能从崩溃中恢复
- [ ] 未授权操作被阻止
- [ ] 回归测试通过率 > 80%

### 阶段 2: 可控上线（6-8 周）

**目标**: 从"能运行"到"可安全运行"

**关键交付**:
- Secret Scanning 和 SAST 集成
- 凭据代理
- 审计日志和可观测性
- Kill Switch
- 回归测试流水线

**门禁条件**:
- [ ] 安全对抗样本防御率 > 98%
- [ ] Kill Switch 可用
- [ ] 审计日志完整
- [ ] 回归测试通过率 > 85%

### 阶段 3: 上下文基线冻结（6-8 周）

**目标**: 基于评测确定上下文算法基线

**关键交付**:
- AST 解析和符号图
- 混合检索（BM25 + Vector + Graph）
- Context Selector
- 基线对比实验

**门禁条件**:
- [ ] 检索质量达标（Recall@10 > 0.9）
- [ ] 检索延迟达标（p95 < 500ms）
- [ ] 任务成功率提升 > 10%

---

## 🔐 安全设计

### 四道零信任防线

1. **AI Gateway** - 模型路由、短期凭据、Agent 零凭证持有
2. **Sandbox Execution** - Docker 隔离、默认拒绝网络
3. **Communication Control** - 结构化事件、来源追踪
4. **AI Asset Governance** - 资产版本、签名、审批

### 安全原则

- Agent 不持有长期凭据
- 默认拒绝网络和未授权文件访问
- Action 前后执行策略校验
- 支持从单个 Action 到全局的 Kill Switch
- 所有变更可追溯、可回放、可撤销

---

## 📊 技术选型

| 层次 | 技术 | 说明 |
|-----|------|------|
| **前端** | React + Next.js | 成熟生态、SSR 支持 |
| **后端** | Python FastAPI | AI 集成友好 |
| **数据库** | PostgreSQL | 事务保证、JSONB 支持 |
| **向量检索** | pgvector | 与 PostgreSQL 集成 |
| **任务队列** | Temporal / Redis Streams | 持久执行 / 轻量 |
| **执行环境** | Docker | MVP 基础隔离 |
| **追踪系统** | OpenTelemetry | 统一标准 |
| **模型接入** | 统一 Model Gateway | 避免供应商绑定 |

---

## 📖 参考资料

### 行业调研

本项目的架构设计参考了以下公开产品和标准：

- **Claude Code** - 分层权限、子代理、安全设计
- **GitHub Copilot Cloud Agent** - 任务流程、分支管理、交付边界
- **OpenAI Codex Cloud** - 环境隔离、网络控制
- **Google Jules** - Session 管理、计划审批
- **OpenHands SDK** - Action/Observation、事件驱动
- **LangGraph** - 持久化编排、State/Context 分离

### 相关论文

- ReAct: Reasoning and Acting in Language Models
- Toolformer: Language Models Can Teach Themselves to Use Tools
- Event Sourcing Pattern (Martin Fowler)
- CQRS and Event Sourcing

---

## 🤝 贡献指南

### 设计文档维护规则

1. 新专项设计必须先在 [未完成需求清单](./docs/design-specs/PENDING-REQUIREMENTS.md) 登记编号
2. 完成设计后更新 [统一设计基线](./docs/design-specs/00-integrated-design-baseline.md) 状态
3. 提交格式: `docs(design): complete REQ-XX-NNN detailed design`
4. 所有专项设计必须引用 Runtime Contract 共享坐标

### 设计审查流程

1. 提出变更 PR
2. 相关方评审
3. 架构师批准
4. 更新文档版本号和变更历史
5. 通知所有相关团队

---

## 📞 联系方式

| 领域 | 责任人 | 联系方式 |
|------|--------|----------|
| 整体架构 | 架构团队 | [待填写] |
| 运行时设计 | 后端 Lead | [待填写] |
| 安全设计 | 安全架构师 | [待填写] |
| 可靠性设计 | SRE Lead | [待填写] |
| 检索设计 | 搜索 Lead | [待填写] |
| 评估设计 | QA Lead | [待填写] |

---

## 📄 License

[待定]

---

**文档维护**: 架构团队  
**最后更新**: 2026-10-08
