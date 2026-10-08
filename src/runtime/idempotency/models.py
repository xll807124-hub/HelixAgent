"""
RT-007 Idempotency Key 与副作用边界 — 数据模型

本模块定义幂等键的核心数据模型（REQ-RT-007 §4、§5）

设计原则：
- 幂等键在首次派发前生成并持久化，模型不得指定或改写
- 公开键使用高熵、不可猜测的标识（UUID v7 或 Base64 哈希）
- 作用域字段和请求摘要存放在受访问控制的账本中
- 敏感参数与密钥不会明文出现在键/指标中
"""

from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..common.types import utc_now
from .types import IdempotencyScope, IdempotencyStatus


class IdempotencyKey(BaseModel):
    """幂等键数据模型（REQ-RT-007 §4、§5）
    
    一个幂等键标识一次逻辑副作用意图，不是一次网络尝试或整个会话的通用键。
    平台在首次派发前生成并持久化；模型不得指定、改写或在重试时重新生成。
    
    字段设计：
    - key_id：高熵不可猜测标识（公开键）
    - scope：幂等作用域（STEP_SCOPE/TASK_SCOPE）
    - organization_id/project_id/repository_id：租户隔离
    - workflow_id/step_id/intent_instance_id：逻辑身份定位
    - request_digest：规范化请求摘要（SHA256，用于冲突检测）
    - status：操作状态（12种状态，见 IdempotencyStatus）
    - lease_token/lease_expires_at：执行租约（原子领取）
    - result_ref：结果引用（SUCCEEDED 状态下的可复用结果）
    - created_at/updated_at：时间戳（UTC）
    """
    
    model_config = ConfigDict(extra="forbid")
    
    # === 幂等键身份 ===
    
    key_id: str = Field(
        ...,
        description="幂等键唯一标识（高熵不可猜测，UUID v7 格式）",
    )
    
    scope: IdempotencyScope = Field(
        default=IdempotencyScope.STEP_SCOPE,
        description="幂等作用域（默认 STEP_SCOPE）",
    )
    
    # === 租户与资源定位 ===
    
    organization_id: str = Field(..., description="组织 ID（租户隔离）")
    project_id: str = Field(..., description="项目 ID")
    repository_id: str = Field(..., description="仓库 ID")
    task_id: str = Field(..., description="任务 ID")
    workflow_id: str = Field(..., description="工作流 ID")
    step_id: str = Field(..., description="步骤 ID（稳定标识，不依赖执行顺序）")
    
    intent_instance_id: str = Field(
        ...,
        description="意图实例 ID（同一步骤内不同独立意图的区分标识）",
    )
    
    # === 操作元数据 ===
    
    action_type: str = Field(..., description="动作类型（如 TOOL_CALL, FILE_WRITE, PR_CREATE）")
    action_id: str | None = Field(
        default=None,
        description="关联的 Action ID（来自 REQ-RT-001）",
    )
    
    request_digest: str = Field(
        ...,
        description="请求摘要（SHA256，规范化参数的哈希，用于冲突检测）",
    )
    
    # === 状态与租约 ===
    
    status: IdempotencyStatus = Field(
        default=IdempotencyStatus.RESERVED,
        description="操作状态（12种状态）",
    )
    
    lease_token: str | None = Field(
        default=None,
        description="执行租约令牌（持有租约的执行者标识）",
    )
    
    lease_expires_at: datetime | None = Field(
        default=None,
        description="租约过期时间（UTC）",
    )
    
    # === 结果与引用 ===
    
    result_ref: str | None = Field(
        default=None,
        description="结果引用（SUCCEEDED 状态下指向 Artifact/Evidence）",
    )
    
    downstream_id: str | None = Field(
        default=None,
        description="下游业务标识（如 PR number, commit SHA, issue ID）",
    )
    
    error_code: str | None = Field(
        default=None,
        description="错误码（失败状态下的错误分类）",
    )
    
    error_message: str | None = Field(
        default=None,
        description="错误消息（不含敏感信息）",
    )
    
    # === 对账与重试 ===
    
    reconciliation_attempts: int = Field(
        default=0,
        ge=0,
        description="对账尝试次数（最多3次）",
    )
    
    last_reconciliation_at: datetime | None = Field(
        default=None,
        description="最后对账时间（UTC）",
    )
    
    retry_count: int = Field(
        default=0,
        ge=0,
        description="重试次数（用于审计和统计）",
    )
    
    # === 审计与关联 ===
    
    trace_id: str | None = Field(
        default=None,
        description="Trace ID（关联到 REQ-RT-006）",
    )
    
    approval_ref: str | None = Field(
        default=None,
        description="审批引用（关联到 Policy Gateway 决策）",
    )
    
    created_by: str = Field(..., description="创建者（Actor ID）")
    
    created_at: datetime = Field(
        default_factory=utc_now,
        description="创建时间（UTC）",
    )
    
    updated_at: datetime = Field(
        default_factory=utc_now,
        description="更新时间（UTC）",
    )
    
    # === 业务方法 ===
    
    def is_lease_valid(self) -> bool:
        """检查租约是否有效（未过期且有 lease_token）"""
        if not self.lease_token or not self.lease_expires_at:
            return False
        return utc_now() < self.lease_expires_at
    
    def is_terminal(self) -> bool:
        """检查是否为终态（不再变化的状态）"""
        return IdempotencyStatus.is_terminal(self.status)
    
    def is_retryable(self) -> bool:
        """检查是否可重试（可复用原键重试的状态）"""
        return IdempotencyStatus.is_retryable(self.status)
    
    def requires_reconciliation(self) -> bool:
        """检查是否需要对账（结果未知需要查询确认）"""
        return IdempotencyStatus.requires_reconciliation(self.status)
    
    def can_acquire_lease(self, executor_id: str) -> bool:
        """检查是否可以获取租约
        
        允许获取租约的条件：
        1. 当前无租约（首次执行）
        2. 租约已过期（接管，但需先核查前次执行状态）
        3. 当前持有者就是请求者（续约）
        
        注意：租约过期不能证明原执行已停止，接管者必须先核查。
        """
        # 无租约，可以获取
        if not self.lease_token:
            return True
        
        # 当前持有者续约
        if self.lease_token == executor_id:
            return True
        
        # 租约已过期，可以接管（但调用者需先核查状态）
        if self.lease_expires_at and utc_now() >= self.lease_expires_at:
            return True
        
        return False


