# infra/ — 基础设施配置

按职责拆分为四个子目录：

| 子目录 | 职责 | 启用阶段 | 状态 |
|--------|------|---------|------|
| `docker/` | 镜像构建（运行时 / 沙箱 / 前端控制台） | 阶段 2 起 | 骨架占位 |
| `kubernetes/` | 部署清单（HPA/NetworkPolicy/PodDisruptionBudget） | 阶段 4 起 | 骨架占位 |
| `terraform/` | 云资源 IaC（DB/Redis/KMS/Secrets） | 阶段 4 起 | 骨架占位 |
| `scripts/` | 运维脚本（DB 初始化 / 回滚 / 健康检查） | 阶段 1 起 | 骨架占位 |

> ⚠️ 当前阶段（Walking Skeleton / 阶段 1.x）以本地 `.venv` 跑测试为主，
> 上述子目录均为骨架占位，**禁止在未走 §7 供应链评审**前把任何外部镜像/Provider
> 默认加入 CI；后续切片启用时按对应 REQ（REQ-SEC-004 沙箱、REQ-SEC-005 凭据等）
> 引入并完成评估。
