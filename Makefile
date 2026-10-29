# AI Agent 平台 - Makefile
# 规则（项目开发执行手册 B2.1-5 / B2.2-1 / B2.3-3）：
#   `make setup` < 2 分钟、首次一行启动；`make dev` 启动服务；`make test` 跑测试。
# Windows 环境若无 GNU make，可执行：powershell -ExecutionPolicy Bypass -File scripts/make.ps1 <target>

# —— 通用配置 ——
PY       ?= .venv\Scripts\python.exe
PIP      ?= .venv\Scripts\pip.exe
RUFF     ?= $(PY) -m ruff
MYPY     ?= $(PY) -m mypy
PYTEST   ?= $(PY) -m pytest
COV      ?= --cov=src --cov-report=term-missing
PYTHONSRC ?= src

.PHONY: help setup install dev test test-fast test-unit test-integration lint format typecheck coverage clean check security security-setup pre-commit

help:
	@echo.  目标：
	@echo.    make setup         一行启动开发环境（venv + 依赖）
	@echo.    make install       安装/同步生产 + 开发依赖
	@echo.    make lint          ruff check
	@echo.    make format        ruff format
	@echo.    make typecheck     mypy src
	@echo.    make test          pytest（含覆盖率）
	@echo.    make test-fast     pytest（仅 unit，-q）
	@echo.    make coverage      pytest + 覆盖率
	@echo.    make check         lint + typecheck + test-fast
	@echo.    make clean         清理缓存

setup:
	@if not exist .venv (python -m venv .venv)
	$(PIP) install --upgrade pip
	$(PY) -m pip install -e ".[dev]"
	@echo.✅ setup 完成

install:
	$(PY) -m pip install -e ".[dev]"

security-setup:
	$(PY) scripts/install_security_tools.py

security:
	$(PY) scripts/security_gate.py

lint:
	$(RUFF) check .

format:
	$(RUFF) format $(PYTHONSRC) tests

typecheck:
	$(MYPY) $(PYTHONSRC)

test:
	$(PYTEST) $(COV)

test-fast:
	$(PYTEST) -q

test-unit:
	$(PYTEST) -q -m unit

test-integration:
	$(PYTEST) -q -m integration

coverage:
	$(PYTEST) $(COV)

check: lint typecheck test-fast
	@echo.✅ check 全绿

pre-commit:
	$(PY) -m pip install pre-commit
	pre-commit install
	pre-commit run --all-files

clean:
	@if exist .pytest_cache rmdir /s /q .pytest_cache
	@if exist .mypy_cache rmdir /s /q .mypy_cache
	@if exist .ruff_cache rmdir /s /q .ruff_cache
	@if exist htmlcov rmdir /s /q htmlcov
	@for /d /r src %%d in (__pycache__) do @if exist %%d rmdir /s /q %%d
	@for /d /r tests %%d in (__pycache__) do @if exist %%d rmdir /s /q %%d
