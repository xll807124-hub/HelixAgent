# SEC-007 依赖兼容升级与安全门禁增量交付

测试日期：2026-10-28。**✅ 本切片（生命周期发现/调用及依赖升级、扫描配置）已于 2026-10-29 获用户验收并标记完成；未进入下一功能。** 本报告接续[生命周期功能报告](./sec007-lifecycle-2026-10-28.md)，不改写历史测试证据。

用户已明确批准将依赖兼容升级与扫描工具配置纳入当前任务。设计、工具对比和 CLI 契约见[安全门禁说明](../security-gate.md)，批准记录见[ADR 第 7 节](../review/sec007-lifecycle-discovery-design-2026-10-28.md#7-adr-增量依赖与扫描配置纳入当前切片)。原 MCP 接口见[API 文档](../api/sec-007-mcp-connector-governance-api.md)。

## 交付内容

- 同步 `pyproject.toml`、`requirements.txt`、`requirements-dev.txt`；升级有漏洞的依赖及必需的兼容依赖。现有 Pydantic、httpx 等无关版本保留。
- 新增固定版本扫描入口、Gitleaks 官方发行包校验安装器、规则配置和样例内容指纹复核记录。扫描规则未全局排除，Bandit 忽略 `nosec` 豁免，Gitleaks 忽略行内 allow 注释且禁止 `.gitleaksignore` 绕过。
- Nox、Make、PowerShell 提供统一入口。CI 删除 `continue-on-error`、`|| true` 和“解析错误视为无漏洞”分支；完整拉取 Git 历史、权限收敛为只读，始终上传扫描证据。Python 矩阵与项目要求统一为 3.12/3.13；无 Node 项目时不运行无意义的 npm 命令。
- 新增 53 个门禁测试；没有改动 MCP 生产行为、UI、数据库或运行时共享契约。

| 依赖 | 原版本 | 当前固定版本 | 原因 |
|---|---|---|---|
| aiohttp | 3.11.10 | 3.14.5 | 清除 HTTP 依赖已知漏洞 |
| opentelemetry-api / sdk | 1.27.0 | 1.45.1 | API 修复与 SDK 严格配套 |
| PyJWT | 2.10.1 | 2.15.1 | JWT 校验漏洞修复 |
| python-dotenv | 1.0.1 | 1.2.4 | 配置解析依赖修复 |
| FastAPI | 0.115.6 | 0.135.4 | 支持修复后的 Starlette；避免无关的大范围升级 |
| Starlette | 0.41.3（间接） | 1.3.1（显式锁定） | 修复 ASGI 依赖漏洞，防止重新解析回旧版本 |
| pytest | 8.3.3 | 9.0.3 | 开发依赖漏洞修复 |
| pytest-asyncio | 0.25.2 | 1.4.1 | 兼容 pytest 9 |
| Bandit | 未安装 | 1.9.4 | Python AST SAST，全内置规则 |
| Gitleaks | 未安装 | 8.30.1 | 工作区及历史 Secret 扫描，Windows/Linux x64 安装包校验 |
| pip-audit | 2.9.0 | 2.9.0 | 保持原版本；实际扫描生产、开发及扫描工具依赖 |

## 测试项 → 用例 → 结果 → 修复动作

| 测试项 | 用例 | 结果 | 修复动作 |
|---|---|---|---|
| 依赖兼容/冒烟 | `pip check`；FastAPI 查询/错误包络、JWT 签发校验、Trace、HTTP 执行链路 | 通过；升级后的全量用例无退化 | 配套升级 FastAPI、Starlette、OpenTelemetry SDK 和异步测试插件 |
| SCA 实扫 | 实际安装环境 92 个分发条目；仅本项目 editable 元数据跳过 | **0 已知漏洞**；91 个第三方分发被检查 | 原 6 包 68 条漏洞记录经升级清零，无漏洞豁免 |
| SAST 实扫 | 199 个产品源码/构建脚本文件，全部内置规则 | **高危 0、中危 0、低危 44**；无解析错误 | 固定规则版本；安装器采用现有 requests HTTPS 客户端；低危提示保留原始报告，不伪称所有提示清零 |
| Secret 工作区 | Git 管理文件及未忽略的新文件，含未提交变更 | 原始命中 20；已复核样例 20；未解释命中 0 | 逐项核验文件、规则及源内容 SHA-256，保留原始脱敏报告 |
| Secret Git 历史 | 本仓库全部本地 Git refs 历史，拒绝浅克隆 | 原始命中 19；已复核样例 19；未解释命中 0 | 不重写历史；使用同一内容复核机制；非当前目录/历史的其他仓库不在扫描范围 |
| 检测能力正向控制 | 真实 Bandit 扫描危险 Shell 调用；真实 Gitleaks 扫描运行时生成的模拟令牌 | 两者均退出 1；SAST 高危命中 1，Secret 命中 1 且报告/控制台完全脱敏 | 证明零阻塞结果来自当前内容与复核，而非扫描器失效 |
| 边界 | SAST 中危 4/5、高危 1、低危 100；SCA 任一 advisory；不可解释 Secret | 按阈值通过或阻塞 | SCA 采用任何已知漏洞均阻塞的保守策略，不把 advisory ID 当作严重度 |
| 异常/降级 | 缺工具、版本不符、空/损坏报告、解析错误、返回码不一致、浅历史、非法复核配置 | 全部拒绝通过；退出 2 | 删除旧 CI 吞错逻辑，运行前删除旧报告，异常不能复用历史绿色结果 |
| 弱网/重试 | 真实子进程超时；真实 pip-audit 经不可用代理访问空缓存漏洞库 | 超时被终止；断网时扫描退出 1、未生成报告，门禁拒绝 | 有界执行；没有离线放行或无限重试降级 |
| 样例防误豁免 | 原样例替换为新内容、移到其他文件 | 新命中阻塞 | 指纹绑定文件、规则和完整命中源行；不按整个 tests/docs 目录忽略 |
| 安装安全 | 官方包实装；错误 SHA-256；带 `../` 成员的归档；Linux 提取分支 | 全部通过 | 校验后只读取指定二进制成员，不执行归档路径解压；失败不覆盖安装 |
| 门禁专项 | 新增测试文件 | **53 通过、0 失败** | 修复最初的一处测试函数签名超长行后静态复测通过 |
| 全量回归 | 全仓 pytest，包含先前 46 个生命周期专项用例 | **2100 通过、0 失败、3 跳过**；53.43s，2126 条弃用等警告 | 无兼容性失败；原 Docker 条件跳过保留，没有将失败改为跳过 |
| 静态检查 | 全仓 Ruff、两个新增脚本显式 Ruff、mypy src | **通过：0 诊断，196 源文件类型检查通过** | 项目 Ruff 原配置排除 scripts，故新增脚本另行显式核验 |
| 覆盖率 | src 单独计数；门禁脚本独立计数；生命周期关键方法 | src 行 **86.04%**、分支 **74.48%**；门禁脚本行 **97.08%**、分支 **93.75%**；安装器行 **95.12%**、分支 **80.00%** | 11 个生命周期关键方法仍为 100% 行覆盖；未外推为所有项目关键模块均已验收 |

44 条 SAST 低危分别为：子进程导入 10、无 shell 参数化子进程调用 6、疑似口令常量 17、非密码随机数 3、类型/状态断言 7、统计目录大小时忽略异常 1。它们按现行门槛不阻塞，原始位置和代码仍在报告中；其中已有模拟实现等项目缺口继续按正文路线图处理。

Secret 复核共 16 个不同内容指纹：确定性脱敏/策略测试数据、[GitHub 官方 API 示例](https://docs.github.com/en/rest/apps/apps#create-an-installation-access-token-for-an-app)及一个字符变化的哈希测试、历史 pip-audit 公告里的空密钥演示 JWT。没有识别出真实业务凭据，未执行远端凭据轮换。任何不同内容的新发现仍阻塞。

## 复现与证据

在仓库根目录执行：

```powershell
.venv/Scripts/python.exe -m pip install -e '.[dev,sandbox]'
.venv/Scripts/python.exe scripts/install_security_tools.py
.venv/Scripts/python.exe -m nox -s security
.venv/Scripts/python.exe -m pytest -q tests/test_security_gate.py tests/test_mcp_lifecycle_discovery.py
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff check scripts/security_gate.py scripts/install_security_tools.py
.venv/Scripts/python.exe -m mypy src
.venv/Scripts/python.exe -m pytest -q --cov=src --cov-branch
```

默认原始扫描产物位于 `.security-reports/`；结构化结果、实际版本、关键方法覆盖率、日志路径与 SHA-256 见[JSON 证据](./sec007-security-gate-2026-10-28.json)。运行 API 沿用[启动指南](../api/README.md)。生产部署应使用这些锁定版本重新安装，仓库中的版本变更不会替换其他机器上已经运行的环境。

本地实测环境为 Windows / Python 3.13.18。CI 配置已更新并检查结构，但没有推送或触发远端 GitHub Actions，不能声称 Linux/Python 3.12 CI 已运行通过。3 个真实 Docker 用例仍需运行中的 daemon；完整 HAR-006、REL-009 和 SEC-007 其他生产缺口仍开放。本轮关闭的是当前切片的 SAST/SCA/Secret 阻塞，不代表全部软件已完成验收。

## 用户验收（2026-10-29）

用户在本次交付后指示“将已完成的任务标记✅”，据此记录当前已交付切片验收。测试摘要：生命周期专项 46、门禁专项 53、全量 2100 通过 / 0 失败 / 3 Docker 跳过；SAST 高中危 0、SCA 0 已知漏洞、Secret 命中已逐项复核为样例。

[结构化验收记录](../delivery-reports/sec007-lifecycle-acceptance-2026-10-29.json)记载完成范围、日期及原始测试 JSON 的 SHA-256。2026-10-28 原始 JSON 中的 `user_acceptance: false` 和 `task_complete: false` 保留为当时快照，最新验收状态以该独立记录为准。本文剩余范围限制继续有效，SEC-007 整体与阶段 0 未勾选完成。本次仅更新文档状态，未重新运行软件测试。
