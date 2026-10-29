"""Run real security tools; missing/incomplete evidence always fails closed."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ScanError(RuntimeError):
    """A scan could not establish a valid result."""


def run(command: list[str], *, cwd: Path = ROOT, timeout: int = 300) -> subprocess.CompletedProcess:
    """Use argv, a deadline and captured output; never echo scanner secret material."""
    try:
        return subprocess.run(command, cwd=cwd, timeout=timeout, capture_output=True,
                              encoding="utf-8", errors="replace", check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ScanError(type(exc).__name__) from exc


def read_report(path: Path, code: int) -> object:
    if code not in (0, 1):
        raise ScanError(f"Scanner execution failed (exit {code})")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ScanError("Missing or invalid JSON report") from exc


def evaluate_sast(data: object, code: int) -> dict:
    if not isinstance(data, dict) or data.get("errors") != []:
        raise ScanError("SAST errors or missing error inventory")
    findings = data.get("results")
    metrics = data.get("metrics", {})
    if not isinstance(findings, list) or metrics.get("_totals", {}).get("loc", 0) <= 0:
        raise ScanError("SAST has no valid target inventory")
    counts = Counter()
    for item in findings:
        if not isinstance(item, dict):
            raise ScanError("Invalid SAST finding")
        severity = item.get("issue_severity")
        if severity not in ("HIGH", "MEDIUM", "LOW") or not item.get("test_id"):
            raise ScanError("Invalid SAST finding")
        counts[severity] += 1
    if code != int(bool(findings)):
        raise ScanError("SAST exit/report mismatch")
    return {"blocked": counts["HIGH"] >= 1 or counts["MEDIUM"] >= 5,
            "high": counts["HIGH"], "medium": counts["MEDIUM"], "low": counts["LOW"],
            "files": len(metrics) - 1, "lines": metrics["_totals"]["loc"]}


def evaluate_sca(data: object, code: int) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get("dependencies"), list):
        raise ScanError("Invalid SCA dependency inventory")
    dependencies = data["dependencies"]
    if not dependencies:
        raise ScanError("Empty SCA dependency inventory")
    count = 0
    skipped = []
    for dep in dependencies:
        if not isinstance(dep, dict):
            raise ScanError("Invalid SCA dependency")
        if dep.get("skip_reason"):
            # Only our editable distribution lacks advisory metadata; dependencies are scanned.
            if dep.get("name") != "ai-agent-platform" or "editable" not in dep["skip_reason"]:
                raise ScanError("Unexpected skipped dependency")
            skipped.append(dep["name"])
            continue
        if not dep.get("name") or not dep.get("version") or not isinstance(dep.get("vulns"), list):
            raise ScanError("Incomplete SCA dependency")
        for vuln in dep["vulns"]:
            if not isinstance(vuln, dict) or not vuln.get("id"):
                raise ScanError("Invalid SCA advisory")
        count += len(dep["vulns"])
    if len(skipped) == len(dependencies) or code != int(count > 0):
        raise ScanError("SCA exit/report mismatch or no audited dependencies")
    return {"blocked": count > 0, "vulnerabilities": count,
            "dependencies": len(dependencies), "skipped": skipped}


def git_output(args: list[str], root: Path) -> str:
    result = run(["git", *args], cwd=root)
    if result.returncode:
        raise ScanError("Git inventory unavailable")
    return result.stdout


def snapshot(root: Path, target: Path) -> int:
    """Scan tracked and non-ignored untracked files, including uncommitted changes."""
    names = git_output(["ls-files", "--cached", "--others", "--exclude-standard", "-z"], root)
    count = 0
    for name in sorted(set(names.split("\0")) - {""}):
        source = root / name
        if not source.exists() or source.is_dir():
            continue  # Deleted files and submodule pointers are not current file contents.
        if source.is_symlink() or not source.resolve().is_relative_to(root.resolve()):
            raise ScanError("Unsafe path in repository inventory")
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        count += 1
    if count == 0:
        raise ScanError("Empty worktree snapshot")
    return count


def evaluate_secrets(data: object, code: int, *, root: Path, tree: Path | None,
                     reviews: list[dict]) -> dict:
    if not isinstance(data, list) or code != int(bool(data)):
        raise ScanError("Invalid Secret report or exit/report mismatch")
    reviewed = 0
    for item in data:
        if not isinstance(item, dict) or not item.get("RuleID") or not item.get("File"):
            raise ScanError("Invalid Secret finding")
        start, end = item.get("StartLine"), item.get("EndLine")
        if not isinstance(start, int) or not isinstance(end, int) or not 1 <= start <= end:
            raise ScanError("Invalid Secret location")
        path = Path(item["File"])
        if tree is not None:
            if path.is_absolute():
                path = path.relative_to(tree)
            full = tree / path
            if not full.resolve().is_relative_to(tree.resolve()):
                raise ScanError("Secret path outside snapshot")
            source = full.read_text(encoding="utf-8")
        else:
            commit = item.get("Commit", "")
            if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
                raise ScanError("Invalid Secret commit")
            source = git_output(["show", f"{commit}:{path.as_posix()}"], root)
        lines = source.splitlines()
        if end > len(lines):
            raise ScanError("Secret location outside source")
        digest = hashlib.sha256("\n".join(lines[start - 1:end]).encode()).hexdigest()
        # Reviewed fixtures are bound to both file and exact source content. Replacing a
        # fixture with a real credential invalidates the fingerprint and blocks the gate.
        match = any(r.get("path") == path.as_posix() and r.get("rule") == item["RuleID"]
                    and r.get("source_sha256") == digest and r.get("reason") for r in reviews)
        reviewed += int(match)
    return {"blocked": len(data) > reviewed, "raw_findings": len(data),
            "reviewed_fixtures": reviewed, "unreviewed": len(data) - reviewed}


def scan(output: Path, root: Path = ROOT) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    config = json.loads((root / "security/tools.json").read_text(encoding="utf-8"))
    reviews = json.loads((root / "security/secret-fixtures.json").read_text(encoding="utf-8"))
    if not isinstance(reviews, list) or any(not isinstance(r, dict) for r in reviews):
        raise ScanError("Invalid reviewed fixture inventory")
    if (root / ".gitleaksignore").exists():
        raise ScanError("Use content-bound fixture reviews, not Gitleaks fingerprint ignores")
    results: dict = {}
    for package in ("bandit", "pip-audit"):
        if importlib.metadata.version(package) != config[package]:
            raise ScanError(f"Unexpected {package} version")
    exe = root / ".tools/gitleaks" / config["gitleaks"]["version"] / (
        "gitleaks.exe" if os.name == "nt" else "gitleaks")
    version = run([str(exe), "version"], cwd=root)
    if version.returncode or version.stdout.strip() != config["gitleaks"]["version"]:
        raise ScanError("Unexpected Gitleaks version")
    if git_output(["rev-parse", "--is-shallow-repository"], root).strip() != "false":
        raise ScanError("Full Git history is required; fetch with depth 0")

    for name, args, evaluate in (
        ("sast", ["-m", "bandit", "-r", "src", "scripts", "noxfile.py", "--ignore-nosec",
                  "-f", "json", "-o"], evaluate_sast),
        ("sca", ["-m", "pip_audit", "--local", "--skip-editable", "--format", "json",
                 "--output"], evaluate_sca),
    ):
        report = output / f"{name}.json"
        report.unlink(missing_ok=True)  # Stale success must never mask a failed new scan.
        proc = run([sys.executable, *args, str(report)], cwd=root)
        (output / f"{name}.log").write_text(proc.stderr, encoding="utf-8")
        results[name] = evaluate(read_report(report, proc.returncode), proc.returncode)

    with tempfile.TemporaryDirectory(prefix="ai-agent-secret-snapshot-") as tmp:
        tree = Path(tmp)
        count = snapshot(root, tree)
        for name, args, current in (
            ("secret-worktree", ["dir", str(tree)], tree),
            ("secret-history", ["git", str(root), "--log-opts=--all"], None),
        ):
            report = output / f"{name}.json"
            report.unlink(missing_ok=True)
            proc = run([str(exe), *args, "--config", str(root / "security/gitleaks.toml"),
                        "--redact=100", "--no-banner", "--ignore-gitleaks-allow",
                        "--report-format=json", "--report-path", str(report)], cwd=root)
            (output / f"{name}.log").write_text(proc.stderr, encoding="utf-8")
            results[name] = evaluate_secrets(read_report(report, proc.returncode), proc.returncode,
                                             root=root, tree=current, reviews=reviews)
        results["secret-worktree"]["files"] = count
    return {"status": "blocked" if any(r["blocked"] for r in results.values()) else "passed",
            "tools": config, "scans": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".security-reports")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    try:
        summary = scan(output)
        code = 1 if summary["status"] == "blocked" else 0
    except Exception as exc:
        # Errors may contain credentials/paths from external tools: report only their type.
        summary = {"status": "error", "error_type": type(exc).__name__}
        code = 2
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
