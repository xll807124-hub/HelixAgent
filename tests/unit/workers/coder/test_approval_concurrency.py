"""
测试 ApprovalAwarePolicyGateway 的并发安全性

对齐: REQ-SEC-003 (Policy Gateway) + 并发安全
"""
import asyncio

import pytest

from src.security.policy_gateway.base import PolicyDecision, PolicyGateway, PolicyResult
from src.workers.coder.approval import (
    ApprovalAwarePolicyGateway,
    TaskBranchApprovalPolicy,
)


class MockPolicyGateway(PolicyGateway):
    """模拟的底层 Policy Gateway"""
    
    async def check_pre_execution(self, action_id, tool_name, params, context):
        # 对于 file-write 返回 REQUIRES_APPROVAL
        if tool_name == "file-write":
            return PolicyResult(decision=PolicyDecision.REQUIRES_APPROVAL)
        return PolicyResult(decision=PolicyDecision.ALLOW)
    
    async def check_post_execution(self, action_id, tool_name, output, context):
        return PolicyResult(decision=PolicyDecision.ALLOW)


async def create_approval_gateway(task_branch="feature/test"):
    """创建测试用的审批网关"""
    inner = MockPolicyGateway()
    policy = TaskBranchApprovalPolicy(
        repo_path="/tmp/test_repo",
        task_branch=task_branch,
        base_branch="main",
        allowed_paths=["/tmp/test_repo"],
        branch_provider=lambda: asyncio.sleep(0, task_branch),  # 返回 task_branch
    )
    return ApprovalAwarePolicyGateway(inner, policy)


@pytest.mark.asyncio
async def test_approval_records_no_duplicates_concurrent():
    """验证: 并发审批时不会重复记录"""
    gateway = await create_approval_gateway()
    
    # 模拟并发的多个审批请求
    async def call_pre_exec(action_id: str):
        return await gateway.check_pre_execution(
            action_id,
            "file-write",
            {"path": "/tmp/test_repo/file.py"},
            {"allowed_paths": ["/tmp/test_repo"]},
        )
    
    # 并发执行 5 个审批请求
    results = await asyncio.gather(
        call_pre_exec("action-1"),
        call_pre_exec("action-2"),
        call_pre_exec("action-3"),
        call_pre_exec("action-4"),
        call_pre_exec("action-5"),
    )
    
    # ✅ 验证所有都是 ALLOW（自动批准）
    for result in results:
        assert result.decision == PolicyDecision.ALLOW
    
    # ✅ 验证有 5 条记录，无重复
    records = gateway.records
    assert len(records) == 5
    assert len(set(r.action_id for r in records)) == 5


@pytest.mark.asyncio
async def test_approval_pop_records_is_atomic():
    """验证: pop_pending_records 是原子操作"""
    gateway = await create_approval_gateway()
    
    # 添加一些审批
    for i in range(5):
        await gateway.check_pre_execution(
            f"action-{i}",
            "file-write",
            {"path": "/tmp/test_repo/file.py"},
            {"allowed_paths": ["/tmp/test_repo"]},
        )
    
    # 原子地获取并清空
    records = await gateway.pop_pending_records()
    assert len(records) == 5
    
    # ✅ 验证立即再获取应该为空
    records2 = await gateway.pop_pending_records()
    assert len(records2) == 0
    
    # ✅ 验证 gateway.records 也是空
    assert len(gateway.records) == 0


@pytest.mark.asyncio
async def test_pop_records_concurrent_no_loss():
    """验证: 并发调用 pop_pending_records 时不会丢失记录"""
    gateway = await create_approval_gateway()
    
    # 添加一些审批
    for i in range(10):
        await gateway.check_pre_execution(
            f"action-{i}",
            "file-write",
            {"path": "/tmp/test_repo/file.py"},
            {"allowed_paths": ["/tmp/test_repo"]},
        )
    
    # 并发地 pop（虽然通常只有一个线程会 pop，但也要处理竞态）
    results = await asyncio.gather(
        gateway.pop_pending_records(),
        gateway.pop_pending_records(),
        gateway.pop_pending_records(),
    )
    
    # ✅ 验证: 一个 pop 返回全部记录，其他返回空
    total_records = sum(len(r) for r in results)
    assert total_records == 10
    
    # ✅ 验证最后是空
    final = await gateway.pop_pending_records()
    assert len(final) == 0


@pytest.mark.asyncio
async def test_approval_record_action_ids_unique():
    """验证: 每条审批记录的 action_id 唯一"""
    gateway = await create_approval_gateway()
    
    action_ids = [f"action-{i}" for i in range(10)]
    
    # 并发执行
    await asyncio.gather(*[
        gateway.check_pre_execution(
            action_id,
            "file-write",
            {"path": "/tmp/test_repo/file.py"},
            {"allowed_paths": ["/tmp/test_repo"]},
        )
        for action_id in action_ids
    ])
    
    records = await gateway.pop_pending_records()
    
    # ✅ 验证: 10 条记录，10 个唯一 action_id
    assert len(records) == 10
    assert len(set(r.action_id for r in records)) == 10
    
    # ✅ 验证: action_id 都在预期列表中
    recorded_ids = {r.action_id for r in records}
    assert recorded_ids == set(action_ids)


@pytest.mark.asyncio
async def test_approval_records_property_returns_copy():
    """验证: records 属性返回副本，修改副本不影响内部状态"""
    gateway = await create_approval_gateway()
    
    await gateway.check_pre_execution(
        "action-1",
        "file-write",
        {"path": "/tmp/test_repo/file.py"},
        {"allowed_paths": ["/tmp/test_repo"]},
    )
    
    # 获取 records 副本
    records1 = gateway.records
    assert len(records1) == 1
    
    # 修改副本（清空）
    records1.clear()
    assert len(records1) == 0
    
    # ✅ 验证: 内部状态不变
    records2 = gateway.records
    assert len(records2) == 1


@pytest.mark.asyncio
async def test_concurrent_append_then_pop():
    """验证: 并发追加和 pop 的完整流程"""
    gateway = await create_approval_gateway()
    
    async def add_approvals(count: int):
        """添加 count 条审批"""
        for i in range(count):
            await gateway.check_pre_execution(
                f"action-task1-{i}",
                "file-write",
                {"path": "/tmp/test_repo/file.py"},
                {"allowed_paths": ["/tmp/test_repo"]},
            )
    
    # 并发添加
    await asyncio.gather(
        add_approvals(5),
        add_approvals(5),
        add_approvals(5),
    )
    
    # ✅ 验证总共 15 条（不应该有丢失）
    records = await gateway.pop_pending_records()
    assert len(records) == 15
    
    # ✅ 再 pop 应该为空
    records2 = await gateway.pop_pending_records()
    assert len(records2) == 0
