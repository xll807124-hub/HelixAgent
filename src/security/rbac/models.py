"""
RBAC 数据模型。

定义主体、资源、角色、操作和授权决策的核心数据结构。
"""

from enum import Enum
from typing import Optional, Set, FrozenSet
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict


class SubjectType(str, Enum):
    """主体类型."""
    
    USER = "USER"              # 自然人用户
    TEAM = "TEAM"              # 团队/组
    SERVICE = "SERVICE"        # 服务主体
    AGENT = "AGENT"            # Agent 运行时身份


class ResourceType(str, Enum):
    """资源类型。
    
    按层级: 平台 → 组织 → 项目 → 仓库 → 路径
    """
    
    PLATFORM = "PLATFORM"      # 平台级资源 (仅平台治理)
    ORGANIZATION = "ORGANIZATION"  # 组织
    PROJECT = "PROJECT"        # 项目
    REPOSITORY = "REPOSITORY"  # 仓库
    PATH = "PATH"              # 路径


class Operation(str, Enum):
    """操作类别。
    
    定义在资源上可执行的操作。
    """
    
    # 读取相关
    VIEW = "VIEW"              # 查看/访问
    READ = "READ"              # 读取内容
    SEARCH = "SEARCH"          # 搜索/检索
    
    # 任务和执行相关
    CREATE_TASK = "CREATE_TASK"  # 创建任务
    MODIFY_TASK = "MODIFY_TASK"  # 修改任务
    EXECUTE_TASK = "EXECUTE_TASK"  # 执行任务/工具调用
    EXECUTE_TEST = "EXECUTE_TEST"  # 执行测试/命令
    
    # 代码相关
    CREATE_BRANCH = "CREATE_BRANCH"  # 创建分支
    CREATE_COMMIT = "CREATE_COMMIT"  # 提交代码
    CREATE_PR = "CREATE_PR"    # 创建 PR
    MERGE_PR = "MERGE_PR"      # 合并 PR
    
    # 管理相关
    MANAGE_MEMBERS = "MANAGE_MEMBERS"  # 管理成员
    MANAGE_ROLES = "MANAGE_ROLES"    # 管理角色
    MANAGE_POLICIES = "MANAGE_POLICIES"  # 管理策略
    
    # 审计相关
    VIEW_AUDIT = "VIEW_AUDIT"  # 查看审计日志


class RoleType(str, Enum):
    """角色类型。
    
    定义组织内的标准角色模板。
    """
    
    PLATFORM_ADMIN = "PLATFORM_ADMIN"      # 平台管理员
    ORG_ADMIN = "ORG_ADMIN"                # 组织管理员
    PROJECT_ADMIN = "PROJECT_ADMIN"        # 项目管理员
    DEVELOPER = "DEVELOPER"                # 开发者/任务发起者
    SECURITY_AUDITOR = "SECURITY_AUDITOR"  # 安全审计员


class AuthorizationDecision(str, Enum):
    """授权决策。
    
    RBAC 评估的结果。
    """
    
    ALLOW = "ALLOW"            # 允许
    DENY = "DENY"              # 拒绝
    UNKNOWN = "UNKNOWN"        # 未知 (默认拒绝)


class Subject(BaseModel):
    """主体 (Principle)。
    
    表示进行授权评估的对象：用户、团队、服务或 Agent。
    """
    
    model_config = ConfigDict(frozen=True)
    
    subject_id: str            # 主体唯一标识
    subject_type: SubjectType  # 主体类型
    organization_id: str       # 所属组织 (Agent/Service 的有机组织)
    roles: FrozenSet[RoleType] = frozenset()  # 主体拥有的角色
    effective_until: Optional[datetime] = None  # 权限有效期


class Resource(BaseModel):
    """资源。
    
    表示被授权访问的资源。
    """
    
    model_config = ConfigDict(frozen=True)
    
    resource_id: str           # 资源唯一标识
    resource_type: ResourceType  # 资源类型
    organization_id: Optional[str] = None  # 所属组织 (只对 ORGANIZATION 以下)
    project_id: Optional[str] = None       # 所属项目
    repository_id: Optional[str] = None    # 所属仓库
    path: Optional[str] = None             # 路径 (用于 PATH 类型)
    sensitivity_level: int = 1  # 敏感度等级 (1=公开, 5=极密)
    is_sensitive: bool = False  # 是否敏感资源


class Role(BaseModel):
    """角色定义。
    
    定义角色包含的权限。
    """
    
    model_config = ConfigDict(frozen=True, json_encoders={
        frozenset: lambda v: list(v),
        FrozenSet: lambda v: list(v),
    })
    
    role_type: RoleType        # 角色类型
    display_name: str          # 显示名称
    description: str           # 角色描述
    permissions: FrozenSet[tuple[ResourceType, Operation]] = frozenset()  # 权限集合


class AuthorizationRequest(BaseModel):
    """授权请求。
    
    请求对资源的某个操作的授权。
    """
    
    model_config = ConfigDict(frozen=True)
    
    request_id: str            # 请求 ID (用于审计追踪)
    subject: Subject           # 发起主体
    resource: Resource         # 目标资源
    operation: Operation       # 请求的操作
    context: Optional[dict] = None  # 额外上下文信息
    timestamp: datetime = None
    
    def __init__(self, **data):
        """初始化授权请求."""
        if data.get("timestamp") is None:
            data["timestamp"] = datetime.now(timezone.utc)
        super().__init__(**data)


class AuthorizationResult(BaseModel):
    """授权评估结果。
    
    返回授权决策及相关信息。
    """
    
    model_config = ConfigDict(frozen=True)
    
    request_id: str            # 对应请求 ID
    decision: AuthorizationDecision  # 授权决策
    subject: Subject           # 评估主体
    resource: Resource         # 评估资源
    operation: Operation       # 评估操作
    reason: Optional[str] = None  # 决策原因 (拒绝时必填)
    effective_until: Optional[datetime] = None  # 决策有效期
    timestamp: datetime = None
    
    def __init__(self, **data):
        """初始化结果."""
        if data.get("timestamp") is None:
            data["timestamp"] = datetime.now(timezone.utc)
        super().__init__(**data)
