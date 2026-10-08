# HelixAgent 贡献指南

欢迎参与 HelixAgent 的开发！本指南将帮助你了解项目结构、开发流程和代码规范。

---

## 📋 目录

- [项目状态](#项目状态)
- [开发环境](#开发环境)
- [代码规范](#代码规范)
- [分支策略](#分支策略)
- [提交规范](#提交规范)
- [设计文档规范](#设计文档规范)
- [测试要求](#测试要求)
- [评审流程](#评审流程)

---

## 项目状态

**当前阶段**: 阶段 0 → 阶段 1.1 过渡期（2026-10-08）

- ✅ 60/60 正式基线需求详细设计完成
- ⏳ 跨模块评审进行中（建议 2026-10-10~11）
- ⏳ Runtime Contract v1.0 待冻结
- ⏳ 阶段 1.1 (Walking Skeleton) 准备启动

**参考文档**:
- [项目开发执行手册](./项目开发执行手册.md) - 完整开发流程
- [阶段 1.1 启动检查清单](./docs/review/阶段1.1启动前置检查清单-2026-10-08.md)
- [跨模块评审议程](./docs/review/跨模块评审启动议程-2026-10-08.md)

---

## 开发环境

### 前置要求

- Python 3.11+
- Git
- Docker (用于沙箱测试)

### 安装步骤

```bash
# 1. 克隆仓库
git clone git@github.com:xll807124-hub/HelixAgent.git
cd HelixAgent

# 2. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. 安装依赖
pip install -e ".[dev]"

# 4. 运行测试验证
pytest tests/
```

### IDE 配置

推荐使用 VSCode + Python 扩展：

```json
// .vscode/settings.json
{
  "python.defaultInterpreterPath": ".venv/bin/python",
  "python.linting.enabled": true,
  "python.linting.ruffEnabled": true,
  "python.formatting.provider": "black",
  "editor.formatOnSave": true,
  "editor.codeActionsOnSave": {
    "source.organizeImports": true
  }
}
```

---

## 代码规范

### Python 风格

遵循 [PEP 8](https://pep8.org/) + 项目扩展规则：

```python
# ✅ 好的示例
from runtime.entities import Task, Action
from runtime.event_store import EventStore

def create_task(task_id: str, description: str) -> Task:
    """创建新任务实例
    
    Args:
        task_id: 任务唯一标识
        description: 任务描述
        
    Returns:
        Task: 创建的任务实体
        
    Raises:
        ValueError: 当 task_id 为空时
    """
    if not task_id:
        raise ValueError("task_id cannot be empty")
    
    return Task(
        task_id=task_id,
        description=description,
        status="PENDING"
    )
```

### 工具配置

项目使用以下工具强制代码质量：

- **Ruff**: 快速 linter（替代 Flake8 + isort）
- **Black**: 代码格式化
- **MyPy**: 类型检查
- **Pytest**: 单元测试

```bash
# 运行所有检查
ruff check src/ tests/
black --check src/ tests/
mypy src/
pytest tests/ --cov=src --cov-report=term-missing
```

### 类型注解

所有公开 API 必须有完整类型注解：

```python
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

@dataclass
class ActionResult:
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = None
```

---

## 分支策略

### 分支命名

| 类型 | 前缀 | 示例 |
|------|------|------|
| 功能开发 | `feature/` | `feature/REQ-RT-005-checkpoint` |
| Bug 修复 | `fix/` | `fix/event-store-memory-leak` |
| 文档更新 | `docs/` | `docs/update-contributing-guide` |
| 重构 | `refactor/` | `refactor/projection-layer` |
| 性能优化 | `perf/` | `perf/event-query-index` |

### 工作流程

```bash
# 1. 从 main 创建功能分支
git checkout -b feature/REQ-XX-YYY

# 2. 提交代码
git add .
git commit -m "feat(runtime): implement checkpoint protocol"

# 3. 推送到远程
git push origin feature/REQ-XX-YYY

# 4. 创建 Pull Request
gh pr create --title "feat(runtime): implement checkpoint protocol" \
             --body "实现 REQ-RT-005 Checkpoint Protocol"
```

### 分支保护

`main` 分支受保护，要求：

- ✅ 至少 1 个审批
- ✅ 所有测试通过
- ✅ 代码覆盖率 > 70%
- ✅ Ruff + Black 检查通过

---

## 提交规范

遵循 [Conventional Commits](https://www.conventionalcommits.org/)：

### 格式

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Type 类型

| Type | 说明 | 示例 |
|------|------|------|
| `feat` | 新功能 | `feat(runtime): add idempotency key generation` |
| `fix` | Bug 修复 | `fix(projection): handle concurrent rebuild` |
| `docs` | 文档更新 | `docs(design): complete REQ-EVA-007` |
| `refactor` | 重构 | `refactor(store): extract envelope parsing` |
| `test` | 测试 | `test(runtime): add state machine tests` |
| `perf` | 性能优化 | `perf(trace): reduce sampling overhead` |
| `chore` | 构建/工具 | `chore: update dependencies` |

### Scope 范围

- `runtime` - 运行时模块
- `security` - 安全模块
- `context` - 上下文模块
- `evaluation` - 评估模块
- `design` - 设计文档
- `infra` - 基础设施

### 示例

```bash
# 功能开发
git commit -m "feat(runtime): implement checkpoint save/restore

- Add CheckpointProtocol interface
- Implement file-based checkpoint storage
- Add tests for concurrent checkpoint operations

Refs: REQ-RT-005"

# Bug 修复
git commit -m "fix(projection): prevent race condition in rebuilder

The rebuilder could start multiple times due to missing lock.
Added distributed lock using Redis.

Fixes #123"

# 文档更新
git commit -m "docs(design): complete REQ-EVA-007 detailed design

Covers production feedback, dataset update, and rollback mechanisms.
Includes drift detection, failure loop, and version bundle management.

Refs: REQ-EVA-007"
```

---

## 设计文档规范

### 文档结构

所有详细设计文档遵循统一模板（见 `docs/design-specs/TEMPLATE.md`）：

```markdown
# REQ-XX-NNN: 需求标题

> 需求编号：`REQ-XX-NNN`  
> 优先级：P0/P1/P2  
> 版本：v0.1-designed/v1.0-frozen  
> 负责人：[姓名]  
> 最后更新：YYYY-MM-DD

## 1. 需求定义
## 2. 核心架构
## 3. 接口设计
## 4. 实施计划
## 5. 验收标准
## 6. 依赖清单
```

### 设计变更流程

1. **提出变更**：在 `docs/design-specs/PENDING-REQUIREMENTS.md` 登记新需求
2. **编写设计**：按模板编写详细设计文档
3. **提交 PR**：`docs(design): complete REQ-XX-NNN detailed design`
4. **跨模块评审**：相关模块负责人审阅接口影响
5. **冻结**：更新 `docs/design-specs/00-integrated-design-baseline.md` 状态
6. **通知**：在 Slack/邮件通知所有相关团队

### Schema 定义规范

所有接口 Schema 使用 TypeScript 类型定义（即使后端是 Python）：

```typescript
// ✅ 好的 Schema 定义
interface TaskCreatedEvent {
  event_type: "task.created";
  task_id: string;
  created_by: ActorId;
  description: string;
  priority: "P0" | "P1" | "P2";
  created_at: timestamp;
}

// ❌ 避免模糊定义
interface Task {
  data: any;  // 太宽泛
  metadata: object;  // 缺少具体字段
}
```

---

## 测试要求

### 测试金字塔

```
      /\
     /  \  E2E (5%)
    /----\
   / Unit \ (70%)
  /--------\
 /Integration\ (25%)
```

### 单元测试

- **覆盖率目标**: > 70%
- **命名**: `test_<function>_<scenario>_<expected_result>`
- **隔离**: 使用 mock 隔离外部依赖

```python
# tests/unit/runtime/entities/test_task.py
import pytest
from runtime.entities import Task

def test_create_task_with_valid_params_succeeds():
    """测试：使用有效参数创建任务应成功"""
    task = Task(task_id="T-001", description="Test task")
    
    assert task.task_id == "T-001"
    assert task.status == "PENDING"

def test_create_task_with_empty_id_raises_error():
    """测试：使用空 ID 创建任务应抛出异常"""
    with pytest.raises(ValueError, match="task_id cannot be empty"):
        Task(task_id="", description="Test")
```

### 集成测试

测试多个模块协作：

```python
# tests/integration/runtime/test_task_lifecycle.py
def test_task_creation_to_completion_flow(event_store, projector):
    """测试：任务从创建到完成的完整流程"""
    # 创建任务
    task_id = create_task("Fix bug #123")
    
    # 执行 Action
    action_id = execute_action(task_id, "read_file", {"path": "main.py"})
    
    # 记录 Evidence
    record_evidence(action_id, "File content retrieved")
    
    # 完成任务
    complete_task(task_id)
    
    # 验证状态
    projection = projector.get_task_projection(task_id)
    assert projection.status == "COMPLETED"
    assert len(projection.actions) == 1
```

### 运行测试

```bash
# 所有测试
pytest tests/

# 单元测试
pytest tests/unit/

# 集成测试
pytest tests/integration/

# 带覆盖率
pytest tests/ --cov=src --cov-report=html

# 仅失败的测试
pytest tests/ --lf

# 详细输出
pytest tests/ -v -s
```

---

## 评审流程

### Pull Request 清单

提交 PR 前确认：

- [ ] 代码通过所有检查（Ruff + Black + MyPy）
- [ ] 单元测试覆盖率 > 70%
- [ ] 更新相关文档
- [ ] PR 描述清晰（背景、变更、测试）
- [ ] 关联 Issue/需求编号

### PR 模板

```markdown
## 变更描述
简要描述本次 PR 的目的和主要变更

## 变更类型
- [ ] 新功能
- [ ] Bug 修复
- [ ] 重构
- [ ] 文档更新
- [ ] 性能优化

## 测试
- [ ] 添加了单元测试
- [ ] 添加了集成测试
- [ ] 手动测试通过

## 关联需求
Refs: REQ-XX-NNN 或 Fixes #123

## 截图/日志
（如适用）
```

### 评审原则

**评审者应检查**：

1. **功能正确性**: 是否满足需求？
2. **代码质量**: 是否清晰、可维护？
3. **测试充分性**: 是否覆盖边界情况？
4. **接口影响**: 是否影响其他模块？
5. **安全风险**: 是否引入漏洞？
6. **性能影响**: 是否有性能回归？

**评审反馈规范**：

```markdown
# ✅ 建设性反馈
**建议**: 这里的异常处理可以更具体，捕获 `FileNotFoundError` 而非 `Exception`

**问题**: L45 的循环可能导致性能问题，建议批量查询

# ❌ 非建设性反馈
这代码写得不行
```

---

## 常见问题

### Q: 如何更新依赖？

```bash
# 1. 更新 pyproject.toml
# 2. 重新安装
pip install -e ".[dev]"
# 3. 提交 PR
git commit -m "chore: update dependencies"
```

### Q: 测试失败怎么办？

```bash
# 1. 查看详细错误
pytest tests/ -v -s --tb=long

# 2. 单独运行失败的测试
pytest tests/unit/runtime/test_task.py::test_create_task

# 3. 使用 pdb 调试
pytest tests/ --pdb
```

### Q: 如何本地运行 CI 检查？

```bash
# 运行所有检查（模拟 CI）
./scripts/ci-check.sh

# 或手动运行
ruff check src/ tests/
black --check src/ tests/
mypy src/
pytest tests/ --cov=src --cov-report=term-missing
```

---

## 资源链接

- **设计文档**: [docs/design-specs/](./docs/design-specs/)
- **开发手册**: [项目开发执行手册.md](./项目开发执行手册.md)
- **需求清单**: [PENDING-REQUIREMENTS.md](./docs/design-specs/PENDING-REQUIREMENTS.md)
- **接口参考**: [G01-RUNTIME-CONTRACT-INTERFACE-REFERENCE.md](./docs/design-specs/G01-RUNTIME-CONTRACT-INTERFACE-REFERENCE.md)

---

## 联系方式

| 问题类型 | 联系方式 |
|---------|---------|
| 设计问题 | 在 GitHub Discussions 提问 |
| Bug 报告 | 在 GitHub Issues 提交 |
| 功能建议 | 在 GitHub Issues 提交 |
| 紧急问题 | Slack #helixagent-dev |

---

**感谢你的贡献！** 🎉

---

_最后更新: 2026-10-08_
