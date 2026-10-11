"""
Git Status/Commit/Diff/PR 工具单元测试
"""
import pytest

from src.tools.base import ExecutionContext, RiskLevel
from src.tools.git.commit import GitCommitTool
from src.tools.git.diff import GitDiffTool
from src.tools.git.pr import GitPullRequestTool
from src.tools.git.status import GitStatusTool


@pytest.fixture
def execution_context():
    return ExecutionContext(
        trace_id="test-123",
        action_id="action-123",
        user_id="user-123",
        organization_id="org-123",
        project_id="project-123",
        task_id="task-123",
    )


# ============ Git Status Tests ============

class TestGitStatusTool:
    """Git Status 工具测试"""

    def test_tool_properties(self):
        tool = GitStatusTool()
        assert tool.name == "git-status"
        assert tool.risk_level == RiskLevel.LOW
        assert "status" in tool.capabilities

    def test_input_schema(self):
        tool = GitStatusTool()
        schema = tool.input_schema
        assert "repo_path" in schema["properties"]
        assert "repo_path" in schema["required"]

    def test_output_schema(self):
        tool = GitStatusTool()
        schema = tool.output_schema
        assert "branch" in schema["properties"]
        assert "modified_files" in schema["properties"]

    def test_validate_missing_repo_path(self):
        tool = GitStatusTool()
        result = tool.validate_input({})
        assert not result.valid

    def test_validate_path_traversal(self):
        tool = GitStatusTool()
        result = tool.validate_input({"repo_path": "../../etc/passwd"})
        assert not result.valid

    def test_validate_success(self):
        tool = GitStatusTool()
        result = tool.validate_input({"repo_path": "/path/to/repo"})
        assert result.valid


# ============ Git Commit Tests ============

class TestGitCommitTool:
    """Git Commit 工具测试"""

    def test_tool_properties(self):
        tool = GitCommitTool()
        assert tool.name == "git-commit"
        assert tool.risk_level == RiskLevel.HIGH
        assert "commit" in tool.capabilities

    def test_input_schema(self):
        tool = GitCommitTool()
        schema = tool.input_schema
        assert "message" in schema["properties"]
        assert "repo_path" in schema["required"]
        assert "message" in schema["required"]

    def test_validate_missing_message(self):
        tool = GitCommitTool()
        result = tool.validate_input({"repo_path": "/path"})
        assert not result.valid

    def test_validate_short_message(self):
        tool = GitCommitTool()
        result = tool.validate_input({
            "repo_path": "/path",
            "message": "ab",
        })
        assert not result.valid
        assert any("3 characters" in e for e in result.errors)

    def test_validate_long_message(self):
        tool = GitCommitTool()
        long_msg = "x" * 1001
        result = tool.validate_input({
            "repo_path": "/path",
            "message": long_msg,
        })
        assert not result.valid

    def test_validate_success(self):
        tool = GitCommitTool()
        result = tool.validate_input({
            "repo_path": "/path",
            "message": "Fix: important bug",
        })
        assert result.valid


# ============ Git Diff Tests ============

class TestGitDiffTool:
    """Git Diff 工具测试"""

    def test_tool_properties(self):
        tool = GitDiffTool()
        assert tool.name == "git-diff"
        assert tool.risk_level == RiskLevel.LOW
        assert "diff" in tool.capabilities

    def test_input_schema(self):
        tool = GitDiffTool()
        schema = tool.input_schema
        assert "repo_path" in schema["properties"]
        assert "repo_path" in schema["required"]

    def test_output_schema(self):
        tool = GitDiffTool()
        schema = tool.output_schema
        assert "diff_content" in schema["properties"]
        assert "files_changed" in schema["properties"]

    def test_validate_missing_repo_path(self):
        tool = GitDiffTool()
        result = tool.validate_input({})
        assert not result.valid

    def test_validate_success(self):
        tool = GitDiffTool()
        result = tool.validate_input({"repo_path": "/path"})
        assert result.valid

    def test_parse_diff_stats_empty(self):
        tool = GitDiffTool()
        stats = tool._parse_diff_stats("")
        assert stats["files"] == 0
        assert stats["insertions"] == 0
        assert stats["deletions"] == 0

    def test_parse_diff_stats_with_changes(self):
        tool = GitDiffTool()
        diff_content = """diff --git a/file1.py b/file1.py
+++ b/file1.py
+new line
-old line"""
        stats = tool._parse_diff_stats(diff_content)
        assert stats["files"] == 1
        assert stats["insertions"] == 1
        assert stats["deletions"] == 1


# ============ Git PR Tests ============

class TestGitPullRequestTool:
    """Git PR 工具测试"""

    def test_tool_properties(self):
        tool = GitPullRequestTool()
        assert tool.name == "git-pr"
        assert tool.risk_level == RiskLevel.HIGH
        assert "pr" in tool.capabilities

    def test_input_schema(self):
        tool = GitPullRequestTool()
        schema = tool.input_schema
        assert "title" in schema["properties"]
        assert "repo_path" in schema["required"]
        assert "title" in schema["required"]

    def test_output_schema(self):
        tool = GitPullRequestTool()
        schema = tool.output_schema
        assert "pr_number" in schema["properties"]
        assert "pr_url" in schema["properties"]

    def test_validate_missing_title(self):
        tool = GitPullRequestTool()
        result = tool.validate_input({"repo_path": "/path"})
        assert not result.valid

    def test_validate_short_title(self):
        tool = GitPullRequestTool()
        result = tool.validate_input({
            "repo_path": "/path",
            "title": "abc",
        })
        assert not result.valid

    def test_validate_long_title(self):
        tool = GitPullRequestTool()
        long_title = "x" * 201
        result = tool.validate_input({
            "repo_path": "/path",
            "title": long_title,
        })
        assert not result.valid

    def test_validate_success(self):
        tool = GitPullRequestTool()
        result = tool.validate_input({
            "repo_path": "/path",
            "title": "Feature: add new functionality",
        })
        assert result.valid

    def test_parse_github_url_https(self):
        tool = GitPullRequestTool()
        owner, repo = tool._parse_github_url("https://github.com/user/myrepo")
        assert owner == "user"
        assert repo == "myrepo"

    def test_parse_github_url_https_with_git(self):
        tool = GitPullRequestTool()
        owner, repo = tool._parse_github_url("https://github.com/user/myrepo.git")
        assert owner == "user"
        assert repo == "myrepo"

    def test_parse_github_url_ssh(self):
        tool = GitPullRequestTool()
        owner, repo = tool._parse_github_url("git@github.com:user/myrepo")
        assert owner == "user"
        assert repo == "myrepo"

    def test_parse_github_url_ssh_with_git(self):
        tool = GitPullRequestTool()
        owner, repo = tool._parse_github_url("git@github.com:user/myrepo.git")
        assert owner == "user"
        assert repo == "myrepo"

    def test_parse_github_url_invalid(self):
        tool = GitPullRequestTool()
        owner, repo = tool._parse_github_url("https://example.com/user/repo")
        assert owner == ""
        assert repo == ""
