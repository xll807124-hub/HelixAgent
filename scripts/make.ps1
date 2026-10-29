# scripts/make.ps1 — Windows 下的 Make 等价物
# 用法：powershell -ExecutionPolicy Bypass -File scripts\make.ps1 <target>
# 与 Makefile 同步：每次新增 Make target 必须同步本文件。

param(
    [Parameter(Mandatory=$true, Position=0)]
    [ValidateSet('setup','install','lint','format','typecheck','test','test-fast','test-unit','test-integration','coverage','check','security','security-setup','pre-commit','clean','help')]
    [string]$Target,
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py   = '.\.venv\Scripts\python.exe'

function Invoke-ProjectPython {
    & $py @args
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

switch ($Target) {
    'setup' {
        if (-not (Test-Path $py)) {
            & $Python -m venv .venv
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
        Invoke-ProjectPython -m pip install --upgrade pip
        Invoke-ProjectPython -m pip install -e '.[dev]'
        Write-Host "✅ setup 完成" -ForegroundColor Green
    }
    'install' {
        Invoke-ProjectPython -m pip install -e '.[dev]'
    }
    'lint'        { Invoke-ProjectPython -m ruff check . }
    'security-setup' { Invoke-ProjectPython scripts/install_security_tools.py }
    'security'    { Invoke-ProjectPython scripts/security_gate.py }
    'format'      { Invoke-ProjectPython -m ruff format src tests }
    'typecheck'   { Invoke-ProjectPython -m mypy src }
    'test'        { Invoke-ProjectPython -m pytest --cov=src --cov-report=term-missing }
    'test-fast'   { Invoke-ProjectPython -m pytest -q }
    'test-unit'   { Invoke-ProjectPython -m pytest -q -m unit }
    'test-integration' { Invoke-ProjectPython -m pytest -q -m integration }
    'coverage'    { Invoke-ProjectPython -m pytest --cov=src --cov-report=term-missing }
    'check' {
        Invoke-ProjectPython -m ruff check .
        Invoke-ProjectPython -m mypy src
        Invoke-ProjectPython -m pytest -q
    }
    'pre-commit' {
        Invoke-ProjectPython -m pip install pre-commit
        Invoke-ProjectPython -m pre_commit install
        Invoke-ProjectPython -m pre_commit run --all-files
    }
    'clean' {
        Get-ChildItem -Path . -Force -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
        Remove-Item -Recurse -Force .pytest_cache, .mypy_cache, .ruff_cache, htmlcov -ErrorAction SilentlyContinue
        Write-Host "✅ 缓存清理完成" -ForegroundColor Green
    }
    'help' {
        Write-Host "目标：setup | install | lint | format | typecheck | test | test-fast | test-unit | test-integration | coverage | check | security-setup | security | pre-commit | clean"
    }
}
