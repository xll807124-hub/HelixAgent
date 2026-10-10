# 【阶段 0】设计冻结详细执行计划

> **文档版本**: v1.0  
> **创建日期**: 2026-10-10  
> **阶段目标**: 完成跨模块评审与冻结核心契约，并行准备开发环境  
> **执行方式**: 并行双轨制 - 评审轨 + 环境准备轨  
> **预期周期**: 2 周

---

## 一、并行工作轨制概览

```text
┌─────────────────────────────────────────────────────────────────┐
│                    【阶段 0】设计冻结                              │
└─────────────────────────────────────────────────────────────────┘
                            │
            ┌───────────────┴───────────────┐
            ▼                               ▼
    【轨 A】跨模块评审              【轨 B】开发环境准备
    与冻结核心契约                  与代码仓库结构
    (2 周)                          (2 周)
    │                               │
    ├─ 周 1-2                       ├─ 周 1
    │  ├─ 接口问题评审              │  ├─ 创建项目目录结构
    │  ├─ Runtime Contract v1       │  ├─ 配置 Python/Node.js 环境
    │  ├─ Security Baseline v1      │  └─ 设置开发工具链
    │  └─ 投票冻结                  │
    │                               ├─ 周 2
    └───────────────┬───────────────┤  ├─ 搭建 PostgreSQL 开发环境
                    │               │  ├─ 搭建 Redis 缓存
                    │               │  ├─ 配置 Docker 本地运行
                    ▼               │  └─ 编写快速开发指南
            【门禁】No-Go/Go        │
            决策通过                └───────────────┬─
                                                   ▼
                                    【交付】可独立开发的环境
```

---

## 二、轨 A：跨模块评审与冻结（2 周）

### A.1 准备阶段（第 1 周 前 2 天）

**时间**：2026-10-10 ~ 2026-10-11  
**负责人**：架构组  
**产出物**：评审准备包

#### A.1.1 汇总评审材料

- [ ] Runtime Contract v1.0 草稿版（含 RT-001 ~ RT-008）
- [ ] Security Baseline v1.0 草稿版（含 SEC-001 ~ SEC-010）
- [ ] 60 项需求依赖关系图（自动生成或手工绘制）
- [ ] 接口问题跟踪表（P0/P1/P2 三个优先级）

**关键文档位置**：
```
docs/design-specs/
├── 01-runtime-contracts.md          ← Runtime Contract 汇总
├── 02-security-threat-model.md      ← Security Baseline 汇总
├── REQ-EVA-006-007-接口协同评审.md   ← P0 问题清单
└── INDEX.md                         ← 60 项需求索引
```

#### A.1.2 识别已知问题

根据 `跨模块评审启动议程-2026-10-08.md`，已识别问题清单：

**P0 问题（阻塞冻结）**：
1. EVA-006/007 接口不对齐（Error Budget、触发器 Schema）
2. SEC-009/EVA-007 Kill Switch 升级路径未对齐
3. 运行时版本管理策略未统一

**P1 问题（可带入实现）**：
4. OBS-003 指标字典是否含血缘维度
5. REL-009 与 EVA-006 的红队报告核对

**处理方式**：
- P0：本周必须评审并达成共识（否则延迟评审 1 周）
- P1：可在评审会中记录，第 2 周前闭环

#### A.1.3 邀请与准备通知

```text
邀请清单：
✓ 运行时组负责人（RT-001 ~ RT-008）- 代表 8 项
✓ 安全组负责人（SEC-001 ~ SEC-010）- 代表 10 项
✓ 可靠性组负责人（REL-001 ~ REL-009）- 代表 9 项
✓ 上下文组负责人（CTX-001 ~ CTX-009）- 代表 9 项
✓ 评估组负责人（EVA-001 ~ EVA-007）- 代表 7 项
✓ 架构组负责人
✓ 技术总负责人（最终决策权）

共：7-8 人参与投票
```

**预期时间**：会议前 3 天收集确认

---

### A.2 评审阶段（第 1-2 周）

**时间**：2026-10-11 ~ 2026-10-18  
**负责人**：各模块设计负责人 + 架构组  
**会议形式**：混合式（同步会议 + 异步 Review）

#### A.2.1 第 1 周：接口问题集中评审

**方式**：同步会议 4 小时（两个上午或下午）

