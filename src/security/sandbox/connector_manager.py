"""
连接器管理系统 - REQ-SEC-004 连接器治理

核心职责：
1. 连接器声明收集与版本化
2. 审批流程与版本固化
3. 运行时连接器下发
4. 网络白名单管理与 DNS 防护
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl

logger = logging.getLogger(__name__)


class ConnectorStatus(str, Enum):
    """连接器声明状态"""
    DRAFT = "draft"                # 草稿
    PENDING_APPROVAL = "pending_approval"  # 待审批
    APPROVED = "approved"          # 已批准
    DEPRECATED = "deprecated"      # 已弃用
    REVOKED = "revoked"            # 已撤销


class DataClassification(str, Enum):
    """数据分类"""
    L1_PUBLIC = "L1_public"        # 公开数据
    L2_INTERNAL = "L2_internal"    # 内部数据
    L3_SENSITIVE = "L3_sensitive"  # 敏感数据
    L4_SECRET = "L4_secret"        # 机密数据


class ConnectorDeclaration(BaseModel):
    """连接器声明"""
    connector_id: str = Field(default_factory=lambda: str(uuid4()), description="连接器 ID")
    
    # 基本信息
    name: str = Field(..., description="连接器名称")
    description: str = Field(..., description="连接器描述")
    owner: str = Field(..., description="所有者（用户/团队）")
    environment: str = Field(
        default="prod",
        description="环境（dev/staging/prod）"
    )
    
    # 目标服务声明
    target_service: str = Field(..., description="目标服务（github/aws/slack/database/...）")
    target_endpoint: HttpUrl = Field(..., description="目标服务端点")
    
    # 网络范围
    allowed_hosts: list[str] = Field(..., description="允许连接的主机/域名列表")
    allowed_ports: list[int] = Field(default=[443, 80], description="允许端口")
    allowed_protocols: list[str] = Field(
        default=["https", "http"],
        description="允许协议"
    )
    
    # 操作范围
    allowed_operations: list[str] = Field(..., description="允许操作（read/write/admin/...）")
    resource_scope: str = Field(..., description="资源范围（仓库名/数据库/...）")
    
    # 数据与权限
    data_classification: DataClassification = Field(
        default=DataClassification.L2_INTERNAL,
        description="数据分类"
    )
    credential_type: str = Field(..., description="凭据类型（github_token/aws_sts/oauth/...）")
    required_scopes: list[str] = Field(default_factory=list, description="所需权限范围")
    
    # 有效期
    valid_from: datetime = Field(default_factory=datetime.utcnow, description="生效时间")
    valid_until: Optional[datetime] = Field(default=None, description="过期时间")
    
    # 验证方式
    verification_method: str = Field(
        default="dns_txt",
        description="验证方式（dns_txt/tls_cert/ip_whitelist/...）"
    )
    
    # 备注
    notes: str = Field(default="", description="备注")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ConnectorVersion(BaseModel):
    """连接器版本（已审批）"""
    version_id: str = Field(default_factory=lambda: str(uuid4()))
    connector_id: str = Field(..., description="关联的连接器")
    version_number: str = Field(..., description="版本号（如 v1.2.3）")
    
    # 声明内容快照
    declaration: ConnectorDeclaration = Field(..., description="连接器声明快照")
    
    # 审批信息
    approved_by: str = Field(..., description="审批人")
    approved_at: datetime = Field(default_factory=datetime.utcnow)
    approval_reason: str = Field(default="", description="审批理由")
    
    # 签名（用于防篡改）
    content_hash: str = Field(..., description="内容 SHA256 哈希")
    
    # 状态
    status: ConnectorStatus = Field(default=ConnectorStatus.APPROVED)
    revoked_at: Optional[datetime] = Field(default=None)
    revoke_reason: Optional[str] = Field(default=None)
    
    # 下发记录
    deployed_to_backends: list[str] = Field(
        default_factory=list,
        description="部署到的后端列表"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "version_number": "v1.2.3",
                "connector_id": "github-api-prod",
                "approved_by": "security-lead@company.com",
                "status": "approved",
            }
        }


class ConnectorRuntimeContext(BaseModel):
    """运行时连接器上下文"""
    task_id: str = Field(..., description="任务 ID")
    worker_id: str = Field(..., description="Worker ID")
    
    # 绑定的连接器版本
    connector_version_id: str = Field(..., description="连接器版本 ID")
    connector_id: str = Field(..., description="连接器 ID")
    version_number: str = Field(..., description="版本号")
    
    # 网络限制
    allowed_hosts: list[str] = Field(..., description="运行时允许的主机")
    allowed_ports: list[int] = Field(..., description="运行时允许的端口")
    allowed_protocols: list[str] = Field(..., description="运行时允许的协议")
    
    # 操作权限
    allowed_operations: list[str] = Field(..., description="允许的操作")
    
    # 凭据信息
    credential_type: str = Field(..., description="凭据类型")
    credential_scope: list[str] = Field(..., description="凭据权限范围")
    
    # 验证配置
    verification_method: str = Field(..., description="验证方式")
    
    # 生效期
    valid_until: Optional[datetime] = Field(default=None, description="有效期")
    
    # 审计
    bound_at: datetime = Field(default_factory=datetime.utcnow)
    bound_by_policy: str = Field(..., description="绑定的策略版本")


class ConnectorManager:
    """
    连接器管理器
    
    职责：
    1. 管理连接器声明的完整生命周期
    2. 版本化与内容快照
    3. 审批流程与固化
    4. 运行时连接器绑定与下发
    5. 审计与可观测性
    """

    def __init__(self):
        """初始化连接器管理器"""
        self._declarations: dict[str, ConnectorDeclaration] = {}
        self._versions: dict[str, ConnectorVersion] = {}
        self._active_versions: dict[str, str] = {}  # connector_id -> version_id
        self._runtime_contexts: dict[str, ConnectorRuntimeContext] = {}
        self._audit_log: list[dict] = []

    def declare_connector(self, declaration: ConnectorDeclaration) -> str:
        """
        提交连接器声明
        
        Args:
            declaration: 连接器声明
            
        Returns:
            connector_id: 新的连接器 ID
        """
        self._declarations[declaration.connector_id] = declaration
        self._audit_log.append({
            "action": "declare",
            "connector_id": declaration.connector_id,
            "timestamp": datetime.utcnow().isoformat(),
            "owner": declaration.owner,
        })
        logger.info(f"Connector declared: {declaration.connector_id}")
        return declaration.connector_id

    def update_declaration(
        self,
        connector_id: str,
        updated_declaration: ConnectorDeclaration,
    ) -> None:
        """
        更新连接器声明
        
        注意：更新后需要重新审批，版本自动变更
        """
        if connector_id not in self._declarations:
            raise ValueError(f"Connector {connector_id} not found")
        
        old = self._declarations[connector_id]
        updated_declaration.connector_id = connector_id  # 保持 ID 一致
        self._declarations[connector_id] = updated_declaration
        
        self._audit_log.append({
            "action": "update",
            "connector_id": connector_id,
            "timestamp": datetime.utcnow().isoformat(),
            "changes": {
                "old_endpoint": str(old.target_endpoint),
                "new_endpoint": str(updated_declaration.target_endpoint),
            },
        })
        logger.info(f"Connector declaration updated: {connector_id}")

    def approve_connector(
        self,
        connector_id: str,
        approved_by: str,
        approval_reason: str = "",
    ) -> str:
        """
        审批连接器，生成版本
        
        Args:
            connector_id: 连接器 ID
            approved_by: 审批人
            approval_reason: 审批理由
            
        Returns:
            version_id: 新的版本 ID
            
        Raises:
            ValueError: 如果连接器不存在
        """
        if connector_id not in self._declarations:
            raise ValueError(f"Connector {connector_id} not found")
        
        declaration = self._declarations[connector_id]
        
        # 生成内容哈希（用于防篡改）
        declaration_json = declaration.model_dump_json()
        content_hash = hashlib.sha256(declaration_json.encode()).hexdigest()
        
        # 确定版本号
        existing_versions = [
            v for v in self._versions.values()
            if v.connector_id == connector_id
        ]
        version_number = f"v{len(existing_versions) + 1}.0.0"
        
        # 创建版本
        version = ConnectorVersion(
            connector_id=connector_id,
            version_number=version_number,
            declaration=declaration.model_copy(),
            approved_by=approved_by,
            approval_reason=approval_reason,
            content_hash=content_hash,
            status=ConnectorStatus.APPROVED,
        )
        
        self._versions[version.version_id] = version
        self._active_versions[connector_id] = version.version_id
        
        self._audit_log.append({
            "action": "approve",
            "connector_id": connector_id,
            "version_id": version.version_id,
            "version_number": version_number,
            "approved_by": approved_by,
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        logger.info(f"Connector approved: {connector_id} v{version_number}")
        return version.version_id

    def get_active_version(self, connector_id: str) -> Optional[ConnectorVersion]:
        """获取连接器的活跃版本"""
        if connector_id not in self._active_versions:
            return None
        
        version_id = self._active_versions[connector_id]
        return self._versions.get(version_id)

    def revoke_connector(
        self,
        connector_id: str,
        reason: str = "",
    ) -> None:
        """
        撤销连接器（停止分配给新任务）
        
        Args:
            connector_id: 连接器 ID
            reason: 撤销原因
        """
        if connector_id not in self._active_versions:
            logger.warning(f"Connector {connector_id} already revoked or not found")
            return
        
        version_id = self._active_versions[connector_id]
        version = self._versions[version_id]
        
        version.status = ConnectorStatus.REVOKED
        version.revoked_at = datetime.utcnow()
        version.revoke_reason = reason
        
        del self._active_versions[connector_id]
        
        self._audit_log.append({
            "action": "revoke",
            "connector_id": connector_id,
            "version_id": version_id,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        logger.warning(f"Connector revoked: {connector_id} (reason: {reason})")

    def bind_connector_to_task(
        self,
        task_id: str,
        worker_id: str,
        connector_id: str,
        policy_version: str,
    ) -> ConnectorRuntimeContext:
        """
        将已批准的连接器版本绑定到任务
        
        Args:
            task_id: 任务 ID
            worker_id: Worker ID
            connector_id: 连接器 ID
            policy_version: 策略版本
            
        Returns:
            ConnectorRuntimeContext: 运行时上下文
            
        Raises:
            ValueError: 如果连接器不可用或已过期
        """
        version = self.get_active_version(connector_id)
        if not version:
            raise ValueError(f"Connector {connector_id} not available or revoked")
        
        declaration = version.declaration
        
        # 检查过期
        if declaration.valid_until and declaration.valid_until < datetime.utcnow():
            raise ValueError(f"Connector {connector_id} expired")
        
        # 创建运行时上下文
        context = ConnectorRuntimeContext(
            task_id=task_id,
            worker_id=worker_id,
            connector_version_id=version.version_id,
            connector_id=connector_id,
            version_number=version.version_number,
            allowed_hosts=declaration.allowed_hosts,
            allowed_ports=declaration.allowed_ports,
            allowed_protocols=declaration.allowed_protocols,
            allowed_operations=declaration.allowed_operations,
            credential_type=declaration.credential_type,
            credential_scope=declaration.required_scopes,
            verification_method=declaration.verification_method,
            valid_until=declaration.valid_until,
            bound_by_policy=policy_version,
        )
        
        context_id = f"{task_id}-{connector_id}"
        self._runtime_contexts[context_id] = context
        
        self._audit_log.append({
            "action": "bind",
            "task_id": task_id,
            "connector_id": connector_id,
            "version_id": version.version_id,
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        logger.info(f"Connector bound to task: {connector_id} → {task_id}")
        return context

    def get_runtime_context(
        self,
        task_id: str,
        connector_id: str,
    ) -> Optional[ConnectorRuntimeContext]:
        """获取运行时上下文"""
        context_id = f"{task_id}-{connector_id}"
        return self._runtime_contexts.get(context_id)

    def verify_network_access(
        self,
        task_id: str,
        connector_id: str,
        destination_host: str,
        destination_port: int,
        protocol: str = "https",
    ) -> tuple[bool, str]:
        """
        验证网络请求是否符合连接器策略
        
        Returns:
            (allowed, reason): 是否允许，以及理由
        """
        context = self.get_runtime_context(task_id, connector_id)
        if not context:
            return False, "Connector not bound to task"
        
        # 检查过期
        if context.valid_until and context.valid_until < datetime.utcnow():
            return False, "Connector context expired"
        
        # 检查主机
        if destination_host not in context.allowed_hosts:
            return False, f"Host {destination_host} not in allowed list"
        
        # 检查端口
        if destination_port not in context.allowed_ports:
            return False, f"Port {destination_port} not allowed"
        
        # 检查协议
        if protocol not in context.allowed_protocols:
            return False, f"Protocol {protocol} not allowed"
        
        return True, "Allowed by connector policy"

    def get_audit_log(self, limit: int = 100) -> list[dict]:
        """获取审计日志"""
        return self._audit_log[-limit:]

    def export_runtime_config(self, context: ConnectorRuntimeContext) -> dict:
        """导出运行时配置用于沙箱"""
        return {
            "connector_id": context.connector_id,
            "version": context.version_number,
            "network": {
                "allowed_hosts": context.allowed_hosts,
                "allowed_ports": context.allowed_ports,
                "allowed_protocols": context.allowed_protocols,
            },
            "operations": context.allowed_operations,
            "credential": {
                "type": context.credential_type,
                "scopes": context.credential_scope,
            },
            "valid_until": context.valid_until.isoformat() if context.valid_until else None,
        }
