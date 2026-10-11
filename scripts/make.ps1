# scripts/make.ps1 — Windows 下的 Make 等价物
# 用法：powershell -ExecutionPolicy Bypass -File scripts\make.ps1 <target>
# 与 Makefile 同步：每次新增 Make target 必须同步本文件。

param(
    [Parameter(Mandatory=$true, Position=0)]
    [ValidateSet('setup','install','lint','format','typecheck','test','test-fast','test-unit','test-integration','coverage','check','pre-commit','clean','help')]
    [string]$Target
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py   = '.\.venv\Scripts\python.exe'
$pip  = '.\.venv\Scripts\pip.exe'

function Run($cmd) { & cmd /c $cmd }

switch ($Target) {
    'setup' {
        if (-not (Test-Path .venv)) { python -m venv .venv }
        & $pip install --upgrade pip
        & $pip install -r requirements-dev.txt
        Write-Host "✅ setup 完成" -ForegroundColor Green
    }
    'install' {
        & $pip install -r requirements.txt
        & $pip install -r requirements-dev.txt
    }
    'lint'        { & $py -m ruff check src tests }
    'format'      { & $py -m ruff format src tests }
    'typecheck'   { & $py -m mypy src }
    'test'        { & $py -m pytest --cov=src --cov-report=term-missing }
    'test-fast'   { & $py -m pytest -q }
    'test-unit'   { & $py -m pytest -q -m unit }
    'test-integration' { & $py -m pytest -q -m integration }
    'coverage'    { & $py -m pytest --cov=src --cov-report=term-missing }
    'check'       { & $py -m ruff check src tests; & $py -m mypy src; & $py -m pytest -q }
    'pre-commit' {
        & $py -m pip install pre-commit
        pre-commit install
        pre-commit run --all-files
    }
    'clean' {
        Get-ChildItem -Path . -Force -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
        Remove-Item -Recurse -Force .pytest_cache, .mypy_cache, .ruff_cache, htmlcov -ErrorAction SilentlyContinue
        Write-Host "✅ 缓存清理完成" -ForegroundColor Green
    }
    'help' {
        Write-Host "目标：setup | install | lint | format | typecheck | test | test-fast | test-unit | test-integration | coverage | check | pre-commit | clean"
    }
}
