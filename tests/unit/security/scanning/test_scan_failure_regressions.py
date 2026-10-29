"""CLI failure and real report format regressions for security scanning."""

import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.security.scanning.codeql_scanner import CodeQLScanner
from src.security.scanning.gitleaks_scanner import GitleaksScanner
from src.security.scanning.npm_scanner import NPMScanner
from src.security.scanning.pip_scanner import PipScanner
from src.security.scanning.policy_integration import ScanPolicyGateway, to_github_check_status
from src.security.scanning.result_processor import ScanDecision, ScanResultSummary


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scanner_type,manifest",
    [
        (NPMScanner, "package.json"),
        (PipScanner, "requirements.txt"),
    ],
)
@pytest.mark.parametrize("outcome", ["exit", "empty", "json", "schema", "timeout", "missing"])
async def test_failed_dependency_scan_cannot_report_clean(
    scanner_type, manifest, outcome, tmp_path
):
    (tmp_path / manifest).write_text("")
    scanner = scanner_type()
    if outcome in {"timeout", "missing"}:
        error = TimeoutError() if outcome == "timeout" else FileNotFoundError("scanner unavailable")
        scanner._run_subprocess = AsyncMock(side_effect=error)
    else:
        stdout = {"exit": "{}", "empty": "", "json": "broken", "schema": '{"error": "failed"}'}[
            outcome
        ]
        scanner._run_subprocess = AsyncMock(
            return_value=subprocess.CompletedProcess(
                [],
                2 if outcome == "exit" else 0,
                stdout,
                "scanner error",
            )
        )
    result = await scanner.scan(tmp_path)
    assert not result.success
    assert result.error_message


@pytest.mark.asyncio
async def test_pip_audit_uses_repository_requirements_and_actual_json(tmp_path):
    (tmp_path / "requirements.txt").write_text("example==1.0\n")
    scanner = PipScanner(pip_audit_path="configured-pip-audit")
    report = {
        "dependencies": [
            {
                "name": "example",
                "version": "1.0",
                "vulns": [
                    {
                        "id": "PYSEC-test",
                        "fix_versions": ["2.0"],
                        "description": "remote code execution",
                    }
                ],
            }
        ],
        "fixes": [],
    }
    scanner._run_subprocess = AsyncMock(
        return_value=subprocess.CompletedProcess(
            [],
            1,
            json.dumps(report),
            "",
        )
    )
    result = await scanner.scan(tmp_path)
    assert result.success
    assert len(result.vulnerabilities) == 1
    assert result.vulnerabilities[0].id == "PYSEC-test"
    assert result.vulnerabilities[0].fix_version == "2.0"
    cmd = scanner._run_subprocess.call_args.args[0]
    assert cmd[0] == "configured-pip-audit"
    assert cmd[cmd.index("-r") + 1] == str(tmp_path / "requirements.txt")


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["exit", "missing_report", "timeout"])
async def test_failed_codeql_analysis_is_not_clean(outcome, tmp_path):
    scanner = CodeQLScanner(database_dir=str(tmp_path / "db"))
    scanner._create_database = AsyncMock(return_value=True)
    scanner._run_subprocess = AsyncMock(
        side_effect=TimeoutError() if outcome == "timeout" else None,
        return_value=subprocess.CompletedProcess([], 2 if outcome == "exit" else 0, "", "failed"),
    )
    assert not (await scanner.scan(tmp_path)).success


@pytest.mark.asyncio
async def test_codeql_reads_sarif_runs(tmp_path):
    scanner = CodeQLScanner(database_dir=str(tmp_path / "db"))
    scanner._create_database = AsyncMock(return_value=True)

    async def analyze(cmd):
        assert "--format=sarif-latest" in cmd
        path = Path(next(arg.split("=", 1)[1] for arg in cmd if arg.startswith("--output=")))
        path.write_text(
            json.dumps(
                {
                    "version": "2.1.0",
                    "runs": [
                        {
                            "results": [
                                {
                                    "ruleId": "py/sql-injection",
                                    "level": "error",
                                    "message": {"text": "SQL Injection"},
                                }
                            ]
                        }
                    ],
                }
            )
        )
        return subprocess.CompletedProcess(cmd, 0, "", "")

    scanner._run_subprocess = analyze
    result = await scanner.scan(tmp_path)
    assert result.success, result.error_message
    assert result.findings[0].rule_id == "py/sql-injection"


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_code", [0, 1, 2])
async def test_gitleaks_missing_report_is_not_clean(exit_code, tmp_path):
    scanner = GitleaksScanner()
    scanner._run_subprocess = AsyncMock(
        return_value=subprocess.CompletedProcess([], exit_code, "", "")
    )
    assert not (await scanner.scan(tmp_path)).success


@pytest.mark.asyncio
async def test_gitleaks_uses_isolated_reports_and_accepts_finding_exit_code(tmp_path):
    scanner = GitleaksScanner()
    paths = []

    async def detect(cmd):
        path = Path(next(arg.split("=", 1)[1] for arg in cmd if arg.startswith("--report-path=")))
        paths.append(path)
        path.write_text(
            json.dumps([{"RuleID": "test", "Secret": "synthetic-test-value", "StartLine": 7}])
        )
        return subprocess.CompletedProcess(cmd, 1, "", "")

    scanner._run_subprocess = detect
    for _ in range(2):
        result = await scanner.scan(tmp_path)
        assert result.success
        assert result.secrets[0].line_number == 7
    assert paths[0] != paths[1]
    assert all(not path.exists() for path in paths)


def test_inconclusive_scan_does_not_produce_passing_github_check():
    summary = ScanResultSummary(ScanDecision.NEUTRAL, 0, 0, 0, 0)
    check = to_github_check_status(ScanPolicyGateway().evaluate(summary))
    assert check["conclusion"] == "failure"


@pytest.mark.asyncio
async def test_scanner_process_is_reaped_after_cancellation(monkeypatch):
    import asyncio

    from src.security.scanning.process import run_scanner_process

    entered = asyncio.Event()
    process = AsyncMock()
    process.returncode = None

    async def wait_for_output():
        entered.set()
        await asyncio.Future()

    from unittest.mock import Mock

    process.communicate.side_effect = wait_for_output
    process.kill = Mock()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    task = asyncio.create_task(run_scanner_process(["scanner"]))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    process.kill.assert_called_once()
    process.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_real_scanner_process_collects_output_and_exit_status():
    import sys

    from src.security.scanning.process import run_scanner_process

    result = await run_scanner_process(
        [
            sys.executable,
            "-c",
            "import sys; print('ok'); print('error', file=sys.stderr); sys.exit(7)",
        ]
    )
    assert result.returncode == 7
    assert result.stdout.strip() == "ok"
    assert result.stderr.strip() == "error"


@pytest.mark.asyncio
async def test_real_scanner_process_exits_when_cancelled(monkeypatch):
    import asyncio
    import sys

    from src.security.scanning.process import run_scanner_process

    original_spawn = asyncio.create_subprocess_exec
    started = asyncio.Event()
    processes = []

    async def spawn(*args, **kwargs):
        process = await original_spawn(*args, **kwargs)
        processes.append(process)
        started.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(
        run_scanner_process(
            [
                sys.executable,
                "-c",
                "import time; time.sleep(60)",
            ]
        )
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert processes[0].returncode is not None
    finally:
        for process in processes:
            if process.returncode is None:
                process.kill()
                await process.wait()
