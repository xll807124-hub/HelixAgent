# SCA 集成指南 - CI/CD 流水线集成

## 快速开始

### 1️⃣ GitHub Actions (推荐)

**前置条件**:
- GitHub 仓库已创建
- 仓库 Settings → Security → Secret and variables 已配置

**部署步骤**:

```bash
# 1. 工作流已自动配置在:
# .github/workflows/sca-security-scan.yml

# 2. 在 GitHub 中配置环保变量 (可选)
# - SLACK_WEBHOOK_URL: Slack 通知 URL
# - SECURITY_EMAIL: 安全团队邮箱

# 3. 触发条件:
# - 推送到 main/develop 分支
# - 创建 PR 到 main/develop
# - 定时任务: 每天 09:00 UTC

# 验证工作流
git push origin main
# 在 GitHub Actions 选项卡查看运行状态
```

**特性**:
- ✅ 多版本 Python 测试 (3.11, 3.12, 3.13)
- ✅ NPM 和 pip-audit 并行扫描
- ✅ PR 自动注释漏洞摘要
- ✅ 工件自动存档 (30 天)
- ✅ CRITICAL 漏洞自动阻止

---

### 2️⃣ GitLab CI

**前置条件**:
- GitLab 项目已创建
- GitLab Runner 已配置 (Docker 镜像)

**部署步骤**:

```bash
# 1. 流水线配置已创建在:
# .gitlab-ci.yml

# 2. 配置 CI/CD 变量 (Settings → CI/CD → Variables):
# - SLACK_WEBHOOK_URL
# - SECURITY_EMAIL

# 3. 提交并推送
git add .gitlab-ci.yml
git commit -m "ci: Add GitLab CI/CD pipeline for SCA scanning"
git push origin feature/ci-cd

# 在 CI/CD → Pipelines 查看运行状态
```

**阶段**:
```
build → scan (npm + pip 并行) → report (汇总)
```

**特性**:
- ✅ Dependency scanning report 格式支持
- ✅ MR 自动注释
- ✅ 工件存档
- ✅ 缓存加速

---

### 3️⃣ Jenkins

**前置条件**:
- Jenkins 服务器已部署
- Git 插件已安装
- Pipeline 插件已启用
- Email Extension 插件已安装 (可选)

**部署步骤**:

```bash
# 1. Jenkinsfile 已创建在项目根目录

# 2. 在 Jenkins UI 创建新的 Pipeline 任务:
#    - 名称: ai-agent-sca-scan
#    - 类型: Pipeline
#    - Pipeline script from SCM
#    - Repository URL: <your-repo>
#    - Script Path: Jenkinsfile

# 3. 配置构建触发器:
#    - Push Events
#    - Pull Requests
#    - Periodic builds (H 9 * * 0 - 每周日 9:00)

# 4. 配置邮件通知 (可选):
#    - Manage Jenkins → Configure System → Email notification
#    - Configure default email address
```

**构建阶段**:
```
Prepare → Install Dependencies → SCA Scanning (并行) → 
Orchestration → Generate Report → Archive Results
```

**特性**:
- ✅ 30 分钟超时控制
- ✅ 构建历史保留 (30 个)
- ✅ 并行执行 npm + pip
- ✅ 邮件通知
- ✅ 工件存档

---

## 环境变量配置

### GitHub Actions

在 `.github/workflows/sca-security-scan.yml` 中添加:

```yaml
env:
  # 可选: Slack 通知
  SLACK_WEBHOOK: ${{ secrets.SLACK_WEBHOOK_URL }}
  # 可选: 安全团队邮箱
  SECURITY_EMAIL: ${{ secrets.SECURITY_EMAIL }}
```

### GitLab CI

在 GitLab 项目设置中配置:

```
Settings → CI/CD → Variables (Protected)
- SLACK_WEBHOOK_URL: https://hooks.slack.com/...
- SECURITY_EMAIL: security@example.com
```

### Jenkins

在 Jenkins 管理界面:

```
Manage Jenkins → Configure System → Global properties
□ Environment variables
- SLACK_WEBHOOK_URL: https://hooks.slack.com/...
- SECURITY_EMAIL: security@example.com
```

---

## 策略配置

SCA 策略定义在 `security/policies/sca-policy.json`:

