# 🔧 修复计划：阶段 1.5 Coder Worker 代码审查发现

**日期**: 2026-10-12  
**优先级**: P0 (2h) + P1 (3h) + P2 (2h) + P3 (4h) = 总计 11 小时  
**建议**: 在推进阶段 2 前完成 P0 和 P1

---

## 📋 修复清单

### ⚠️ P0（高优先级，2 小时）

#### 【P0-1】ReActLoop 迭代上限检查的精确性

**文件**: `src/workers/react_loop/loop.py`  
**问题**: 迭代上限检查在增加计数后进行，导致可能执行超过 max_iterations 的迭代

**当前代码** (行 220-235):

```python
async def _run_iteration(self) -> bool:
    try:
        # ❌ 问题: 先增加 iteration，再检查上限，导致可能超额执行
        self._check_timeout()
        self._check_iteration_limit()  # 检查 current >= max_iterations
        self._current_iteration += 1   # 然后增加（此时 current 已经 > max_iterations-1）
        
        # 最后的预算检查在执行后，无法有效阻止超额
        self._check_budget()
```

**修复方案**:

```python
async def _run_iteration(self) -> bool:
    """执行一次完整的 Observe → Reason → Act 迭代"""
    try:
        # ✅ 修复: 在执行前检查所有约束
        self._check_timeout()
        
        # ✅ 在增加计数前检查上限
        if self._current_iteration >= self.config.max_iterations:
            raise ReActLoopBudgetExceededError(
                f"Max iterations reached: {self._current_iteration} >= {self.config.max_iterations}"
            )
        
        self._current_iteration += 1  # 现在增加是安全的
        
        # ... observe / reason / act ...
        
        # ✅ 每个阶段后即时检查预算，失败立即中止
        self._check_budget(reasoning)  # 在推理后检查
        self._check_budget()           # 在 action 后再检查
        
        return True
        
    except ReActLoopBudgetExceededError as e:
        self._termination_reason = str(e)
        self._forced_termination = True
        logger.warning(f"Loop {self.loop_id} terminated: {e}")
        return False
```

**测试方案** (新增):

```python
@pytest.mark.asyncio
async def test_loop_respects_max_iterations_strictly(valid_config, trace_context):
    """验证: max_iterations=3 时，恰好执行 3 轮，第 4 轮完全不执行"""
    observations = [Observation(iteration=i, ...) for i in range(1, 10)]
    reasonings = [
        Reasoning(iteration=i, should_continue=True, ...) 
        for i in range(1, 10)
    ]
    
    observer = AsyncMock(side_effect=observations)
    reasoner = AsyncMock(side_effect=reasonings)
    actor = AsyncMock()
    
    config = ReActLoopConfig(max_iterations=3, timeout_seconds=60)
    
    loop = ReActLoop(
        loop_id=generate_entity_id(),
        worker_id="test",
        task_id="test",
        config=config,
        observer=observer,
        reasoner=reasoner,
        actor=actor,
        trace_context=trace_context,
    )
    
    result = await loop.run()
    
    # ✅ 验证
    assert result.iteration_count == 3
    assert observer.call_count == 3  # 恰好 observe 3 次
    assert reasoner.call_count == 3  # 恰好 reason 3 次
    assert actor.call_count == 3     # 恰好 act 3 次（第 4 轮没有执行任何东西）
    assert result.succeeded is False
    assert "Max iterations reached" in result.termination_reason
```

**工期**: 1 小时（改动 + 测试）

---

### 🔧 P1（中优先级，3 小时）

#### 【P1-1】CoderWorker 的 git 命令缺少错误上下文

**文件**: `src/workers/coder/worker.py` (行 60-73)  
**问题**: git 命令失败时丢弃 stderr，调试困难；异常被吞掉无日志

**当前代码**:

```python
async def _git(repo: str, *args: str) -> tuple[int, str]:
    """在仓库内执行 git，返回 (退出码, stdout)。启动失败时返回 (1, "")。"""
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

**测试方案** (新增):

```python
@pytest.mark.asyncio
async def test_git_command_error_logging(caplog):
    """验证: git 命令失败时记录 stderr"""
    # 使用不存在的仓库路径
    code, output = await _git("/nonexistent/repo", "status")
    
    assert code != 0
    assert output == ""
    # ✅ 验证日志中有错误信息
    assert "Failed to start git process" in caplog.text or "Exit code" in caplog.text


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
```

**工期**: 1.5 小时（改动 + 集成测试）

---

#### 【P1-2】审批记录的并发安全性

**文件**: `src/workers/coder/worker.py` (行 355-387)  
**问题**: `_approval_gateway.records` 可能被并发修改，导致遗漏或重复

**当前代码**:

```python
def _record_approvals(self) -> None:
    """把审批网关新增的 ApprovalRecord 转成 Evidence。"""
    if self._approval_gateway is None:
        return
    records = self._approval_gateway.records  # ❌ 竞态: records 可能被修改
    for record in records[self._approvals_seen:]:
        self.approval_evidences.append(self._approval_evidence(record))
    self._approvals_seen = len(records)
