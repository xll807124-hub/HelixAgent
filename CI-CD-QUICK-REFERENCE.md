# SCA CI/CD 集成 - 快速参考

## 📋 文件清单

```
.github/workflows/sca-security-scan.yml    GitHub Actions 工作流
.gitlab-ci.yml                              GitLab CI 流水线
Jenkinsfile                                 Jenkins Groovy 脚本
security/policies/sca-policy.json          SCA 安全策略
CI-CD-INTEGRATION-GUIDE.md                 详细集成指南
scripts/deploy-sca-ci-cd.sh                自动部署脚本
```

---

## 🚀 快速部署

### GitHub Actions (最简单)

```bash
# 1. 已配置完毕 (.github/workflows/sca-security-scan.yml)
# 2. 推送代码
git push origin main

# 3. 查看 https://github.com/<owner>/<repo>/actions
```

### GitLab CI

```bash
# 1. 已配置完毕 (.gitlab-ci.yml)
# 2. 配置 CI/CD 变量 (Settings → CI/CD → Variables)
# 3. 推送代码
git push origin main
```

### Jenkins

```bash
# 1. 新增 Pipeline 任务
# 2. Pipeline script from SCM
# 3. Repository URL + Jenkinsfile
# 4. 配置构建触发器 (Push, PR, Periodic)
```

---

## 🔍 扫描策略

| 工具 | CRITICAL | HIGH | 操作 |
|-----|---------|------|------|
| npm | 0 | ≥3 | BLOCK / REVIEW |
| pip | 0 | ≥5 | BLOCK / REVIEW |

**位置**: `security/policies/sca-policy.json`

---

## 📊 输出报告

```
npm-audit.json                # NPM 原始输出
pip-audit.json                # pip 原始输出
orchestrator-decision.json    # 最终决策
summary.txt                   # 人类可读摘要
```

---

## ✅ 检查清单

- [ ] 选择 CI 平台 (GitHub Actions / GitLab / Jenkins)
- [ ] 配置环境变量 (可选: Slack 通知)
- [ ] 推送代码并验证首次扫描
- [ ] 配置漏洞阈值 (如需修改)
- [ ] 设置通知 (邮件/Slack)
- [ ] 文档化已批准的例外

---

## 🐛 常见问题

**Q: 我的 PR 被 BLOCK 了，该怎么办？**  
A: 查看详细报告，更新依赖或获得安全批准

**Q: 如何添加例外？**  
A: 编辑 `security/policies/sca-policy.json` 的 `approved_exceptions` 部分

**Q: 如何修改阈值？**  
A: 编辑 `security/policies/sca-policy.json` 的 `vulnerability_thresholds`

**Q: 扫描失败了，怎么调试？**  
A: 查看 CI/CD 工作流日志中的错误消息，或运行本地测试

---

## 📞 支持

完整指南: [`CI-CD-INTEGRATION-GUIDE.md`](CI-CD-INTEGRATION-GUIDE.md)  
SCA 扫描器: [`src/security/scanning/`](src/security/scanning/)  
策略配置: [`security/policies/sca-policy.json`](security/policies/sca-policy.json)

---

## 📈 监控指标

| 指标 | 目标 |
|-----|------|
| 平均扫描时间 | < 5 分钟 |
| npm 覆盖率 | 100% |
| pip 覆盖率 | 100% |
| 误报率 | < 5% |

---

**状态**: ✅ 生产就绪 | **更新**: 2026-10-12