```json
{
  "vulnerability_thresholds": {
    "npm": {
      "critical": { "threshold": 0, "action": "block" },
      "high": { "threshold": 3, "action": "review" }
    },
    "pip": {
      "critical": { "threshold": 0, "action": "block" },
      "high": { "threshold": 5, "action": "review" }
    }
  }
}
```

**修改策略**:

1. 编辑 `security/policies/sca-policy.json`
2. 更新阈值或操作
3. 提交并推送
4. 新策略在下一次扫描时生效

---

## 输出和报告

### 扫描结果

每次扫描生成以下报告:

```
security-reports/
├── npm-audit.json              # NPM 审计原始输出
├── npm-audit-formatted.json    # 格式化后的 NPM 结果
├── pip-audit.json              # pip-audit 原始输出
├── pip-audit.md                # Markdown 格式的 pip 结果
├── orchestrator-decision.json  # SCA 编排器决策
└── summary.txt                 # 人类可读的摘要
```

### PR 注释示例

```
## 🔐 SCA Security Scan Results

### NPM Audit
- Total vulnerabilities: 3
- Critical: 0
- High: 2

### pip-audit
- Vulnerable packages: 5

### Decision
✅ ALLOW (无 CRITICAL 漏洞)
```

---

## 故障排除

### 问题 1: "npm not found"

**原因**: Node.js 未安装

**解决**:
- GitHub Actions: 自动处理 (actions/setup-node@v4)
- GitLab CI: 使用 `node:20-alpine` 镜像
- Jenkins: 在服务器上安装 Node.js

### 问题 2: "pip-audit: command not found"

**原因**: pip-audit 未安装

**解决**:
```bash
python -m pip install pip-audit
# 或者在 CI 配置中添加
python -m pip install --upgrade pip-audit
```

### 问题 3: "Requirements not found"

**原因**: `requirements.txt` 不存在

**解决**: 
- 创建 `requirements.txt` 或指定其他方式安装依赖
- 在 CI 配置中标记为 `continue-on-error: true`

### 问题 4: PR 未被阻止 (预期被阻止)

**原因**: 漏洞数未超过阈值

**调试**:
```bash
# 查看原始 JSON 报告
cat npm-audit-report.json | python -m json.tool
cat pip-audit-report.json | python -m json.tool

# 检查编排器决策
cat sca-orchestrator-results.json
```

---

## 监控和维护

### 定期检查

| 频率 | 任务 |
|-----|------|
| 每周 | 检查 SCA 报告趋势 |
| 每月 | 更新漏洞阈值 |
| 每季度 | 审查已批准的例外 |
| 每年 | 更新策略文档 |

### 性能优化

```yaml
# 启用缓存加速 (减少 50% 执行时间)
cache:
  npm: true
  pip: true
  ttl: 24h
```

### 成本优化

- GitHub Actions: 免费配额 2000 分钟/月 (公开仓库无限制)
- GitLab CI: 根据 Runner 配置
- Jenkins: 自托管 (无额外成本)

---

## 集成实例

### 与 PR 审查工作流集成

```
PR Created
  ↓
SCA Scan Started
  ↓
  ├─ NPM Audit
  ├─ pip-audit
  └─ Orchestrator Decision
  ↓
Decision == BLOCK?
  ├─ YES → PR 标记为需要修复 (PR 自动注释)
  └─ NO → 继续审查
  ↓
PR Merged
  ↓
Deploy to Staging
```

### 与发布流程集成

```
Release Tag Created (v1.2.3)
  ↓
SCA Scan Run
  ↓
Decision == ALLOW?
  ├─ YES → 发布到 NPM/PyPI
  └─ NO → 发布失败 (需要修复)
```

---

## 最佳实践

✅ **推荐**:
- [ ] 在所有 PR 上运行 SCA 扫描
- [ ] 将 CRITICAL 漏洞设置为阻止条件
- [ ] 每周检查漏洞报告
- [ ] 维护已批准的例外清单
- [ ] 启用 Slack/Email 通知
- [ ] 定期更新扫描工具版本

❌ **避免**:
- 禁用关键漏洞检查
- 忽视高危漏洞警告
- 过度批准例外
- 不更新依赖版本
- 缺乏文件记录

---

## 支持

遇到问题？

1. 查看本指南的故障排除部分
2. 检查工作流/流水线的构建日志
3. 查看生成的 SCA 报告
4. 联系安全团队

---

**最后更新**: 2026-10-12  
**维护者**: Security Team