```

**修复方案**:

假设 `ApprovalAwarePolicyGateway` 提供原子操作接口（如果没有，则需要先修改网关）：

```python
def _record_approvals(self) -> None:
    """把审批网关新增的 ApprovalRecord 转成 Evidence（原子操作）。"""
    if self._approval_gateway is None:
        return
    
    # ✅ 获取并清空所有待处理的审批记录（原子操作）
    records = self._approval_gateway.pop_pending_records()
    
    for record in records:
        evidence = self._approval_evidence(record)
        self.approval_evidences.append(evidence)
```

**网关接口修改** (`src/workers/coder/approval.py`):

```python
class ApprovalAwarePolicyGateway:
    def __init__(self, ...):
        self._records: list[ApprovalRecord] = []
        self._records_lock = asyncio.Lock()  # ✅ 保护 _records
    
    @property
    def records(self) -> list[ApprovalRecord]:
        """只读访问（危险，请勿使用，改用 pop_pending_records()）"""
        return self._records.copy()
    
    async def pop_pending_records(self) -> list[ApprovalRecord]:
        """原子地获取并清空所有待处理的审批记录"""
        async with self._records_lock:
            result = self._records.copy()
            self._records.clear()
            return result
```

**测试方案** (新增):

```python
@pytest.mark.asyncio
async def test_approval_records_no_duplicates(tmp_path):
    """验证: 并发审批时不会重复记录"""
    policy = TaskBranchApprovalPolicy(...)
    gateway = ApprovalAwarePolicyGateway(SimplifiedPolicyGateway(...), policy)
    
    # 模拟并发的两个审批请求
    async def call_pre_exec(action_id: str):
        return await gateway.check_pre_execution(
            action_id, "file-write", {"path": str(tmp_path / "a.py"), "content": "x"}
        )
    
    results = await asyncio.gather(
        call_pre_exec("action-1"),
        call_pre_exec("action-2"),
    )
    
    # 获取审批记录
    records = await gateway.pop_pending_records()
    
    # ✅ 验证有 2 条记录，无重复
    assert len(records) == 2
    assert records[0].action_id == "action-1"
    assert records[1].action_id == "action-2"
    
    # 再次获取应该为空
    records2 = await gateway.pop_pending_records()
    assert len(records2) == 0
```

**工期**: 1.5 小时（接口改动 + 测试）

---

### 📝 P2（低优先级，2 小时）

#### 【P2-1】添加 ReActLoop 日志改进

**文件**: `src/workers/react_loop/loop.py`  
**改进**: 添加结构化日志，便于生产环境监控

**修改**:

```python
import logging

logger = logging.getLogger(__name__)

class ReActLoop:
    async def run(self) -> ReActLoopResult:
        """执行 ReAct 循环"""
        self._start_time = ensure_utc(datetime.now(UTC))
        self._state = ReActLoopState.INITIALIZING
        
        # ✅ 记录开始
        logger.info(
            f"Starting ReActLoop",
            extra={
                "loop_id": self.loop_id,
                "task_id": self.task_id,
                "worker_id": self.worker_id,
                "config": {
                    "max_iterations": self.config.max_iterations,
                    "timeout_seconds": self.config.timeout_seconds,
                    "max_tokens": self.config.max_tokens,
                    "max_cost_cents": self.config.max_cost_cents,
                },
            },
        )
        
        try:
            while True:
                if self._cancelled:
                    raise ReActLoopCancelledException("Loop was cancelled")
                
                try:
                    should_continue = await self._run_iteration()
                except Exception as e:
                    logger.error(
                        f"Iteration failed",
                        extra={
                            "loop_id": self.loop_id,
                            "iteration": self._current_iteration,
                            "error": str(e),
                        },
                        exc_info=True,
                    )
                    raise
                
                if not should_continue:
                    break
            
            # 完成
            self._state = ReActLoopState.FAILED if self._forced_termination else ReActLoopState.COMPLETE
            
            logger.info(
                f"ReActLoop completed",
                extra={
                    "loop_id": self.loop_id,
                    "final_state": self._state.value,
                    "iterations": self._current_iteration,
                    "succeeded": not self._forced_termination,
                    "tokens_consumed": self._total_tokens_consumed,
                    "cost_cents": self._total_cost_cents,
                    "time_ms": self._total_time_ms,
                },
            )
            
            # ... 返回结果 ...
            
        except Exception as e:
            logger.error(
                f"ReActLoop failed",
                extra={"loop_id": self.loop_id, "error": str(e)},
                exc_info=True,
            )
            # ... 错误处理 ...
