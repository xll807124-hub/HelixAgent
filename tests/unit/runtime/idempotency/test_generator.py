"""
单元测试：src/runtime/idempotency/generator.py

测试覆盖：
- IdempotencyKeyGenerator 幂等键生成
- 确定性生成（相同输入不同时间调用产生不同键，但逻辑一致性通过账本校验）
- 请求摘要计算委托
- 作用域一致性验证

验收标准：
- 生成的键格式正确（idem-{uuid}）
- 不同调用产生不同键（UUID v7 高熵）
- 请求摘要计算委托给 RequestDigestCalculator
- 作用域一致性校验正确
"""

import pytest

from src.runtime.idempotency.generator import IdempotencyKeyGenerator
from src.runtime.idempotency.types import IdempotencyScope


class TestIdempotencyKeyGenerator:
    """冒烟 + 边界：IdempotencyKeyGenerator 幂等键生成"""

    def test_smoke_generate_key_with_default_scope(self) -> None:
        """冒烟：生成幂等键（默认 STEP_SCOPE）"""
        generator = IdempotencyKeyGenerator()
        
        key_id = generator.generate_key(
            organization_id="org-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
            request={"tool": "file_write", "path": "test.py"},
        )
        
        assert key_id.startswith("idem-")
        assert len(key_id) > 10  # idem- + UUID

    def test_smoke_generated_keys_are_unique(self) -> None:
        """冒烟：生成的键是唯一的（UUID v7 高熵）"""
        generator = IdempotencyKeyGenerator()
        
        key_id1 = generator.generate_key(
            organization_id="org-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
            request={"tool": "file_write", "path": "test.py"},
        )
        
        key_id2 = generator.generate_key(
            organization_id="org-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
            request={"tool": "file_write", "path": "test.py"},
        )
        
        # 每次调用生成新的 UUID，即使参数相同
        assert key_id1 != key_id2

    def test_smoke_generate_request_digest(self) -> None:
        """冒烟：生成请求摘要"""
        generator = IdempotencyKeyGenerator()
        
        request = {"tool": "file_write", "path": "test.py", "content": "hello"}
        digest = generator.generate_request_digest(request)
        
        assert digest.startswith("sha256:")
        assert len(digest) == 71

    def test_smoke_same_request_produces_same_digest(self) -> None:
        """冒烟：相同请求产生相同摘要"""
        generator = IdempotencyKeyGenerator()
        
        request = {"tool": "file_write", "path": "test.py"}
        digest1 = generator.generate_request_digest(request)
        digest2 = generator.generate_request_digest(request)
        
        assert digest1 == digest2

    def test_smoke_different_request_produces_different_digest(self) -> None:
        """冒烟：不同请求产生不同摘要"""
        generator = IdempotencyKeyGenerator()
        
        request1 = {"tool": "file_write", "path": "test.py"}
        request2 = {"tool": "file_write", "path": "other.py"}
        
        digest1 = generator.generate_request_digest(request1)
        digest2 = generator.generate_request_digest(request2)
        
        assert digest1 != digest2

    def test_smoke_verify_step_scope_consistency_valid(self) -> None:
        """冒烟：STEP_SCOPE 一致性校验（有效）"""
        generator = IdempotencyKeyGenerator()
        
        is_valid = generator.verify_scope_consistency(
            scope=IdempotencyScope.STEP_SCOPE,
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
        )
        
        assert is_valid is True

    def test_boundary_verify_step_scope_consistency_missing_step_id(self) -> None:
        """边界：STEP_SCOPE 缺少 step_id 时无效"""
        generator = IdempotencyKeyGenerator()
        
        is_valid = generator.verify_scope_consistency(
            scope=IdempotencyScope.STEP_SCOPE,
            workflow_id="wf-001",
            step_id="",  # 缺少 step_id
            intent_instance_id="intent-001",
        )
        
        assert is_valid is False

    def test_boundary_verify_step_scope_consistency_missing_intent_id(self) -> None:
        """边界：STEP_SCOPE 缺少 intent_instance_id 时无效"""
        generator = IdempotencyKeyGenerator()
        
        is_valid = generator.verify_scope_consistency(
            scope=IdempotencyScope.STEP_SCOPE,
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="",  # 缺少 intent_instance_id
        )
        
        assert is_valid is False

    def test_smoke_verify_task_scope_consistency_valid(self) -> None:
        """冒烟：TASK_SCOPE 一致性校验（有效）"""
        generator = IdempotencyKeyGenerator()
        
        is_valid = generator.verify_scope_consistency(
            scope=IdempotencyScope.TASK_SCOPE,
            workflow_id="wf-001",
            step_id="",
            intent_instance_id="",
        )
        
        assert is_valid is True

    def test_boundary_verify_task_scope_consistency_missing_workflow_id(self) -> None:
        """边界：TASK_SCOPE 缺少 workflow_id 时无效"""
        generator = IdempotencyKeyGenerator()
        
        is_valid = generator.verify_scope_consistency(
            scope=IdempotencyScope.TASK_SCOPE,
            workflow_id="",  # 缺少 workflow_id
            step_id="step-001",
            intent_instance_id="intent-001",
        )
        
        assert is_valid is False

    def test_boundary_generate_key_with_task_scope(self) -> None:
        """边界：使用 TASK_SCOPE 生成键"""
        generator = IdempotencyKeyGenerator()
        
        key_id = generator.generate_key(
            organization_id="org-001",
            workflow_id="wf-001",
            step_id="",  # TASK_SCOPE 不需要 step_id
            intent_instance_id="",
            action_type="PR_CREATE",
            request={"title": "Fix bug"},
            scope=IdempotencyScope.TASK_SCOPE,
        )
        
        assert key_id.startswith("idem-")
        assert len(key_id) > 10
