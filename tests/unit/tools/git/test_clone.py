"""
Git Clone 工具单元测试
"""
import pytest
import tempfile
from pathlib import Path

from src.tools.base import ExecutionContext, RiskLevel
from src.tools.git.clone import GitCloneTool


@pytest.fixture
def tool():
    """创建工具实例"""
    return GitCloneTool()


@pytest.fixture
def execution_context():
    """创建执行上下文"""
    return ExecutionContext(
        trace_id="test-123",
        action_id="action-123",
        user_id="user-123",
        organization_id="org-123",
        project_id="project-123",
        task_id="task-123",
    )


class TestGitCloneToolProperties:
    """工具属性测试"""

    def test_tool_name(self, tool):
        """测试工具名称"""
        assert tool.name == "git-clone"

    def test_tool_description(self, tool):
        """测试工具描述"""
        assert "clone" in tool.description.lower()

    def test_tool_risk_level(self, tool):
        """测试风险等级"""
        assert tool.risk_level == RiskLevel.MEDIUM

    def test_timeout_seconds(self, tool):
        """测试超时时间"""
        assert tool.timeout_seconds == 60

    def test_capabilities(self, tool):
        """测试能力标签"""
        assert "git" in tool.capabilities
        assert "clone" in tool.capabilities

    def test_input_schema(self, tool):
        """测试输入 Schema"""
        schema = tool.input_schema
        assert "properties" in schema
        assert "repo_url" in schema["properties"]
        assert "target_dir" in schema["properties"]
        assert "repo_url" in schema["required"]
        assert "target_dir" in schema["required"]

    def test_output_schema(self, tool):
        """测试输出 Schema"""
        schema = tool.output_schema
        assert "properties" in schema
        assert "cloned_path" in schema["properties"]
        assert "commit_hash" in schema["properties"]


class TestGitCloneToolValidation:
    """输入验证测试"""

    def test_validate_missing_repo_url(self, tool):
        """测试缺失 repo_url"""
        result = tool.validate_input({"target_dir": "repo"})
        assert not result.valid
        assert any("repo_url" in e for e in result.errors)

    def test_validate_missing_target_dir(self, tool):
        """测试缺失 target_dir"""
        result = tool.validate_input({"repo_url": "https://github.com/user/repo"})
        assert not result.valid
        assert any("target_dir" in e for e in result.errors)

    def test_validate_invalid_repo_url(self, tool):
        """测试无效的 repo_url"""
        result = tool.validate_input({
            "repo_url": "https://example.com/repo",
            "target_dir": "repo",
        })
        assert not result.valid
        assert any("GitHub" in e for e in result.errors)

    def test_validate_valid_https_url(self, tool):
        """测试有效的 HTTPS URL"""
        result = tool.validate_input({
            "repo_url": "https://github.com/user/repo",
            "target_dir": "repo",
        })
        assert result.valid

    def test_validate_valid_ssh_url(self, tool):
        """测试有效的 SSH URL"""
        result = tool.validate_input({
            "repo_url": "git@github.com:user/repo",
            "target_dir": "repo",
        })
        assert result.valid

    def test_validate_path_traversal(self, tool):
        """测试路径穿越拒绝"""
        result = tool.validate_input({
            "repo_url": "https://github.com/user/repo",
            "target_dir": "../../etc/passwd",
        })
        assert not result.valid
        assert any("relative" in e.lower() for e in result.errors)

    def test_validate_invalid_depth(self, tool):
        """测试无效的深度参数"""
        result = tool.validate_input({
            "repo_url": "https://github.com/user/repo",
            "target_dir": "repo",
            "depth": -1,
        })
        assert not result.valid

    def test_validate_success(self, tool):
        """测试验证成功"""
        result = tool.validate_input({
            "repo_url": "https://github.com/user/repo",
            "target_dir": "repo",
            "branch": "main",
            "depth": 0,
        })
        assert result.valid
        assert len(result.errors) == 0


class TestGitCloneToolMetadata:
    """元数据测试"""

    def test_output_schema_completeness(self, tool):
        """测试输出 Schema 完整性"""
        schema = tool.output_schema
        required_fields = ["cloned_path", "commit_hash", "branch", "remote_url"]
        for field in required_fields:
            assert field in schema["properties"]
