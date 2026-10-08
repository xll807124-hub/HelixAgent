"""
单元测试：src/runtime/idempotency/types.py

测试覆盖：
- IdempotencyScope 枚举
- IdempotencyStatus 枚举及其辅助方法
- ReconciliationOutcome 枚举

验收标准：
- 枚举值正确定义
- 辅助方法逻辑正确（is_terminal, is_retryable, requires_reconciliation）
"""

import pytest

from src.runtime.idempotency.types import (
    IdempotencyScope,
    IdempotencyStatus,
    ReconciliationOutcome,
)


class TestIdempotencyScope:
    """冒烟 + 边界：IdempotencyScope 枚举"""

    def test_smoke_scope_values_exist(self) -> None:
        """冒烟：枚举值存在且正确"""
        assert IdempotencyScope.STEP_SCOPE == "STEP_SCOPE"
        assert IdempotencyScope.TASK_SCOPE == "TASK_SCOPE"

    def test_boundary_only_two_scopes(self) -> None:
        """边界：只有两种作用域（MVP 限制）"""
        assert len(IdempotencyScope) == 2


class TestIdempotencyStatus:
    """冒烟 + 边界：IdempotencyStatus 枚举及辅助方法"""

    def test_smoke_all_statuses_exist(self) -> None:
        """冒烟：所有12种状态存在"""
        expected_statuses = {
            "RESERVED",
            "EXECUTING",
            "SUCCEEDED",
            "FAILED_RETRYABLE",
            "FAILED_FINAL",
            "OUTCOME_UNKNOWN",
            "RECONCILING",
            "ESCALATED",
            "COMPENSATING",
            "COMPENSATED",
            "COMPENSATION_FAILED",
            "CONFLICT",
        }
        actual_statuses = {status.value for status in IdempotencyStatus}
        assert actual_statuses == expected_statuses

    def test_smoke_is_terminal_for_final_states(self) -> None:
        """冒烟：终态判断正确"""
        # 终态
        assert IdempotencyStatus.is_terminal(IdempotencyStatus.SUCCEEDED)
        assert IdempotencyStatus.is_terminal(IdempotencyStatus.FAILED_FINAL)
        assert IdempotencyStatus.is_terminal(IdempotencyStatus.COMPENSATED)
        assert IdempotencyStatus.is_terminal(IdempotencyStatus.COMPENSATION_FAILED)
        assert IdempotencyStatus.is_terminal(IdempotencyStatus.CONFLICT)
        assert IdempotencyStatus.is_terminal(IdempotencyStatus.ESCALATED)

        # 非终态
        assert not IdempotencyStatus.is_terminal(IdempotencyStatus.RESERVED)
        assert not IdempotencyStatus.is_terminal(IdempotencyStatus.EXECUTING)
        assert not IdempotencyStatus.is_terminal(IdempotencyStatus.FAILED_RETRYABLE)
        assert not IdempotencyStatus.is_terminal(IdempotencyStatus.OUTCOME_UNKNOWN)
        assert not IdempotencyStatus.is_terminal(IdempotencyStatus.RECONCILING)
        assert not IdempotencyStatus.is_terminal(IdempotencyStatus.COMPENSATING)

    def test_smoke_is_retryable_for_valid_states(self) -> None:
        """冒烟：可重试状态判断正确"""
        # 可重试
        assert IdempotencyStatus.is_retryable(IdempotencyStatus.RESERVED)
        assert IdempotencyStatus.is_retryable(IdempotencyStatus.FAILED_RETRYABLE)

        # 不可重试
        assert not IdempotencyStatus.is_retryable(IdempotencyStatus.EXECUTING)
        assert not IdempotencyStatus.is_retryable(IdempotencyStatus.SUCCEEDED)
        assert not IdempotencyStatus.is_retryable(IdempotencyStatus.FAILED_FINAL)
        assert not IdempotencyStatus.is_retryable(IdempotencyStatus.OUTCOME_UNKNOWN)
        assert not IdempotencyStatus.is_retryable(IdempotencyStatus.CONFLICT)
        assert not IdempotencyStatus.is_retryable(IdempotencyStatus.ESCALATED)

    def test_smoke_requires_reconciliation_for_unknown_states(self) -> None:
        """冒烟：需要对账状态判断正确"""
        # 需要对账
        assert IdempotencyStatus.requires_reconciliation(IdempotencyStatus.OUTCOME_UNKNOWN)
        assert IdempotencyStatus.requires_reconciliation(IdempotencyStatus.RECONCILING)

        # 不需要对账
        assert not IdempotencyStatus.requires_reconciliation(IdempotencyStatus.RESERVED)
        assert not IdempotencyStatus.requires_reconciliation(IdempotencyStatus.EXECUTING)
        assert not IdempotencyStatus.requires_reconciliation(IdempotencyStatus.SUCCEEDED)
        assert not IdempotencyStatus.requires_reconciliation(IdempotencyStatus.FAILED_RETRYABLE)

    def test_boundary_terminal_and_retryable_are_mutually_exclusive(self) -> None:
        """边界：终态和可重试状态互斥"""
        for status in IdempotencyStatus:
            is_terminal = IdempotencyStatus.is_terminal(status)
            is_retryable = IdempotencyStatus.is_retryable(status)
            # 终态不应该可重试（除了边界情况）
            if is_terminal:
                assert not is_retryable, f"{status} 是终态但标记为可重试"


class TestReconciliationOutcome:
    """冒烟：ReconciliationOutcome 枚举"""

    def test_smoke_reconciliation_outcomes_exist(self) -> None:
        """冒烟：对账结果枚举值存在"""
        assert ReconciliationOutcome.CONFIRMED_SUCCESS == "CONFIRMED_SUCCESS"
        assert ReconciliationOutcome.CONFIRMED_NOT_EXECUTED == "CONFIRMED_NOT_EXECUTED"
        assert ReconciliationOutcome.STILL_UNKNOWN == "STILL_UNKNOWN"

    def test_boundary_only_three_outcomes(self) -> None:
        """边界：只有三种对账结果"""
        assert len(ReconciliationOutcome) == 3
