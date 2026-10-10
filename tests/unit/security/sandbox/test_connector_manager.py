"""
连接器管理系统测试 - REQ-SEC-004

测试覆盖：
1. 连接器声明的完整生命周期
2. 版本化与审批
3. 撤销流程
4. 运行时上下文绑定
5. 网络策略验证
"""
import pytest
from datetime import datetime, timedelta
from pydantic import HttpUrl
from src.security.sandbox.connector_manager import (
    ConnectorDeclaration,
    ConnectorManager,
    ConnectorStatus,
    DataClassification,
)


@pytest.fixture
def connector_manager():
    """创建连接器管理器"""
    return ConnectorManager()


@pytest.fixture
def github_connector():
    """GitHub 连接器声明"""
    return ConnectorDeclaration(
        name="GitHub API Connector",
        description="Access to GitHub API for repository operations",
        owner="security-team@company.com",
        environment="prod",
        target_service="github",
        target_endpoint=HttpUrl("https://api.github.com"),
        allowed_hosts=["api.github.com", "github.com"],
        allowed_ports=[443],
        allowed_protocols=["https"],
        allowed_operations=["read", "write"],
        resource_scope="org/repo-*",
        data_classification=DataClassification.L2_INTERNAL,
        credential_type="github_app_token",
        required_scopes=["contents:read", "contents:write"],
    )


@pytest.fixture
def aws_connector():
    """AWS 连接器声明"""
    return ConnectorDeclaration(
        name="AWS STS Connector",
        description="AWS STS for temporary credentials",
        owner="infra-team@company.com",
        environment="prod",
        target_service="aws",
        target_endpoint=HttpUrl("https://sts.amazonaws.com"),
        allowed_hosts=["sts.amazonaws.com", "s3.amazonaws.com"],
        allowed_ports=[443],
        allowed_protocols=["https"],
        allowed_operations=["assume", "read"],
        resource_scope="arn:aws:iam::123456789:role/AgentRole",
        data_classification=DataClassification.L2_INTERNAL,
        credential_type="aws_sts_token",
        required_scopes=["sts:AssumeRole"],
    )


# 测试：声明提交
def test_declare_connector(connector_manager, github_connector):
    """测试提交连接器声明"""
    connector_id = connector_manager.declare_connector(github_connector)
    
    assert connector_id == github_connector.connector_id
    assert connector_id in connector_manager._declarations


def test_update_declaration(connector_manager, github_connector):
    """测试更新声明"""
    connector_id = connector_manager.declare_connector(github_connector)
    
    # 更新端点
    github_connector.target_endpoint = HttpUrl("https://api-new.github.com")
    connector_manager.update_declaration(connector_id, github_connector)
    
    updated = connector_manager._declarations[connector_id]
    assert str(updated.target_endpoint) == "https://api-new.github.com/"


def test_update_nonexistent_declaration_fails(connector_manager, github_connector):
    """测试更新不存在的声明失败"""
    with pytest.raises(ValueError, match="not found"):
        connector_manager.update_declaration("nonexistent-id", github_connector)


# 测试：审批与版本化
def test_approve_connector(connector_manager, github_connector):
    """测试审批连接器"""
    connector_id = connector_manager.declare_connector(github_connector)
    
    version_id = connector_manager.approve_connector(
        connector_id,
        approved_by="security-lead@company.com",
        approval_reason="Verified for production use",
    )
    
    assert version_id
    version = connector_manager._versions[version_id]
    assert version.status == ConnectorStatus.APPROVED
    assert version.version_number == "v1.0.0"


def test_approve_multiple_versions(connector_manager, github_connector):
    """测试同一连接器的多个版本"""
    connector_id = connector_manager.declare_connector(github_connector)
    
    version1 = connector_manager.approve_connector(
        connector_id,
        approved_by="security-lead@company.com",
    )
    
    # 更新声明
    github_connector.allowed_hosts.append("api-beta.github.com")
    connector_manager.update_declaration(connector_id, github_connector)
    
    version2 = connector_manager.approve_connector(
        connector_id,
        approved_by="security-lead@company.com",
    )
    
    assert version1 != version2
    
    v1 = connector_manager._versions[version1]
    v2 = connector_manager._versions[version2]
    assert v1.version_number == "v1.0.0"
    assert v2.version_number == "v2.0.0"