| 时间 | 议题 | 负责人 | 预期产出 |
|------|------|--------|---------|
| 2h | P0 问题 1：EVA-006/007 接口 | EVA-006 负责人 | 决议：接受/拒绝新增 Error Budget |
| 1h | P0 问题 2：SEC-009/EVA-007 升级 | SEC-009 负责人 | 决议：确认升级规则 |
| 0.5h | P0 问题 3：版本管理规范 | 架构组 | 决议：统一规范 |
| 0.5h | P1 问题 4-5 | 相关负责人 | 记录为 TD，定期跟进 |

**投票规则**：
- 每项问题投票通过后，相关负责人立即启动修改
- 无法在会议中达成共识的问题延迟 1 周再评审（影响里程碑）

#### A.2.2 第 1 周后期：修改与补充评审

**时间**：2026-10-13 ~ 2026-10-14  
**任务**：各模块负责人根据投票结果补充修改设计文档

示例：
- 若投票决定 EVA-006 接受 Error Budget，则 EVA-006 需在 2026-10-13 前完成补充设计
- 所有修改需更新到设计文档中，并标注版本号

#### A.2.3 第 2 周：冻结前最终审视

**时间**：2026-10-15 ~ 2026-10-18  
**任务**：

1. **全体 Review**（异步）：
   - 每个负责人 review 修改后的相关文档
   - 提交 Approve / Requested Changes

2. **冻结投票**（同步会议 2 小时）：
   - 逐项投票通过冻结版本
   - 记录任何残余风险或保留意见
   - 架构组做出最终 Go/No-Go 决策

**通过条件**：
- ✓ 所有 P0 问题已闭环
- ✓ ≥80% 投票人同意冻结
- ✓ 架构组明确表态"Go"

**不通过处理**：
- 记录否决理由和修改要求
- 延迟至少 1 周再评审（可能推迟阶段 1）

---

### A.3 冻结与交付（第 2 周末）

**时间**：2026-10-18 ~ 2026-10-20  
**产出物**：

- [ ] Runtime Contract v1.0（冻结版，含修订日志）
- [ ] Security Baseline v1.0（冻结版，含修订日志）
- [ ] 跨模块评审会议纪要
- [ ] 接口问题解决方案确认清单
- [ ] 阶段 1.1 启动 No-Go/Go 决策报告

**版本管理**：
```
runtime-contract-v1.0-frozen.md
├── 修订日志
├── 冻结时间戳
├── 冻结投票记录
└── 所有相关人签字确认
```

---

## 三、轨 B：开发环境与代码仓库准备（2 周）

### B.1 代码仓库结构创建（第 1 周）

**时间**：2026-10-10 ~ 2026-10-15  
**负责人**：基础设施团队 Lead  
**产出物**：标准化项目目录、`.env` 模板、快速开发指南

#### B.1.1 创建项目目录结构

根据 `项目开发执行手册.md` 中的标准结构，创建以下目录：

