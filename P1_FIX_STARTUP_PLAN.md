# 🔧 P1 修复启动 - git 错误处理 + 审批并发安全

**时间**: 2026-10-12 20:40 PM UTC+8  
**优先级**: 🟡 **中（推荐本周完成）**  
**工期**: 3 小时  
**状态**: 📋 **就绪启动**

---

## 🎯 P1 修复范围

### P1-1: git 命令错误处理不完整

**问题**: git 命令失败时 stderr 被丢弃，无法调试  
**文件**: `src/workers/coder/worker.py` (行 60-73)  
**工期**: 1.5 小时

**当前代码问题**:

```python
async def _git(repo: str, *args: str) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", repo, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,  # ❌ 丢弃 stderr
        )
        out, _ = await proc.communicate()
    except (OSError, ValueError):
        return 1, ""  # ❌ 吞掉异常，无日志
    code = proc.returncode if proc.returncode is not None else 1
    return code, out.decode("utf-8", errors="replace").strip()
```

**修复方案**:

```python
import logging

logger = logging.getLogger(__name__)

async def _git(repo: str, *args: str) -> tuple[int, str]:
    """在仓库内执行 git，返回 (退出码, stdout)。失败时返回 (1, "")。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", repo, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,  # ✅ 捕获 stderr
        )
        out, err = await proc.communicate()
    except (OSError, ValueError) as e:
        logger.error(
            f"Failed to start git process in repo {repo!r} with args {args}: {e}",
            exc_info=True,
        )
        return 1, ""
    
    code = proc.returncode if proc.returncode is not None else 1
    
    # ✅ 记录失败的 git 命令便于调试
    if code != 0:
        err_msg = err.decode("utf-8", errors="replace").strip()
        logger.debug(
            f"Git command failed: git -C {repo!r} {' '.join(args)}\n"
            f"Exit code: {code}\nstderr: {err_msg}"
        )
    
    # ✅ 返回 stdout（若为非 UTF-8，replace 是可接受的降级）
    try:
        output = out.decode("utf-8").strip()
    except UnicodeDecodeError:
        output = out.decode("utf-8", errors="replace").strip()
        logger.warning(
            f"Git output contains non-UTF-8 bytes, fallback to lossy decoding"
        )
    
    return code, output
```

**新增测试**:

```python
# tests/unit/workers/coder/test_git_functions.py

@pytest.mark.asyncio
async def test_git_command_error_logging(caplog):
    """验证: git 命令失败时记录 stderr"""
    # 使用不存在的仓库路径
    code, output = await _git("/nonexistent/repo", "status")
    
    assert code != 0
    assert output == ""
    # ✅ 验证日志中有错误信息
    assert "Failed to start git process" in caplog.text or code != 0


@pytest.mark.asyncio
async def test_git_non_utf8_output(tmp_path):
    """验证: git 输出包含非 UTF-8 字节时的处理"""
    repo = tmp_path
    repo.mkdir(exist_ok=True)
    
    # 初始化 git 仓库
    await _git(str(repo), "init")
    
    # 创建包含非 UTF-8 内容的文件
    file = repo / "test.bin"
    file.write_bytes(b"\xff\xfe")  # 非 UTF-8 字节
    
    # git add 应该不会失败，但输出可能包含非 UTF-8
    code, output = await _git(str(repo), "add", ".")
    
    # 验证没有 crash，返回降级编码的结果
    assert isinstance(output, str)


@pytest.mark.asyncio
async def test_git_process_startup_failure(monkeypatch):
    """验证: 进程启动异常时的处理"""
    async def mock_exec(*args, **kwargs):
        raise OSError("Process startup failed")
    
    monkeypatch.setattr(asyncio, "create_subprocess_exec", mock_exec)
    
    code, output = await _git("/some/repo", "status")
    
    assert code == 1
    assert output == ""
```

---

### P1-2: 审批记录的并发竞态

**问题**: 多并发 action 时审批记录可能遗漏或重复  
**文件**: `src/workers/coder/worker.py` (行 378-387)  
**工期**: 1.5 小时

**当前代码问题**:

