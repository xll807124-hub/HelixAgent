"""
Integration Test: SCA Real Scan Verification

Test npm audit and pip-audit real execution

Run: python test_sca_integration.py
"""

import asyncio
import tempfile
from pathlib import Path
import json
import sys
import subprocess

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent))

from src.security.scanning.npm_scanner import NPMScanner
from src.security.scanning.pip_scanner import PipScanner
from src.security.scanning.sca_orchestrator import SCAOrchestrator


def setup_test_npm_project():
    """Create test Node.js project"""
    temp_dir = Path(tempfile.gettempdir()) / "npm-test-project"
    temp_dir.mkdir(exist_ok=True)
    
    # Create package.json with known vulnerable packages
    package_json = {
        "name": "test-app",
        "version": "1.0.0",
        "dependencies": {
            "lodash": "4.17.15"  # Known vulnerable version
        }
    }
    
    with open(temp_dir / "package.json", "w") as f:
        json.dump(package_json, f, indent=2)
    
    # Run npm install to install dependencies
    try:
        print(f"  [*] Running 'npm install' in {temp_dir}...")
        result = subprocess.run(
            [r"C:\Program Files\nodejs\npm.cmd", "install"],
            cwd=str(temp_dir),
            capture_output=True,
            timeout=60
        )
        if result.returncode != 0:
            print(f"  [!] npm install failed: {result.stderr.decode()[:200]}")
    except Exception as e:
        print(f"  [!] npm install error: {e}")
    
    return temp_dir


def setup_test_pip_project():
    """Create test Python project"""
    temp_dir = Path(tempfile.gettempdir()) / "pip-test-project"
    temp_dir.mkdir(exist_ok=True)
    
    # Create requirements.txt with known vulnerable packages
    requirements = """
requests==2.28.0
Werkzeug==2.0.0
"""
    
    with open(temp_dir / "requirements.txt", "w") as f:
        f.write(requirements)
    
    return temp_dir


async def test_npm_scanner():
    """Test npm scanner"""
    print("\n=== Test NPM Scanner ===")
    
    npm_project = setup_test_npm_project()
    print(f"[+] Created test project: {npm_project}")
    
    # Use full path for npm on Windows
    npm_path = r"C:\Program Files\nodejs\npm.cmd"
    scanner = NPMScanner(npm_path=npm_path, timeout_seconds=60)
    result = await scanner.scan(str(npm_project), deep_scan=False)
    
    print(f"\nScan results:")
    print(f"  Success: {result.success}")
    print(f"  Vulnerabilities: {len(result.vulnerabilities)}")
    print(f"  CRITICAL: {result.critical_count}, HIGH: {result.high_count}")
    
    if result.vulnerabilities:
        print(f"\nFound vulnerabilities:")
        for vuln in result.vulnerabilities[:3]:  # Show first 3
            print(f"  - {vuln.package} {vuln.current_version} -> {vuln.fix_version}")
            print(f"    Severity: {vuln.severity.value}")
            print(f"    Issue: {vuln.description[:60]}...")
    
    return result


async def test_pip_scanner():
    """Test pip scanner"""
    print("\n=== Test Pip Scanner ===")
    
    pip_project = setup_test_pip_project()
    print(f"[+] Created test project: {pip_project}")
    
    scanner = PipScanner(pip_audit_path="python", timeout_seconds=60)
    result = await scanner.scan(str(pip_project), deep_scan=False)
    
    print(f"\nScan results:")
    print(f"  Success: {result.success}")
    print(f"  Vulnerabilities: {len(result.vulnerabilities)}")
    print(f"  CRITICAL: {result.critical_count}, HIGH: {result.high_count}")
    
    if result.vulnerabilities:
        print(f"\nFound vulnerabilities:")
        for vuln in result.vulnerabilities[:3]:  # Show first 3
            print(f"  - {vuln.package} {vuln.current_version} -> {vuln.fix_version}")
            print(f"    Severity: {vuln.severity.value}")
            print(f"    Issue: {vuln.description[:60]}...")
    
    return result


async def test_orchestrator():
    """Test SCA orchestrator"""
    print("\n=== Test SCA Orchestrator ===")
    
    npm_project = setup_test_npm_project()
    pip_project = setup_test_pip_project()
    
    orchestrator = SCAOrchestrator()
    
    # Scan npm project
    print("\nScanning npm project...")
    npm_summary = await orchestrator.scan_pr(
        task_id="test-001",
        repo_path=str(npm_project),
        pr_number=1
    )
    print(f"  npm vulnerabilities: {npm_summary.npm_vulnerabilities}")
    print(f"  decision: {npm_summary.decision.value}")
    
    # Scan pip project
    print("\nScanning pip project...")
    pip_summary = await orchestrator.scan_pr(
        task_id="test-002",
        repo_path=str(pip_project),
        pr_number=2
    )
    print(f"  pip vulnerabilities: {pip_summary.pip_vulnerabilities}")
    print(f"  decision: {pip_summary.decision.value}")


async def main():
    """Run all integration tests"""
    print("=" * 60)
    print("SCA Integration Test - Real Scan Verification")
    print("=" * 60)
    
    try:
        # Test npm scanner
        npm_result = await test_npm_scanner()
        
        # Test pip scanner
        pip_result = await test_pip_scanner()
        
        # Test orchestrator
        await test_orchestrator()
        
        print("\n" + "=" * 60)
        print("[OK] All integration tests completed")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