class IdempotencyResult(BaseModel):
    """幂等操作结果（REQ-RT-007 §6）
    
    封装幂等操作的执行结果，包括：
    - is_duplicate：是否为重复提交
    - should_execute：是否应该执行操作（false 表示直接返回缓存结果）
    - cached_result：缓存的结果（SUCCEEDED 状态下）
    - conflict_reason：冲突原因（CONFLICT 状态下）
    """
    
    model_config = ConfigDict(extra="forbid")
    
    key_id: str = Field(..., description="幂等键 ID")
    
    status: IdempotencyStatus = Field(..., description="当前状态")
    
    is_duplicate: bool = Field(
        default=False,
        description="是否为重复提交（同键同摘要）",
    )
    
    should_execute: bool = Field(
        default=True,
        description="是否应该执行操作（false 表示返回缓存结果）",
    )
    
    cached_result: dict[str, Any] | None = Field(
        default=None,
        description="缓存的结果（SUCCEEDED 状态下）",
    )
    
    conflict_reason: str | None = Field(
        default=None,
        description="冲突原因（CONFLICT 状态下：同键不同摘要）",
    )
    
    requires_reconciliation: bool = Field(
        default=False,
        description="是否需要对账（结果未知）",
    )
    
    escalated: bool = Field(
        default=False,
        description="是否已升级到人工处理",
    )


class LeaseAcquisition(BaseModel):
    """租约获取结果
    
    封装租约获取操作的结果：
    - acquired：是否成功获取租约
    - lease_token：租约令牌（成功时）
    - lease_expires_at：租约过期时间（成功时）
    - conflict_holder：冲突持有者（失败时，另一个执行者持有租约）
    """
    
    model_config = ConfigDict(extra="forbid")
    
    acquired: bool = Field(..., description="是否成功获取租约")
    
    lease_token: str | None = Field(
        default=None,
        description="租约令牌（成功时）",
    )
    
    lease_expires_at: datetime | None = Field(
        default=None,
        description="租约过期时间（成功时）",
    )
    
    conflict_holder: str | None = Field(
        default=None,
        description="冲突持有者（失败时，另一个执行者持有租约）",
    )


class ReconciliationAttempt(BaseModel):
    """对账尝试记录
    
    记录每次对账查询的尝试信息：
    - attempt_number：尝试次数（1-based）
    - attempted_at：尝试时间
    - outcome：对账结果（CONFIRMED_SUCCESS/CONFIRMED_NOT_EXECUTED/STILL_UNKNOWN）
    - error_code：错误码（查询失败时）
    - next_retry_at：下次重试时间（失败时）
    """
    
    model_config = ConfigDict(extra="forbid")
    
    attempt_number: int = Field(..., ge=1, le=4, description="尝试次数（1-4）")
    
    attempted_at: datetime = Field(
        default_factory=utc_now,
        description="尝试时间（UTC）",
    )
    
    outcome: str = Field(
        ...,
        description="对账结果（CONFIRMED_SUCCESS/CONFIRMED_NOT_EXECUTED/STILL_UNKNOWN）",
    )
    
    error_code: str | None = Field(
        default=None,
        description="错误码（查询失败时）",
    )
    
    error_message: str | None = Field(
        default=None,
        description="错误消息（不含敏感信息）",
    )
    
    next_retry_at: datetime | None = Field(
        default=None,
        description="下次重试时间（失败时，按指数退避计算）",
    )
    
    @staticmethod
    def calculate_next_retry(attempt_number: int, base_delay_seconds: float = 1.0) -> datetime:
        """计算下次重试时间（有抖动的指数退避）
        
        REQ-RT-007 §6.2 规定：
        - 最多重试 3 次（总共 4 次查询尝试）
        - 有抖动的指数退避，初始建议 1s、2s、4s
        - 遵守下游 Retry-After 头（实现时处理）
        
        Args:
            attempt_number: 当前尝试次数（1-based）
            base_delay_seconds: 基础延迟（秒）
        
        Returns:
            下次重试时间（UTC）
        """
        import random
        
        # 指数退避：2^(attempt_number - 1) * base_delay
        delay = (2 ** (attempt_number - 1)) * base_delay_seconds
        
        # 添加 ±25% 抖动
        jitter = random.uniform(-0.25, 0.25) * delay
        final_delay = delay + jitter
        
        return utc_now() + timedelta(seconds=final_delay)