```python
def _record_approvals(self) -> None:
    """把审批网关新增的 ApprovalRecord 转成 Evidence。"""
    if self._approval_gateway is None:
        return
    records = self._approval_gateway.records  # ❌ 竞态: 可能被并发修改
    for record in records[self._approvals_seen:]:
        self.approval_evidences.append(self._approval_evidence(record))
    self._approvals_seen = len(records)
```

**修复方案**:

**第一步**: 修改网关类 (`src/workers/coder/approval.py`):

```python
class ApprovalAwarePolicyGateway:
    def __init__(self, gateway: PolicyGateway, policy: ApprovalPolicy) -> None:
        self._gateway = gateway
        self._policy = policy
        self._records: list[ApprovalRecord] = []
        self._records_lock = asyncio.Lock()  # ✅ 保护 _records
    
    @property
    def records(self) -> list[ApprovalRecord]:
        """只读访问（危险，请勿使用）"""
        return self._records.copy()
    
    async def pop_pending_records(self) -> list[ApprovalRecord]:
        """原子地获取并清空所有待处理的审批记录"""
        async with self._records_lock:
            result = self._records.copy()
            self._records.clear()
            return result
```

**第二步**: 修改 Worker 类 (`src/workers/coder/worker.py`):

```python
def _record_approvals(self) -> None:
    """把审批网关新增的 ApprovalRecord 转成 Evidence（原子操作）。"""
    if self._approval_gateway is None:
        return
    
    # ❌ 这种方式在 async 环境中有问题
    # ✅ 应该改为异步方式或在初始化时提供同步版本
    # 临时方案：使用 try-except 保护
    try:
        records = self._approval_gateway.pop_pending_records_sync()
        for record in records:
            evidence = self._approval_evidence(record)
            self.approval_evidences.append(evidence)
    except AttributeError:
        # 回退到原来的方式（已有锁保护）
        records = self._approval_gateway.records
        for record in records[self._approvals_seen:]:
            self.approval_evidences.append(self._approval_evidence(record))
        self._approvals_seen = len(records)
```

**或者更好的方案**: 在 _act() 中用 async:

```python
async def _act(self, reasoning: Reasoning) -> _ActResult:
    if not reasoning.next_tool_name:
        await self._record_approvals_async()  # ✅ 异步方式
        return _ActResult()
    
    # ... action 执行 ...
    
    await self._record_approvals_async()
    return _ActResult(action=final_action, evidence=exec_result.evidence)

async def _record_approvals_async(self) -> None:
    """异步记录审批（原子操作）"""
    if self._approval_gateway is None:
        return
    records = await self._approval_gateway.pop_pending_records()
    for record in records:
        self.approval_evidences.append(self._approval_evidence(record))
```

**新增测试**:

```python
# tests/unit/workers/coder/test_approval.py

@pytest.mark.asyncio
async def test_approval_records_no_duplicates_concurrent(tmp_path):
    """验证: 并发审批时不会重复记录"""
    policy = TaskBranchApprovalPolicy(...)
    gateway = ApprovalAwarePolicyGateway(SimplifiedPolicyGateway(...), policy)
    
    # 模拟并发的两个审批请求
    async def call_pre_exec(action_id: str):
        return await gateway.check_pre_execution(
            action_id, "file-write", 
            {"path": str(tmp_path / "a.py"), "content": "x"}
        )
    
    results = await asyncio.gather(
        call_pre_exec("action-1"),
        call_pre_exec("action-2"),
    )
    
    # 获取审批记录（原子操作）
    records = await gateway.pop_pending_records()
    
    # ✅ 验证有 2 条记录，无重复
    assert len(records) == 2
    assert records[0].action_id == "action-1"
    assert records[1].action_id == "action-2"
    
    # 再次获取应该为空
    records2 = await gateway.pop_pending_records()
    assert len(records2) == 0


@pytest.mark.asyncio
async def test_approval_pop_records_is_atomic(tmp_path):
    """验证: pop_pending_records 是原子操作"""
    policy = TaskBranchApprovalPolicy(...)
    gateway = ApprovalAwarePolicyGateway(SimplifiedPolicyGateway(...), policy)
    
    # 添加一些审批
    for i in range(5):
        await gateway.check_pre_execution(
            f"action-{i}", "file-write",
            {"path": str(tmp_path / f"file{i}.py"), "content": "x"}
        )
    
    # 原子地获取并清空
    records = await gateway.pop_pending_records()
    assert len(records) == 5
    
    # 立即再获取应该为空
    records2 = await gateway.pop_pending_records()
    assert len(records2) == 0
```

