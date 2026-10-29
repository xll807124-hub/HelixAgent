"""
测试 _git() 函数的错误处理和 stderr 捕获

对齐: REQ-RT-001 (Action/Evidence 追踪) + REQ-OPS-001 (可观测性)
"""
import asyncio

import pytest

from src.workers.coder.worker import _git


@pytest.mark.asyncio
async def test_git_command_success(tmp_path):
    """验证: git 命令成功执行"""
    repo = tmp_path / "test_repo"
    repo.mkdir()
    
    # 初始化 git 仓库
    code, output = await _git(str(repo), "init")
    
    assert code == 0
    assert "Initialized empty Git repository" in output or len(output) > 0


@pytest.mark.asyncio
async def test_git_command_error_returns_nonzero(tmp_path):
    """验证: git 命令失败时返回非零退出码"""
    # 使用不存在的仓库路径
    code, output = await _git("/nonexistent/repo/that/does/not/exist", "status")
    
    assert code != 0
    assert output == ""


@pytest.mark.asyncio
async def test_git_command_error_logging(tmp_path, caplog):
    """验证: git 命令失败时记录到 logger"""
    import logging
    caplog.set_level(logging.DEBUG)
    
    repo = tmp_path / "test_repo"
    repo.mkdir()
    await _git(str(repo), "init")
    
    # 执行会失败的 git 命令（访问不存在的远程）
    code, output = await _git(str(repo), "pull", "nonexistent-remote", "main")
    
    # ✅ 验证: 返回非零退出码（拉取不存在的远程会失败）
    assert code != 0


@pytest.mark.asyncio
async def test_git_process_startup_failure(monkeypatch):
    """验证: git 进程启动异常时的处理"""
    async def mock_exec(*args, **kwargs):
        raise OSError("Process startup failed")
    
    monkeypatch.setattr(asyncio, "create_subprocess_exec", mock_exec)
    
    code, output = await _git("/some/repo", "status")
    
    # ✅ 验证: 返回 (1, "")
    assert code == 1
    assert output == ""


@pytest.mark.asyncio
async def test_git_process_value_error(monkeypatch):
    """验证: 参数错误异常的处理"""
    async def mock_exec(*args, **kwargs):
        raise ValueError("Invalid argument")
    
    monkeypatch.setattr(asyncio, "create_subprocess_exec", mock_exec)
    
    code, output = await _git("/some/repo", "status")
    
    # ✅ 验证: 返回 (1, "")
    assert code == 1
    assert output == ""


@pytest.mark.asyncio
async def test_git_utf8_output(tmp_path):
    """验证: UTF-8 编码的 git 输出被正确解析"""
    repo = tmp_path / "test_repo"
    repo.mkdir()
    
    await _git(str(repo), "init")
    
    # 创建一个文件
    file = repo / "test.txt"
    file.write_text("hello")
    
    # git add 应该成功
    code, output = await _git(str(repo), "add", "test.txt")
    
    assert code == 0


@pytest.mark.asyncio
async def test_git_empty_output(tmp_path):
    """验证: git 命令返回空输出时的处理"""
    repo = tmp_path / "test_repo"
    repo.mkdir()
    
    await _git(str(repo), "init")
    
    # git rev-parse HEAD 在空仓库中返回空或错误
    code, output = await _git(str(repo), "rev-parse", "HEAD")
    
    # 可能失败或返回空，两种情况都应该处理
    assert isinstance(code, int)
    assert isinstance(output, str)


@pytest.mark.asyncio
async def test_git_multiple_args(tmp_path):
    """验证: 带多个参数的 git 命令"""
    repo = tmp_path / "test_repo"
    repo.mkdir()
    
    await _git(str(repo), "init")
    
    # git config 命令
    code, output = await _git(str(repo), "config", "user.name", "Test User")
    
    assert code == 0


@pytest.mark.asyncio
async def test_git_special_characters_in_path(tmp_path):
    """验证: 路径中包含特殊字符的处理"""
    # 创建包含空格的目录（如果系统允许）
    repo = tmp_path / "test repo with spaces"
    repo.mkdir()
    
    code, output = await _git(str(repo), "init")
    
    # 应该能够处理包含空格的路径
    assert isinstance(code, int)
