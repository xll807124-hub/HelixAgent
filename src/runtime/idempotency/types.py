"""
RT-007 Idempotency Key 与副作用边界 — 枚举和类型定义

本模块定义幂等性相关的枚举类型（REQ-RT-007 §4、§5）
"""

from enum import Enum


class IdempotencyScope(str, Enum):
    """幂等键作用域（REQ-RT-007 §4.2）
    
    MVP 实现：
    - STEP_SCOPE（默认）：同一 Workflow 的同一稳定步骤实例中，同一逻辑操作复用键
    - TASK_SCOPE：整项 Task 内必须唯一的副作用（如同一任务只能创建一个目标 PR）
    
    注意：
    - STEP_SCOPE 是默认值，覆盖绝大多数场景
    - TASK_SCOPE 仅用于业务规则明确规定的全局唯一副作用，必须显式声明
    - 并行分支必须使用不同的 step_id/intent_instance_id，不能依赖完成顺序
    """
    
    STEP_SCOPE = "STEP_SCOPE"      # 默认：步骤级去重
    TASK_SCOPE = "TASK_SCOPE"      # 任务级去重（显式声明业务唯一约束）


class IdempotencyStatus(str, Enum):
    """幂等操作状态机（REQ-RT-007 §5.1）
    
    状态流转：
        RESERVED → EXECUTING → {SUCCEEDED, FAILED_RETRYABLE, FAILED_FINAL, OUTCOME_UNKNOWN}
        OUTCOME_UNKNOWN → RECONCILING → {SUCCEEDED, FAILED_FINAL, ESCALATED}
        {SUCCEEDED, FAILED_FINAL} → COMPENSATING → {COMPENSATED, COMPENSATION_FAILED}
        
    MVP 实现：
    - RESERVED/EXECUTING/SUCCEEDED/FAILED_*：✅ 完整实现
    - OUTCOME_UNKNOWN/RECONCILING/ESCALATED：✅ 完整实现（对账逻辑）
    - COMPENSATING/COMPENSATED/COMPENSATION_FAILED：⚠️ 占位（待 REQ-REL-007 集成）
    - CONFLICT：✅ 完整实现（同键不同摘要拒绝）
    """
    
    # === 正向操作状态 ===
    
    RESERVED = "RESERVED"
    """预留：逻辑键、请求摘要和授权引用已持久化，尚未确认派发"""
    
    EXECUTING = "EXECUTING"
    """执行中：已有一个持有有效执行租约的执行者"""
    
    SUCCEEDED = "SUCCEEDED"
    """成功：正向副作用有下游响应或可验证证据；保存可复用结果引用"""
    
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    """失败-可重试：确认未产生副作用，且失败类别允许有限重试"""
    
    FAILED_FINAL = "FAILED_FINAL"
    """失败-终态：确认失败且不可重试，或策略明确禁止重试"""
    
    # === 结果未知与对账状态 ===
    
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    """结果未知：请求可能已到达下游，但没有足够证据确认是否生效"""
    
    RECONCILING = "RECONCILING"
    """对账中：正在查询下游或比对本地/远端资源（最多3次重试）"""
    
    ESCALATED = "ESCALATED"
    """已升级：自动处理达到边界，等待用户或运维决策"""
    
    # === 补偿状态（MVP 占位）===
    
    COMPENSATING = "COMPENSATING"
    """补偿中：正在执行补偿操作（待 REQ-REL-007 集成）"""
    
    COMPENSATED = "COMPENSATED"
    """已补偿：补偿操作成功完成（待 REQ-REL-007 集成）"""
    
    COMPENSATION_FAILED = "COMPENSATION_FAILED"
    """补偿失败：补偿操作失败，需人工介入（待 REQ-REL-007 集成）"""
    
    # === 冲突状态 ===
    
    CONFLICT = "CONFLICT"
    """冲突：相同逻辑键对应不同请求摘要，拒绝执行并审计"""
    
    @classmethod
    def is_terminal(cls, status: "IdempotencyStatus") -> bool:
        """判断是否为终态（不再变化的状态）
        
        终态包括：
        - SUCCEEDED：操作成功完成
        - FAILED_FINAL：操作最终失败
        - COMPENSATED：补偿成功完成
        - COMPENSATION_FAILED：补偿失败（需人工）
        - CONFLICT：幂等冲突（不可重试）
        - ESCALATED：已升级到人工处理
        """
        return status in {
            cls.SUCCEEDED,
            cls.FAILED_FINAL,
            cls.COMPENSATED,
            cls.COMPENSATION_FAILED,
            cls.CONFLICT,
            cls.ESCALATED,
        }
    
    @classmethod
    def is_retryable(cls, status: "IdempotencyStatus") -> bool:
        """判断是否可重试（可复用原键重试的状态）
        
        可重试状态：
        - RESERVED：预留后尚未执行
        - FAILED_RETRYABLE：确认未产生副作用且允许重试
        
        不可重试状态：
        - EXECUTING：已有执行者持有租约
        - SUCCEEDED：已成功，不需要重试
        - FAILED_FINAL：最终失败，不允许重试
        - OUTCOME_UNKNOWN/RECONCILING：结果未知，需先对账
        - CONFLICT：冲突，必须新建意图
        - ESCALATED：已升级，需人工决策
        """
        return status in {cls.RESERVED, cls.FAILED_RETRYABLE}
    
    @classmethod
    def requires_reconciliation(cls, status: "IdempotencyStatus") -> bool:
        """判断是否需要对账（结果未知需要查询确认）"""
        return status in {cls.OUTCOME_UNKNOWN, cls.RECONCILING}


class ReconciliationOutcome(str, Enum):
    """对账结果（REQ-RT-007 §6.2、§6.3）
    
    对账查询的三种可能结果：
    - CONFIRMED_SUCCESS：确认下游操作已成功
    - CONFIRMED_NOT_EXECUTED：确认下游操作未发生
    - STILL_UNKNOWN：查询失败或仍无法确认（达到重试上限后升级）
    """
    
    CONFIRMED_SUCCESS = "CONFIRMED_SUCCESS"
    """确认成功：下游操作已执行且有证据"""
    
    CONFIRMED_NOT_EXECUTED = "CONFIRMED_NOT_EXECUTED"
    """确认未执行：下游操作确认未发生，可安全重试"""
    
    STILL_UNKNOWN = "STILL_UNKNOWN"
    """仍未知：查询失败或无法确认（需升级人工处理）"""