def test_active_version_updated(connector_manager, github_connector):
    """测试活跃版本被更新"""
    connector_id = connector_manager.declare_connector(github_connector)
    
    version1 = connector_manager.approve_connector(connector_id, "approver1")
    active1 = connector_manager.get_active_version(connector_id)
    assert active1.version_id == version1
    
    github_connector.allowed_hosts.append("new-host.github.com")
    connector_manager.update_declaration(connector_id, github_connector)
    
    version2 = connector_manager.approve_connector(connector_id, "approver2")
    active2 = connector_manager.get_active_version(connector_id)
    assert active2.version_id == version2


# 测试：撤销
def test_revoke_connector(connector_manager, github_connector):
    """测试撤销连接器"""
    connector_id = connector_manager.declare_connector(github_connector)
    connector_manager.approve_connector(connector_id, "approver")
    
    connector_manager.revoke_connector(connector_id, reason="Security incident")
    
    active = connector_manager.get_active_version(connector_id)
    assert active is None


def test_revoke_nonexistent_connector(connector_manager):
    """测试撤销不存在的连接器"""
    connector_manager.revoke_connector("nonexistent-id", "Cleanup")
    # 应该不抛出异常，只记录警告


# 测试：运行时绑定
def test_bind_connector_to_task(connector_manager, github_connector):
    """测试将连接器绑定到任务"""
    connector_id = connector_manager.declare_connector(github_connector)
    connector_manager.approve_connector(connector_id, "approver")
    
    context = connector_manager.bind_connector_to_task(
        task_id="task-001",
        worker_id="worker-001",
        connector_id=connector_id,
        policy_version="policy-v1",
    )
    
    assert context.task_id == "task-001"
    assert context.connector_id == connector_id
    assert context.connector_version_id
    assert context.allowed_hosts == github_connector.allowed_hosts


def test_bind_revoked_connector_fails(connector_manager, github_connector):
    """测试绑定已撤销的连接器失败"""
    connector_id = connector_manager.declare_connector(github_connector)
    connector_manager.approve_connector(connector_id, "approver")
    connector_manager.revoke_connector(connector_id)
    
    with pytest.raises(ValueError, match="not available or revoked"):
        connector_manager.bind_connector_to_task(
            task_id="task-001",
            worker_id="worker-001",
            connector_id=connector_id,
            policy_version="policy-v1",
        )


def test_bind_expired_connector_fails(connector_manager):
    """测试绑定已过期的连接器失败"""
    expired_connector = ConnectorDeclaration(
        name="Expired Connector",
        description="Already expired",
        owner="test@company.com",
        target_service="github",
        target_endpoint=HttpUrl("https://api.github.com"),
        allowed_hosts=["api.github.com"],
        allowed_ports=[443],
        allowed_protocols=["https"],
        allowed_operations=["read"],
        resource_scope="org/repo",
        credential_type="github_app_token",
        valid_until=datetime.utcnow() - timedelta(days=1),  # 已过期
    )
    
    connector_id = connector_manager.declare_connector(expired_connector)
    connector_manager.approve_connector(connector_id, "approver")
    
    with pytest.raises(ValueError, match="expired"):
        connector_manager.bind_connector_to_task(
            task_id="task-001",
            worker_id="worker-001",
            connector_id=connector_id,
            policy_version="policy-v1",
        )


# 测试：网络策略验证
def test_verify_network_access_allowed(connector_manager, github_connector):
    """测试允许的网络访问"""
    connector_id = connector_manager.declare_connector(github_connector)
    connector_manager.approve_connector(connector_id, "approver")
    
    context = connector_manager.bind_connector_to_task(
        task_id="task-001",
        worker_id="worker-001",
        connector_id=connector_id,
        policy_version="policy-v1",
    )
    
    allowed, reason = connector_manager.verify_network_access(
        task_id="task-001",
        connector_id=connector_id,
        destination_host="api.github.com",
        destination_port=443,
        protocol="https",
    )
    
    assert allowed
    assert "Allowed" in reason


def test_verify_network_access_disallowed_host(connector_manager, github_connector):
    """测试拒绝的主机"""
    connector_id = connector_manager.declare_connector(github_connector)
    connector_manager.approve_connector(connector_id, "approver")
    
    connector_manager.bind_connector_to_task(
        task_id="task-001",
        worker_id="worker-001",
        connector_id=connector_id,
        policy_version="policy-v1",
    )
    
    allowed, reason = connector_manager.verify_network_access(
        task_id="task-001",
        connector_id=connector_id,
        destination_host="evil.com",
        destination_port=443,
        protocol="https",
    )
    
    assert not allowed
    assert "not in allowed list" in reason