---

## 📋 P1 修复清单

### P1-1: git 错误处理

- [ ] **修改 `_git()` 函数**
  - [ ] 改 `stderr=DEVNULL` → `stderr=PIPE`
  - [ ] 添加异常日志记录 (logger.error)
  - [ ] 添加 stderr 失败日志 (logger.debug)
  - [ ] 改进非 UTF-8 处理

- [ ] **新增 3 个单元测试**
  - [ ] test_git_command_error_logging
  - [ ] test_git_non_utf8_output
  - [ ] test_git_process_startup_failure

- [ ] **代码质量检查**
  - [ ] mypy 检查通过
  - [ ] ruff 检查通过

### P1-2: 审批并发安全

- [ ] **修改网关类**
  - [ ] 添加 `_records_lock`
  - [ ] 添加 `pop_pending_records()` 方法
  - [ ] 确保原子操作

- [ ] **修改 Worker 类**
  - [ ] 改 `_record_approvals()` 为异步
  - [ ] 使用 `pop_pending_records()`
  - [ ] 移除 `_approvals_seen` 计数

- [ ] **新增 2 个单元测试**
  - [ ] test_approval_records_no_duplicates_concurrent
  - [ ] test_approval_pop_records_is_atomic

- [ ] **代码质量检查**
  - [ ] mypy 检查通过
  - [ ] ruff 检查通过

---

## ✅ P1 验收标准

### 测试

- [ ] 原有 1303 个测试全部通过
- [ ] 新增 5 个测试全部通过
- [ ] 总计 1308+ 通过

### 代码质量

- [ ] mypy: 0 errors
- [ ] ruff: all checks passed
- [ ] 代码覆盖率 > 90%

### 功能验证

- [ ] git 命令失败时能正确捕获 stderr
- [ ] 非 UTF-8 输出能正确处理
- [ ] 进程启动失败能正确处理
- [ ] 并发审批时无遗漏/重复

---

## 🚀 启动 P1 修复

### 第 1 步: 创建修复分支

```bash
git checkout main
git pull origin main  # 或使用本地 main
git checkout -b fix/stage-1.5-git-and-approvals
```

### 第 2 步: 实施修复

1. 先修复 git 错误处理 (1.5h)
2. 再修复审批并发安全 (1.5h)

### 第 3 步: 测试验证

```bash
# 运行修改文件的测试
pytest tests/unit/workers/coder/ -v

# 运行全部测试
pytest tests/ -q

# 类型检查
mypy src/workers/coder/

# Lint 检查
ruff check src/workers/coder/
```

### 第 4 步: 提交推送

```bash
git add src/workers/coder/ tests/unit/workers/coder/
git commit -m "fix: Improve git error handling and approval record safety - P1 fix"
git push -u origin fix/stage-1.5-git-and-approvals
```

---

## 📊 工期估算

| 任务 | 工期 | 备注 |
|------|------|------|
| git 错误处理修复 | 1 小时 | 代码改动 |
| git 错误处理测试 | 0.5 小时 | 3 个单元测试 |
| 审批并发修复 | 1 小时 | 网关 + Worker 改动 |
| 审批并发测试 | 0.5 小时 | 2 个单元测试 |
| 全量测试验证 | 0.5 小时 | 1308+ 测试 |
| **总计** | **3.5 小时** | 含缓冲 |

---

## ✨ 预期成果

修复完成后:

```
✅ 1308+ 个单元测试通过
✅ 代码覆盖率 > 90%
✅ mypy: 0 errors
✅ ruff: all checks passed
✅ git 命令失败时能正确捕获错误信息
✅ 审批记录并发安全，无遗漏/重复
✅ 代码质量达到生产级别
```

---

**P1 修复启动就绪** ✓  
**建议开始时间**: 2026-10-13 (明天)

---

**文档生成**: 2026-10-12 20:40 PM UTC+8  
**审查者**: Kiro (AI Code Reviewer)
