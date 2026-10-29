# SEC-007 安全门禁：执行契约与范围扩展

日期：2026-10-28。用户已明确将依赖兼容升级与扫描工具配置纳入当前任务；本页补充既有生命周期方案，不开启下一功能。✅ 已于 2026-10-29 获用户验收完成；2026-10-28 实测为全量 2100 通过 / 3 Docker 跳过、SAST/SCA/Secret 通过，见[验收记录](./delivery-reports/sec007-lifecycle-acceptance-2026-10-29.json)。

## 设计与工具对比

- [Bandit](https://bandit.readthedocs.io/en/latest/) 对 Python AST 运行安全插件，并提供原生严重度和置信度。当前产品只有 Python 后端，选择固定版本 1.9.4 的全部内置规则检查 `src`、`scripts` 和 `noxfile.py`；测试夹具不作为产品 SAST 目标，但仍参加 Secret 扫描。没有全局跳过规则。
- [Semgrep CE](https://semgrep.dev/products/community-edition/) 支持 Windows 和多语言规则；本次核验的 1.182.1 强制依赖 OpenTelemetry 1.37.x，与本项目修复后的 1.45.1 冲突，故本次采用 Bandit。后续出现前端时再补对应语言规则，不把 Python 扫描外推为多语言覆盖。
- [Gitleaks](https://github.com/gitleaks/gitleaks) 提供目录和 Git 历史扫描、脱敏报告及默认规则。固定 8.30.1，校验官方发行包 SHA-256；覆盖 Git 管理文件及未忽略的新文件（含未提交变更）和全部可用 Git 历史。报告必须脱敏，真实凭据不能用忽略规则消除。
- [pip-audit](https://github.com/pypa/pip-audit) 检查实际安装的依赖。保留固定 2.9.0，扫描生产、开发和扫描工具依赖；只允许跳过本项目 editable 元数据，项目依赖必须仍被扫描。本轮采取所有已知漏洞均阻塞的保守策略，不依赖缺失的严重度字段。

## CLI / 结果契约（实现前确定）

`python scripts/security_gate.py --output-dir <目录>` 运行三个扫描类别并写 JSON 报告及 `summary.json`；默认输出到被 Git 忽略的 `.security-reports`。`python scripts/install_security_tools.py` 安装校验后的 Gitleaks 到 `.tools`；Python 工具随开发依赖安装。

- 退出码 0：扫描成功、结果有效且满足所有阈值。
- 退出码 1：存在阻塞发现。
- 退出码 2：工具缺失、版本错误、超时、报告缺失/解析错误、扫描不完整或其他执行异常。
- SAST 高危 ≥1 或中危 ≥5 阻塞；任何未解释的 SCA/Secret 命中阻塞。工具异常优先于发现状态，不能算作通过。
- 不向外上传源代码；pip-audit 需要网络查询公开漏洞库，断网时拒绝通过。Gitleaks 报告及控制台使用完整脱敏。
- 有意行为的静态误报只能逐条以文件、规则、代码指纹和原因核验，仍保留原始报告；不使用通配目录忽略真实代码问题。

## 实施及验证顺序

1. 保存当前依赖与工作区证据；同步生产/开发清单，修复 aiohttp、OpenTelemetry、PyJWT、dotenv、Starlette、pytest，并配套升级 FastAPI/异步测试插件。
2. 安装真实扫描器、检查原始发现，修复实际问题或记录有证据的逐条误报。
3. 增加统一入口和 CI，工具失败、非零扫描和缺失报告均不可被吞掉。
4. 验证干净路径、发现阻塞、损坏报告、缺工具、超时/网络失败、阈值边界；执行全量功能回归、静态检查和覆盖率。
5. 报告证据、启动方法和剩余项目级缺口；本切片已于 2026-10-29 验收；SEC-007 其余功能保持待完成。

本次不新增 HTTP API、UI、数据库迁移或敏感配置，沿用原有 MCP 接口文档。依赖升级不会授权改变冻结的 Runtime 契约。

## 复核与实际交付

门禁实际验证及历史前后数据见[增量报告](./test-reports/sec007-security-gate-2026-10-28.md)。`security/secret-fixtures.json` 只记录已核验合成样例的文件、规则、源内容 SHA-256 和证据；扫描器仍输出全部命中。内容、文件或规则变化会重新阻塞。忽略的虚拟环境、缓存、工具二进制及本机 .env 不属于可提交文件扫描范围；不据此宣称扫描了本机所有凭据。Git 子模块自身历史须在相应仓库另行运行，本入口不自动递归扫描外部仓库。
