"""Nox sessions —— AGENTS.md §1 适配区一键验证。

设计原则：
- 三个 session 命名与 AGENTS.md 适配区命令一一对应：lint / typecheck / test。
- 不复用 dev session 名称以避免与历史 noxfile 冲突。
- 全部使用 venv（默认），不创建独立 venv（pre-commit + ruff/mypy/pytest 已经在项目 .venv）。
- Windows + PowerShell 友好：所有命令都不依赖 bash。
"""
from __future__ import annotations

import nox

# 默认所有 session 使用项目根目录 + Python 3.12（与 mypy --python-version 一致）
# 注意：Windows + 已有 .venv 的项目，不强制 nox 创建独立 venv（用 reuse_existing_venv=True）
nox.options.reuse_existing_venv = True
nox.options.default_venv_backend = "venv"


@nox.session(name="lint", python=["3.12"])
def lint(session: nox.Session) -> None:
    """AGENTS.md §1 适配区 lint：ruff check . （含自动修复不需手工跑）"""
    session.run("ruff", "check", ".", external=True)


@nox.session(name="typecheck", python=["3.12"])
def typecheck(session: nox.Session) -> None:
    """AGENTS.md §1 适配区 typecheck：mypy --python-version 3.12 src"""
    session.run(
        "mypy",
        "--python-version",
        "3.12",
        "src",
        external=True,
    )


@nox.session(name="test", python=["3.12"])
def test(session: nox.Session) -> None:
    """AGENTS.md §1 适配区 test：pytest -q （含 unit/integration/e2e/contract）"""
    session.run("pytest", "-q", external=True)
