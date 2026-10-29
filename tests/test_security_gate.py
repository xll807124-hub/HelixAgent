"""Security gate regression: scanner failures must never become a green result."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tarfile
import zipfile
from types import SimpleNamespace

import pytest

from scripts import install_security_tools as installer
from scripts import security_gate as gate


def sast(*severities):
    return {"errors": [], "metrics": {"_totals": {"loc": 10}, "src/app.py": {}},
            "results": [{"issue_severity": s, "test_id": "B999"} for s in severities]}


@pytest.mark.parametrize(("levels", "blocked"), [
    ([], False), (["LOW"] * 100, False), (["MEDIUM"] * 4, False),
    (["MEDIUM"] * 5, True), (["HIGH"], True),
])
def test_sast_severity_boundaries(levels, blocked):
    result = gate.evaluate_sast(sast(*levels), int(bool(levels)))
    assert result["blocked"] is blocked


@pytest.mark.parametrize("data", [
    {}, {"errors": ["parse failure"]}, {"errors": [], "results": []},
    {"errors": [], "results": [], "metrics": {"_totals": {"loc": 0}}},
    sast("UNKNOWN"),
])
def test_sast_incomplete_scan_never_passes(data):
    with pytest.raises(gate.ScanError):
        gate.evaluate_sast(data, 0)


@pytest.mark.parametrize(("data", "code"), [(sast(), 1), (sast("HIGH"), 0)])
def test_sast_exit_report_mismatch(data, code):
    with pytest.raises(gate.ScanError):
        gate.evaluate_sast(data, code)


def sca(vulns=None):
    return {"dependencies": [{"name": "example-package", "version": "1.0",
                               "vulns": vulns or []}]}


def test_sca_all_advisories_block_without_assuming_severity():
    assert not gate.evaluate_sca(sca(), 0)["blocked"]
    assert gate.evaluate_sca(sca([{"id": "TEST-ADVISORY"}]), 1)["blocked"]


def test_sca_only_local_editable_project_may_be_skipped():
    data = sca()
    data["dependencies"].append({"name": "ai-agent-platform", "skip_reason": "editable package"})
    assert gate.evaluate_sca(data, 0)["skipped"] == ["ai-agent-platform"]
    data["dependencies"][-1]["name"] = "unknown-package"
    with pytest.raises(gate.ScanError):
        gate.evaluate_sca(data, 0)


@pytest.mark.parametrize(("data", "code"), [
    ({}, 0), ({"dependencies": []}, 0), ({"dependencies": ["invalid"]}, 0),
    ({"dependencies": [{"name": "example"}]}, 0), (sca(), 1),
    (sca([{}]), 1), (sca([{"id": "TEST"}]), 0),
    ({"dependencies": [{"name": "ai-agent-platform", "skip_reason": "editable"}]}, 0),
])
def test_sca_incomplete_or_inconsistent_evidence(data, code):
    with pytest.raises(gate.ScanError):
        gate.evaluate_sca(data, code)


@pytest.mark.parametrize("code", [2, 127, -1])
def test_scanner_execution_error_cannot_reuse_success_report(tmp_path, code):
    report = tmp_path / "report.json"
    report.write_text("[]")
    with pytest.raises(gate.ScanError):
        gate.read_report(report, code)


def test_missing_and_corrupt_reports_fail(tmp_path):
    report = tmp_path / "report.json"
    for content in (None, "not-json"):
        if content is not None:
            report.write_text(content)
        with pytest.raises(gate.ScanError):
            gate.read_report(report, 0)


def test_missing_tool_and_real_process_timeout_fail_without_retry(tmp_path):
    with pytest.raises(gate.ScanError, match="FileNotFoundError"):
        gate.run([str(tmp_path / "missing-scanner")])
    with pytest.raises(gate.ScanError, match="TimeoutExpired"):
        gate.run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.05)


def test_secret_fixture_review_does_not_hide_replacement_or_other_file(tmp_path):
    source = "synthetic fixture"
    path = tmp_path / "fixture.py"
    path.write_text(source)
    finding = {"File": str(path), "RuleID": "example-rule", "StartLine": 1, "EndLine": 1}
    reviews = [{"path": "fixture.py", "rule": "example-rule", "reason": "test fixture",
                "source_sha256": hashlib.sha256(source.encode()).hexdigest()}]
    args = {"root": tmp_path, "tree": tmp_path, "reviews": reviews}
    assert not gate.evaluate_secrets([finding], 1, **args)["blocked"]
    path.write_text("changed credential material")
    assert gate.evaluate_secrets([finding], 1, **args)["unreviewed"] == 1
    other = tmp_path / "app.py"
    other.write_text(source)
    finding["File"] = str(other)
    assert gate.evaluate_secrets([finding], 1, **args)["blocked"]


@pytest.mark.parametrize(("data", "code"), [({}, 0), ([], 1), ([{}], 1), ([{}], 0)])
def test_invalid_secret_report_blocks(tmp_path, data, code):
    with pytest.raises(gate.ScanError):
        gate.evaluate_secrets(data, code, root=tmp_path, tree=tmp_path, reviews=[])


def test_snapshot_includes_untracked_and_modified_files_but_not_generated_cache(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    (repo / ".gitignore").write_text("cache/\n")
    (repo / "tracked.py").write_text("before")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    (repo / "tracked.py").write_text("after")
    (repo / "new.py").write_text("new")
    (repo / "cache").mkdir()
    (repo / "cache/data").write_text("generated")
    target = tmp_path / "snapshot"
    assert gate.snapshot(repo, target) == 3
    assert (target / "tracked.py").read_text() == "after"
    assert (target / "new.py").exists()
    assert not (target / "cache").exists()


def test_cli_exception_overwrites_stale_green_summary(tmp_path, monkeypatch, capsys):
    (tmp_path / "summary.json").write_text('{"status":"passed"}')

    def fail(_):
        raise gate.ScanError("private scanner output must not be echoed")

    monkeypatch.setattr(gate, "scan", fail)
    monkeypatch.setattr(sys, "argv", ["security_gate.py", "--output-dir", str(tmp_path)])
    assert gate.main() == 2
    assert json.loads((tmp_path / "summary.json").read_text())["status"] == "error"
    assert "private scanner" not in capsys.readouterr().out


@pytest.mark.parametrize("valid_checksum", [True, False])
def test_installer_checksum_before_write(tmp_path, monkeypatch, valid_checksum):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("gitleaks.exe", b"verified fixture binary")
        z.writestr("../outside.txt", b"must not extract")
    data = archive.getvalue()
    checksum = hashlib.sha256(data).hexdigest() if valid_checksum else "0" * 64
    (tmp_path / "security").mkdir()
    (tmp_path / "security/tools.json").write_text(json.dumps({"gitleaks": {
        "version": "test", "assets": {"Windows": {"filename": "test.zip", "sha256": checksum}}
    }}))
    monkeypatch.setattr(installer, "ROOT", tmp_path)
    monkeypatch.setattr(installer.platform, "system", lambda: "Windows")
    monkeypatch.setattr(installer.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(installer.requests, "get", lambda *a, **kw: SimpleNamespace(
        content=data, raise_for_status=lambda: None))
    if valid_checksum:
        assert installer.install().read_bytes() == b"verified fixture binary"
    else:
        with pytest.raises(RuntimeError, match="checksum"):
            installer.install()
        assert not (tmp_path / ".tools").exists()
    assert not (tmp_path / "outside.txt").exists()


def test_history_fixture_review_uses_committed_content(tmp_path, monkeypatch):
    source = "public example"
    review = {"path": "test.py", "rule": "test", "reason": "public fixture",
              "source_sha256": hashlib.sha256(source.encode()).hexdigest()}
    finding = {"File": "test.py", "RuleID": "test", "StartLine": 1, "EndLine": 1,
               "Commit": "a" * 40}
    monkeypatch.setattr(gate, "git_output", lambda *a: source)
    assert not gate.evaluate_secrets([finding], 1, root=tmp_path, tree=None,
                                    reviews=[review])["blocked"]
    finding["Commit"] = "invalid"
    with pytest.raises(gate.ScanError, match="commit"):
        gate.evaluate_secrets([finding], 1, root=tmp_path, tree=None, reviews=[review])


@pytest.mark.parametrize("change", ["location", "bounds", "traversal"])
def test_secret_source_validation(tmp_path, change):
    (tmp_path / "test.py").write_text("fixture")
    finding = {"File": "test.py", "RuleID": "test", "StartLine": 1, "EndLine": 1}
    if change == "location":
        finding["StartLine"] = 0
    elif change == "bounds":
        finding["EndLine"] = 99
    else:
        finding["File"] = "../outside.py"
    with pytest.raises(gate.ScanError):
        gate.evaluate_secrets([finding], 1, root=tmp_path, tree=tmp_path, reviews=[])


def test_git_failure_and_empty_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "run", lambda *a, **kw: SimpleNamespace(returncode=1))
    with pytest.raises(gate.ScanError):
        gate.git_output(["ls-files"], tmp_path)
    monkeypatch.setattr(gate, "git_output", lambda *a: "")
    with pytest.raises(gate.ScanError, match="Empty"):
        gate.snapshot(tmp_path, tmp_path / "snapshot")


@pytest.mark.parametrize(("mode", "expected"), [
    ("clean", "passed"), ("finding", "blocked"), ("tool-missing", "error"),
    ("wrong-version", "error"), ("shallow", "error"), ("corrupt-report", "error"),
    ("network-failure", "error"), ("invalid-reviews", "error"), ("ignore-file", "error"),
])
def test_complete_orchestration_fail_closed(tmp_path, monkeypatch, mode, expected):
    # Fake tools isolate orchestration from the network; real tools are also run at delivery.
    config = json.loads((gate.ROOT / "security/tools.json").read_text())
    (tmp_path / "security").mkdir()
    (tmp_path / "security/tools.json").write_text(json.dumps(config))
    (tmp_path / "security/secret-fixtures.json").write_text(
        '{}' if mode == "invalid-reviews" else '[]')
    if mode == "ignore-file":
        (tmp_path / ".gitleaksignore").write_text("unapproved")
    monkeypatch.setattr(gate.importlib.metadata, "version", lambda p:
                        "wrong" if mode == "wrong-version" else config[p])
    monkeypatch.setattr(gate, "git_output", lambda *a:
                        "true" if mode == "shallow" else "false")
    monkeypatch.setattr(gate, "snapshot", lambda *a: 1)

    def execute(command, **kw):
        if mode == "tool-missing":
            raise gate.ScanError("tool unavailable")
        if command[-1] == "version":
            return SimpleNamespace(returncode=0, stdout=config["gitleaks"]["version"])
        if "bandit" in command:
            data = sast("HIGH") if mode == "finding" else sast()
        elif "pip_audit" in command:
            if mode == "network-failure":
                return SimpleNamespace(returncode=2, stderr="network unavailable")
            data = sca()
        else:
            assert "--redact=100" in command
            assert "--ignore-gitleaks-allow" in command
            data = []
        from pathlib import Path
        Path(command[-1]).write_text('bad-json' if mode == "corrupt-report" else json.dumps(data))
        return SimpleNamespace(returncode=int("bandit" in command and mode == "finding"), stderr="")

    monkeypatch.setattr(gate, "run", execute)
    if expected == "error":
        with pytest.raises(gate.ScanError):
            gate.scan(tmp_path / "output", root=tmp_path)
    else:
        result = gate.scan(tmp_path / "output", root=tmp_path)
        assert result["status"] == expected
        assert len(result["scans"]) == 4


@pytest.mark.parametrize("status,code", [("passed", 0), ("blocked", 1)])
def test_cli_result_codes(tmp_path, monkeypatch, status, code):
    monkeypatch.setattr(gate, "scan", lambda _: {"status": status})
    monkeypatch.setattr(sys, "argv", ["security_gate.py", "--output-dir", str(tmp_path)])
    assert gate.main() == code


def test_linux_installer_extracts_only_expected_member(tmp_path, monkeypatch):
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        info = tarfile.TarInfo("gitleaks")
        data = b"binary fixture"
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    raw = archive.getvalue()
    (tmp_path / "security").mkdir()
    (tmp_path / "security/tools.json").write_text(json.dumps({"gitleaks": {
        "version": "test", "assets": {"Linux": {
            "filename": "test.tar.gz", "sha256": hashlib.sha256(raw).hexdigest()}}
    }}))
    monkeypatch.setattr(installer, "ROOT", tmp_path)
    monkeypatch.setattr(installer.platform, "system", lambda: "Linux")
    monkeypatch.setattr(installer.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(installer.requests, "get", lambda *a, **kw: SimpleNamespace(
        content=raw, raise_for_status=lambda: None))
    assert installer.install().read_bytes() == data
    monkeypatch.setattr(installer.platform, "machine", lambda: "arm64")
    with pytest.raises(RuntimeError, match="platforms"):
        installer.install()