```
Ai_agent/
├── src/                                  # 源代码目录
│   ├── runtime/                         # RT 运行时基础
│   │   ├── entities/                    # RT-001 核心实体
│   │   ├── state_machine/               # RT-002 状态机
│   │   ├── event_store/                 # RT-003 事件存储
│   │   ├── projection/                  # RT-004 状态投影
│   │   ├── checkpoint/                  # RT-005 检查点
│   │   ├── trace/                       # RT-006 Trace 传播
│   │   └── idempotency/                 # RT-007 幂等性
│   │
│   ├── security/                        # 安全模块
│   │   ├── rbac/                        # SEC-002 权限控制
│   │   ├── policy_gateway/              # SEC-003 策略网关
│   │   ├── sandbox/                     # SEC-004 沙箱隔离
│   │   ├── credential/                  # SEC-005 凭据代理
│   │   └── kill_switch/                 # SEC-009 熔断开关
│   │
│   ├── reliability/                     # 可靠性模块
│   │   ├── failure_taxonomy/            # REL-001 失败分类
│   │   ├── retry_policy/                # REL-002 重试策略
│   │   ├── retry_decision_engine/       # REL-003 重试决策
│   │   └── compensation/                # REL-007 补偿工作流
│   │
│   ├── context/                         # 上下文管理
│   │   ├── indexing/                    # CTX-001-003 索引构建
│   │   ├── retrieval/                   # CTX-004-005 混合检索
│   │   └── selector/                    # CTX-006 上下文选择
│   │
│   ├── memory/                          # 记忆系统
│   │   ├── schema/                      # MEM-001 记忆数据模型
│   │   ├── approval/                    # MEM-002 写入审批
│   │   └── lifecycle/                   # MEM-004 生命周期
│   │
│   ├── harness/                         # Harness 层
│   │   ├── identity/                    # 身份管理
│   │   ├── context/                     # 上下文压缩
│   │   ├── tools/                       # 工具适配器
│   │   ├── execution/                   # 执行隔离
│   │   ├── policy/                      # 策略执行
│   │   └── evidence/                    # 证据记录
│   │
│   ├── observability/                   # 可观测性
│   │   ├── telemetry/                   # OBS-001 OpenTelemetry
│   │   ├── audit/                       # OBS-006/007 审计日志
│   │   └── metrics/                     # OBS-003 指标
│   │
│   ├── evaluation/                      # 评估系统
│   │   ├── dataset/                     # EVA-001 Golden Dataset
│   │   ├── scorer/                      # EVA-003 自动评分
│   │   └── regression/                  # EVA-005 回归测试
│   │
│   ├── workers/                         # Worker 实现
│   │   ├── coder/                       # Coder Worker
│   │   ├── explorer/                    # Explorer Worker (未来)
│   │   ├── planner/                     # Planner Worker (未来)
│   │   └── common/                      # 公共基类
│   │
│   ├── tools/                           # 工具集
│   │   ├── file/                        # 文件读写
│   │   ├── search/                      # 代码搜索
│   │   ├── git/                         # Git 操作
│   │   ├── test/                        # 测试执行
│   │   └── shell/                       # Shell 执行
│   │
│   └── api/                             # API 层
│       ├── schemas/                     # 数据模型
│       ├── endpoints/                   # API 端点
│       └── middleware/                  # 中间件
│
├── tests/                               # 测试代码
│   ├── unit/                            # 单元测试
│   │   ├── runtime/
│   │   ├── security/
│   │   ├── reliability/
│   │   └── ...
│   │
│   ├── integration/                     # 集成测试
│   │   └── workflows/
│   │
│   └── e2e/                             # 端到端测试
│       └── scenarios/
│
├── infra/                               # 基础设施
│   ├── docker/                          # Docker 配置
│   │   ├── Dockerfile
│   │   ├── docker-compose.yml
│   │   └── .dockerignore
│   │
│   ├── kubernetes/                      # K8s 配置 (未来)
│   │   └── manifests/
│   │
│   ├── terraform/                       # IaC 配置 (未来)
│   │   └── modules/
│   │
│   └── scripts/                         # 操作脚本
│       ├── setup.sh                     # 初始化脚本
│       ├── migrate.sh                   # 数据迁移
│       └── health_check.sh              # 健康检查
│
├── docs/                                # 文档
│   ├── design-specs/                    # 设计规范 (现有)
│   ├── api/                             # API 文档
│   ├── architecture/                    # 架构文档
│   ├── runbooks/                        # 运维手册
│   └── development/                     # 开发指南
│
├── .env.example                         # 环境变量模板
├── .env.test                            # 测试环境配置
├── .env.dev                             # 开发环境配置
├── pyproject.toml                       # Python 项目配置
├── requirements.txt                     # Python 依赖
├── requirements-dev.txt                 # 开发依赖
├── package.json                         # Node.js 项目配置（前端）
├── tsconfig.json                        # TypeScript 配置
├── Makefile                             # 开发命令集
├── docker-compose.yml                   # 本地开发环境
├── pytest.ini                           # pytest 配置
├── .pre-commit-config.yaml              # Pre-commit hooks
└── README.md                            # 项目说明
```

#### B.1.2 初始化基础文件

**创建时间**：第 1 周前 3 天

1. **根目录配置文件**：
   - [ ] `pyproject.toml` - Python 项目配置
   - [ ] `requirements.txt` - 生产依赖（FastAPI、PostgreSQL driver、Redis 等）
   - [ ] `requirements-dev.txt` - 开发依赖（pytest、black、ruff 等）
   - [ ] `.env.example` - 环境变量模板
   - [ ] `Makefile` - 常用命令（install、test、lint、run 等）
   - [ ] `.pre-commit-config.yaml` - Pre-commit hooks（lint、format、security check）

2. **Docker 配置**：
   - [ ] `Dockerfile` - 生产镜像
   - [ ] `docker-compose.yml` - 本地开发环境（含 PostgreSQL、Redis）