```

**工期**: 1 小时

---

### 🔨 P3（低优先级，4 小时）

#### 【P3-1】ReActLoopConfig 参数验证

**文件**: `src/workers/react_loop/models.py`

```python
from pydantic import field_validator

class ReActLoopConfig:
    max_iterations: int = Field(default=20, ge=1, le=1000)
    timeout_seconds: int = Field(default=600, ge=1, le=3600)
    max_tokens: int | None = Field(default=None, ge=0)
    max_cost_cents: int | None = Field(default=None, ge=0)
    
    @field_validator("max_iterations")
    @classmethod
    def validate_max_iterations(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("max_iterations must be > 0")
        if v > 1000:
            raise ValueError("max_iterations > 1000 is unreasonable (infinite loop risk)")
        return v
    
    @field_validator("timeout_seconds")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("timeout_seconds must be > 0")
        if v > 3600:
            raise ValueError("timeout_seconds > 3600 (1h) is unreasonable")
        return v
```

**工期**: 1 小时

---

#### 【P3-2】完成闸门的可扩展性

**文件**: `src/workers/coder/worker.py`

```python
from typing import Protocol

class VerificationPolicy(Protocol):
    """可扩展的验证策略"""
    async def verify(self, worker: CoderWorker) -> list[str]:
        """验证逻辑，返回失败原因列表（空列表表示通过）"""
        ...

class CoderWorker:
    def __init__(
        self,
        *,
        spec: CoderTaskSpec,
        ...,
        verification_policies: list[VerificationPolicy] | None = None,
    ) -> None:
        self._policies = verification_policies or [
            _DefaultBranchPolicy(),
            _DefaultCommitPolicy(),
            _DefaultDiffPolicy(),
            _DefaultTestPolicy(),
        ]
    
    async def _verify(self) -> VerificationReport:
        """执行所有验证策略"""
        failures: list[str] = []
        for policy in self._policies:
            failures.extend(await policy.verify(self))
        return VerificationReport(passed=not failures, failures=failures)
```

**工期**: 2 小时

---

## 📊 修复优先级矩阵

| 问题 | 优先级 | 风险 | 工期 | ROI |
|-----|--------|------|------|-----|
| ReActLoop 迭代上限 | P0 | 高 | 1h | 高 |
| git 命令错误处理 | P1 | 中 | 1.5h | 中 |
| 审批记录并发安全 | P1 | 中 | 1.5h | 中 |
| 日志改进 | P2 | 低 | 1h | 低 |
| 参数验证 | P3 | 低 | 1h | 低 |
| 完成闸门可扩展性 | P3 | 低 | 2h | 低 |

---

## ✅ 完成标准

- [ ] 所有 P0 修复完成并通过单元测试
- [ ] 所有 P1 修复完成并通过集成测试
- [ ] 代码审查通过（mypy 0 errors, ruff 0 errors）
- [ ] 新增测试用例 50+ 个
- [ ] 总测试数 1302 → 1350+
- [ ] 测试通过率保持 100%
- [ ] 代码覆盖率 > 90%

---

## 🚀 实施建议

### 第一步（P0，1 天）
```bash
git checkout -b fix/stage-1.5-react-loop-iteration-limit
# 修复 ReActLoop 迭代上限检查
# 新增测试
git push origin fix/stage-1.5-react-loop-iteration-limit
```

### 第二步（P1，1.5 天）
```bash
git checkout -b fix/stage-1.5-git-and-approvals
# 修复 git 命令错误处理
# 改进审批记录并发安全性
# 新增测试
git push origin fix/stage-1.5-git-and-approvals
```

### 第三步（P2+P3，1 天，可选）
```bash
git checkout -b improve/stage-1.5-logging-and-extensibility
# 添加日志改进
# 参数验证
# 完成闸门可扩展性
git push origin improve/stage-1.5-logging-and-extensibility
```

---

**修复计划完成**: 2026-10-12 11:45 AM UTC+8