def test_verify_network_access_disallowed_port(connector_manager, github_connector):
    """测试拒绝的端口"""
    connector_id = connector_manager.declare_connector(github_connector)
    connector_manager.approve_connector(connector_id, "approver")
    
    connector_manager.bind_connector_to_task(
        task_id="task-001",
        worker_id="worker-001",
        connector_id=connector_id,
        policy_version="policy-v1",
    )
    
    allowed, reason = connector_manager.verify_network_access(
        task_id="task-001",
        connector_id=connector_id,
        destination_host="api.github.com",
        destination_port=8080,  # 不允许
        protocol="https",
    )
    
    assert not allowed
    assert "not allowed" in reason


def test_verify_network_access_disallowed_protocol(connector_manager, github_connector):
    """测试拒绝的协议"""
    connector_id = connector_manager.declare_connector(github_connector)
    connector_manager.approve_connector(connector_id, "approver")
    
    connector_manager.bind_connector_to_task(
        task_id="task-001",
        worker_id="worker-001",
        connector_id=connector_id,
        policy_version="policy-v1",
    )
    
    allowed, reason = connector_manager.verify_network_access(
        task_id="task-001",
        connector_id=connector_id,
        destination_host="api.github.com",
        destination_port=443,
        protocol="http",  # 不允许，仅 https
    )
    
    assert not allowed
    assert "not allowed" in reason


def test_verify_unbound_connector_fails(connector_manager, github_connector):
    """测试验证未绑定的连接器失败"""
    allowed, reason = connector_manager.verify_network_access(
        task_id="task-001",
        connector_id="unbound-connector",
        destination_host="api.github.com",
        destination_port=443,
    )
    
    assert not allowed
    assert "not bound" in reason


# 测试：运行时配置导出
def test_export_runtime_config(connector_manager, github_connector):
    """测试导出运行时配置"""
    connector_id = connector_manager.declare_connector(github_connector)
    connector_manager.approve_connector(connector_id, "approver")
    
    context = connector_manager.bind_connector_to_task(
        task_id="task-001",
        worker_id="worker-001",
        connector_id=connector_id,
        policy_version="policy-v1",
    )
    
    config = connector_manager.export_runtime_config(context)
    
    assert config["connector_id"] == connector_id
    assert config["network"]["allowed_hosts"] == github_connector.allowed_hosts
    assert config["network"]["allowed_ports"] == [443]
    assert config["credential"]["type"] == "github_app_token"


# 测试：审计日志
def test_audit_log_records_operations(connector_manager, github_connector):
    """测试审计日志记录操作"""
    connector_id = connector_manager.declare_connector(github_connector)
    connector_manager.approve_connector(connector_id, "approver1")
    connector_manager.revoke_connector(connector_id)
    
    log = connector_manager.get_audit_log()
    
    assert len(log) >= 3  # declare, approve, revoke
    assert log[0]["action"] == "declare"
    assert log[1]["action"] == "approve"
    assert log[2]["action"] == "revoke"


# 集成测试：完整生命周期
def test_connector_complete_lifecycle(connector_manager, github_connector):
    """测试连接器的完整生命周期"""
    # 1. 声明
    connector_id = connector_manager.declare_connector(github_connector)
    
    # 2. 审批
    version_id = connector_manager.approve_connector(connector_id, "approver")
    
    # 3. 绑定
    context = connector_manager.bind_connector_to_task(
        task_id="task-001",
        worker_id="worker-001",
        connector_id=connector_id,
        policy_version="policy-v1",
    )
    
    # 4. 验证
    allowed, _ = connector_manager.verify_network_access(
        task_id="task-001",
        connector_id=connector_id,
        destination_host="api.github.com",
        destination_port=443,
    )
    assert allowed
    
    # 5. 撤销
    connector_manager.revoke_connector(connector_id, "Policy update")
    
    # 验证撤销后无法绑定
    with pytest.raises(ValueError):
        connector_manager.bind_connector_to_task(
            task_id="task-002",
            worker_id="worker-001",
            connector_id=connector_id,
            policy_version="policy-v1",
        )