3. **测试配置**：
   - [ ] `pytest.ini` - pytest 配置
   - [ ] `tests/__init__.py` - 测试包初始化

4. **IDE 配置**：
   - [ ] `.vscode/settings.json` - VS Code 设置
   - [ ] `.vscode/launch.json` - Debug 配置
   - [ ] `.idea/codeStyles/` - PyCharm 设置（可选）

---

### B.2 开发环境搭建（第 1-2 周）

**时间**：2026-10-10 ~ 2026-10-20  
**负责人**：基础设施团队 + 开发 Lead  
**产出物**：本地开发环境、快速启动脚本

#### B.2.1 Python 环境配置

**目标**：一行命令启动完整开发环境

```bash
# 快速开始
make setup          # 安装依赖、配置预提交、初始化数据库
make dev            # 启动本地开发服务器
make test           # 运行所有测试
```

**具体步骤**：

1. [ ] 创建 Python 虚拟环境脚本
2. [ ] 配置 Poetry 或 pip 环保管理
3. [ ] 安装核心依赖：
   - `FastAPI`：后端框架
   - `SQLAlchemy`：ORM
   - `Pydantic`：数据验证
   - `psycopg2`：PostgreSQL driver
   - `redis`：缓存客户端
   - `pytest`：测试框架
   - `pytest-cov`：覆盖率
   - `black`：代码格式化
   - `ruff`：代码检查
   - `mypy`：类型检查

4. [ ] 配置 Pre-commit hooks：
   ```yaml
   - repo: https://github.com/psf/black
     rev: 23.0.0
     hooks:
       - id: black
   
   - repo: https://github.com/charliermarsh/ruff-pre-commit
     rev: v0.0.240
     hooks:
       - id: ruff
   
   - repo: https://github.com/pre-commit/mirrors-mypy
     rev: v1.0.0
     hooks:
       - id: mypy
   ```

#### B.2.2 PostgreSQL 本地开发环境

**方式**：Docker Compose（推荐）

```yaml
# docker-compose.yml
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: ai_agent_dev
      POSTGRES_USER: dev_user
      POSTGRES_PASSWORD: dev_password
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U dev_user"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

**启动命令**：
```bash
docker-compose up -d
```

#### B.2.3 数据库初始化

**目标**：自动化 Schema 创建和测试数据加载

1. [ ] 创建 `infra/scripts/init_db.sh`：
   ```bash
   #!/bin/bash
   # 创建生产 Schema
   psql -h localhost -U dev_user -d ai_agent_dev < infra/sql/schema.sql
   
   # 创建测试 Schema
   psql -h localhost -U dev_user -d ai_agent_test < infra/sql/test_schema.sql
   ```

2. [ ] 编写 SQLAlchemy Migration 脚本（使用 Alembic）
3. [ ] 准备测试数据集 fixture

#### B.2.4 IDE 快速启动

**VS Code 配置**：
```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
  "python.linting.enabled": true,
  "python.linting.pylintEnabled": false,
  "python.linting.ruffEnabled": true,
  "python.formatting.provider": "black",
  "[python]": {
    "editor.defaultFormatter": "ms-python.python",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
      "source.organizeImports": true
    }
  }
}
```

---

### B.3 开发指南编写（第 2 周）

**时间**：2026-10-17 ~ 2026-10-20  
**负责人**：开发 Lead + 文档管理员  
**产出物**：`docs/development/QUICK_START.md`、`docs/development/CODING_STANDARDS.md`

#### B.3.1 快速开发指南（QUICK_START.md）

```markdown
# 快速开发指南

## 环境要求
- Python 3.11+
- Docker & Docker Compose
- Node.js 18+（前端，未来）

## 一分钟开始

### 1. 克隆代码并进入目录
git clone <repo>
cd Ai_agent

### 2. 初始化开发环境
make setup

### 3. 启动服务
make dev

### 4. 运行测试
make test

