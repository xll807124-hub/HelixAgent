"""
Git Branch 工具单元测试
"""
import pytest

from src.tools.base import ExecutionContext, RiskLevel
from src.tools.git.branch import GitBranchTool


@pytest.fixture
def tool():
    """创建工具实例"""
    return GitBranchTool()


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


class TestGitBranchToolProperties:
    """工具属性测试"""

    def test_tool_name(self, tool):
        assert tool.name == "git-branch"

    def test_tool_description(self, tool):
        assert "branch" in tool.description.lower()

    def test_tool_risk_level(self, tool):
        assert tool.risk_level == RiskLevel.MEDIUM

    def test_input_schema(self, tool):
        schema = tool.input_schema
        assert "action" in schema["properties"]
        assert schema["properties"]["action"]["enum"] == ["create", "switch", "delete", "list"]

    def test_output_schema(self, tool):
        schema = tool.output_schema
        assert "current_branch" in schema["properties"]
        assert "all_branches" in schema["properties"]


class TestGitBranchToolValidation:
    """输入验证测试"""

    def test_validate_missing_action(self, tool):
        result = tool.validate_input({"repo_path": "/path/to/repo"})
        assert not result.valid

    def test_validate_create_without_branch_name(self, tool):
        result = tool.validate_input({
            "repo_path": "/path/to/repo",
            "action": "create",
        })
        assert not result.valid
        assert any("branch_name" in e for e in result.errors)

    def test_validate_switch_without_branch_name(self, tool):
        result = tool.validate_input({
            "repo_path": "/path/to/repo",
            "action": "switch",
        })
        assert not result.valid

    def test_validate_delete_without_branch_name(self, tool):
        result = tool.validate_input({
            "repo_path": "/path/to/repo",
            "action": "delete",
        })
        assert not result.valid

    def test_validate_invalid_branch_name_with_dash(self, tool):
        result = tool.validate_input({
            "repo_path": "/path/to/repo",
            "action": "create",
            "branch_name": "-invalid",
        })
        assert not result.valid

    def test_validate_valid_create(self, tool):
        result = tool.validate_input({
            "repo_path": "/path/to/repo",
            "action": "create",
            "branch_name": "feature/new-feature",
        })
        assert result.valid

    def test_validate_valid_switch(self, tool):
        result = tool.validate_input({
            "repo_path": "/path/to/repo",
            "action": "switch",
            "branch_name": "main",
        })
        assert result.valid

    def test_validate_valid_list(self, tool):
        result = tool.validate_input({
            "repo_path": "/path/to/repo",
            "action": "list",
        })
        assert result.valid

    def test_validate_force_delete(self, tool):
        result = tool.validate_input({
            "repo_path": "/path/to/repo",
            "action": "delete",
            "branch_name": "old-branch",
            "force": True,
        })
        assert result.valid


class TestGitBranchBranchNameValidation:
    """分支名称验证测试"""

    def test_valid_branch_names(self, tool):
        valid_names = [
            "main",
            "master",
            "develop",
            "feature/new-feature",
            "bugfix/issue-123",
            "release-1.0",
            "v1.0.0",
        ]
        for name in valid_names:
            assert tool._is_valid_branch_name(name), f"Should accept: {name}"

    def test_invalid_branch_names(self, tool):
        invalid_names = [
            "",
            "-invalid",
            "branch.lock",
            "branch with spaces",
            "branch\twith\ttabs",
            "branch...name",
        ]
        for name in invalid_names:
            assert not tool._is_valid_branch_name(name), f"Should reject: {name}"
