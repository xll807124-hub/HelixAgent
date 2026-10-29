"""Quality checks using the interpreter that starts Nox.

Install the project with its dev extra first. Sessions reuse that environment
so Windows does not require a separate Python 3.12 installation.
Keep this file ASCII for Nox versions that read it with the Windows locale.
"""

from __future__ import annotations

import sys

import nox


@nox.session(name="lint", python=False)
def lint(session: nox.Session) -> None:
    """Check the entire repository without modifying files."""
    session.run(sys.executable, "-m", "ruff", "check", ".", external=True)


@nox.session(name="typecheck", python=False)
def typecheck(session: nox.Session) -> None:
    """Check source types against the Python 3.12 target."""
    session.run(sys.executable, "-m", "mypy", "src", external=True)


@nox.session(name="test", python=False)
def test(session: nox.Session) -> None:
    """Run the project's full test suite."""
    session.run(sys.executable, "-m", "pytest", "-q", external=True)


@nox.session(name="security", python=False)
def security(session: nox.Session) -> None:
    """Run SAST, SCA and Secret scans with fail-closed evidence validation."""
    session.run(sys.executable, "scripts/security_gate.py", *session.posargs, external=True)