## 常用命令
- make lint      # 检查代码风格
- make format    # 格式化代码
- make type      # 类型检查
- make test-cov  # 测试 + 覆盖率
- make docs      # 生成文档
```

#### B.3.2 编码规范（CODING_STANDARDS.md）

- [ ] 文件组织规范
- [ ] 命名约定（文件、类、函数、常量）
- [ ] 代码注释要求
- [ ] Git 提交规范
- [ ] 测试要求（单元测试最低覆盖率 70%）
- [ ] API 设计规范

---

### B.4 持续集成配置（第 2 周）

**时间**：2026-10-17 ~ 2026-10-20  
**负责人**：基础设施团队  
**产出物**：GitHub Actions CI/CD 流水线

#### B.4.1 创建 GitHub Actions 工作流

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main, develop ]

jobs:
  test:
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: postgres:15-alpine
        env:
          POSTGRES_DB: ai_agent_test
          POSTGRES_PASSWORD: test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      
      redis:
        image: redis:7-alpine
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r requirements-dev.txt
      
      - name: Lint with ruff
        run: ruff check src/
      
      - name: Format check with black
        run: black --check src/
      
      - name: Type check with mypy
        run: mypy src/
      
      - name: Run tests
        run: pytest tests/ --cov=src --cov-report=xml
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          files: ./coverage.xml
```

---

## 四、时间表与交付物

### 周期：2026-10-10 ~ 2026-10-20（2 周）

| 周 | 日期 | 轨 A（评审） | 轨 B（环境准备） | 交付物 |
|----|------|------------|---------------|--------|
| 1 | 10-10~10-11 | 准备阶段：汇总材料、识别问题 | 创建目录结构、初始化配置文件 | 评审准备包 |
| 1 | 10-12~10-13 | 第 1 次评审会（P0 问题） | Docker 配置、数据库初始化 | 问题决议 |
| 1 | 10-14~10-15 | 修改与补充、投票 | 环境搭建完成 | 冻结预案 |
| 2 | 10-16~10-18 | 最终投票与冻结 | 开发指南编写 | Runtime v1.0、Security v1.0 冻结版 |
| 2 | 10-19~10-20 | 事后总结 | 快速启动文档 | 可用开发环境、QUICK_START.md |

---

## 五、风险与应急预案

### 风险 1：评审周期延长（概率中）

**触发条件**：
- EVA-006 拒绝 Error Budget 新增
- Runtime Contract 版本管理有重大分歧

**应急措施**：
- 延迟评审 1 周（新期限 2026-10-25）
- 评审变更为"边实施边评审"模式（降低优先级）

### 风险 2：开发环境搭建困难（概率低）

**触发条件**：
- Docker 镜像兼容性问题
- 数据库初始化失败

**应急措施**：
- 提供云端 DevBox（临时方案）
- 准备 Windows + WSL2 支持文档

### 风险 3：新增接口问题（概率中）

**触发条件**：
- 评审中发现未列出的接口冲突
- 跨模块依赖发现遗漏

**应急措施**：
- P0 问题立即停会讨论
- P1 问题加入追踪表，第 2 周评审

---

## 六、成功标准

### 轨 A 成功标准

- [ ] 所有 P0 问题已闭环
- [ ] Runtime Contract v1.0 获得 ≥80% 投票通过
- [ ] Security Baseline v1.0 获得 ≥80% 投票通过
- [ ] 签署冻结记录，所有相关人确认
- [ ] 无阻塞风险进入阶段 1

### 轨 B 成功标准

- [ ] 项目目录结构已创建
- [ ] `make setup` 能在 1 分钟内完成环境初始化
- [ ] `make dev` 能成功启动所有本地服务
- [ ] `make test` 能通过所有测试
- [ ] QUICK_START.md 文档完整
- [ ] 新成员能在 30 分钟内独立完成开发环境搭建

---

## 七、下一步（阶段 1 启动准备）

### Go/No-Go 决策（2026-10-20）

**入场条件**：
- ✓ Runtime Contract v1.0 冻结
- ✓ Security Baseline v1.0 冻结
- ✓ 开发环境可用
- ✓ 所有 P0 问题已闭环
- ✓ 技术栈确认无异议

**决策权**：技术总负责人

**预期结果**：通过（除非有重大遗漏风险）

### 【阶段 1】启动内容（2026-10-20 ~ 2026-12-15）

- **1.1 Walking Skeleton**（第 1-2 周）：事件存储 + 状态投影 + 简单 Action 执行
- **1.2 核心运行时**（第 3-4 周）：状态机、检查点、幂等性
- **1.3 基础安全**（第 5-6 周）：RBAC、Policy Gateway、沙箱
- **1.4 基础工具集**（第 7-8 周）：文件、Git、测试工具
- **1.5 简单 Worker**（第 9-10 周）：Coder Worker、ReAct Loop、端到端测试

---

**文档所有者**：架构团队  
**更新频率**：每周一次进度更新  
**联系方式**：[待填写]
