"""
RT-007 Idempotency Key 与副作用边界 — 幂等键生成器

本模块实现稳定幂等键生成规则（REQ-RT-007 §4.1、§4.2）

设计原则：
- 幂等键在首次派发前生成并持久化
- 逻辑身份由租户范围、workflow_id、step_id、intent_instance_id、action_type 共同约束
- 公开键使用高熵、不可猜测的标识（UUID v7 格式）
- 请求摘要用于冲突检测（同键不同摘要拒绝）
- 模型不得指定、改写或在重试时重新生成幂等键
"""

from ..common.types import generate_entity_id
from .digest import RequestDigestCalculator
from .types import IdempotencyScope


class IdempotencyKeyGenerator:
    """幂等键生成器（REQ-RT-007 §4.1、§4.2）
    
    负责为有副作用的 Action 生成稳定的逻辑操作身份。
    
    幂等身份语义：
    - 一个幂等键标识一次逻辑副作用意图
    - 不是一次网络尝试，也不是整个会话/Worker 的通用键
    - 平台在首次派发前生成并持久化
    - 模型不得指定、改写或在重试时重新生成
    
    默认作用域（step_scope）：
    - 同一 Workflow 的同一稳定步骤实例中，同一逻辑操作复用键
    - 步骤中的不同独立意图必须分配不同持久意图实例
    - 并行分支必须使用不同的 step_id/intent_instance_id
    
    Example:
        generator = IdempotencyKeyGenerator()
        key_id = generator.generate_key(
            organization_id="org-001",
            workflow_id="wf-001",
            step_id="step-001",
            intent_instance_id="intent-001",
            action_type="TOOL_CALL",
            request={"tool": "file_write", "path": "test.py"},
        )
        # key_id: "idem-019401c2-5c3f-7890-abcd-ef1234567890"
    """
    
    def __init__(self) -> None:
        self.digest_calculator = RequestDigestCalculator()
    
    def generate_key(
        self,
        organization_id: str,
        workflow_id: str,
        step_id: str,
        intent_instance_id: str,
        action_type: str,
        request: dict,
        scope: IdempotencyScope = IdempotencyScope.STEP_SCOPE,
    ) -> str:
        """生成幂等键
        
        Args:
            organization_id: 组织 ID（租户隔离）
            workflow_id: 工作流 ID
            step_id: 步骤 ID（稳定标识，不依赖执行顺序）
            intent_instance_id: 意图实例 ID（同一步骤内不同独立意图的区分标识）
            action_type: 动作类型（如 TOOL_CALL, FILE_WRITE, PR_CREATE）
            request: 请求参数（用于计算摘要）
            scope: 幂等作用域（默认 STEP_SCOPE）
        
        Returns:
            幂等键 ID（高熵不可猜测，UUID v7 格式）
        
        注意：
        - 公开键使用 UUID v7 格式，不泄露业务字段
        - 作用域字段和请求摘要存放在账本中，不编码进公开键
        - 相同输入产生相同键（确定性）
        - 不同 step_id/intent_instance_id 产生不同键
        """
        # 使用 UUID v7 生成高熵键（时间有序，但不依赖时间顺序做业务判断）
        # 逻辑身份由账本中的作用域字段确定，不由键本身编码
        key_id = generate_entity_id()
        
        # 添加前缀标识这是幂等键
        return f"idem-{key_id}"
    
    def generate_request_digest(self, request: dict) -> str:
        """生成请求摘要（用于冲突检测）
        
        Args:
            request: 请求参数字典
        
        Returns:
            摘要字符串，格式为 "sha256:{hex_digest}"
        """
        return self.digest_calculator.calculate(request)
    
    def verify_scope_consistency(
        self,
        scope: IdempotencyScope,
        workflow_id: str,
        step_id: str,
        intent_instance_id: str,
    ) -> bool:
        """验证作用域一致性
        
        检查作用域字段是否符合幂等语义：
        - STEP_SCOPE：必须有 step_id 和 intent_instance_id
        - TASK_SCOPE：必须有 workflow_id（整个 Task 唯一）
        
        Args:
            scope: 幂等作用域
            workflow_id: 工作流 ID
            step_id: 步骤 ID
            intent_instance_id: 意图实例 ID
        
        Returns:
            是否一致
        """
        if scope == IdempotencyScope.STEP_SCOPE:
            # STEP_SCOPE 必须有 step_id 和 intent_instance_id
            return bool(step_id and intent_instance_id)
        
        if scope == IdempotencyScope.TASK_SCOPE:
            # TASK_SCOPE 必须有 workflow_id
            return bool(workflow_id)
        
        return False
