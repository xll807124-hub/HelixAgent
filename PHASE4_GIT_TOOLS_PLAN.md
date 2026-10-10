# Git 工具模块实现计划

**模块**: 阶段 1.4 - 基础工具集 - Git 工具  
**预计周期**: 1-2 周  
**优先级**: 继续推进（接续文件工具）

## 工具清单与实现顺序

### 第 1 阶段：基础操作（第 1 周）

1. **git-clone** (优先级 P0)
   - 实现: 克隆 GitHub 仓库
   - 依赖: 凭据代理 (OAuth token)
   - 测试: 正常克隆、无效仓库、网络超时
   - 估期: 2-3 天

2. **git-status** (优先级 P0)
   - 实现: 获取仓库状态
   - 依赖: 本地 git 命令
   - 测试: 修改检测、分支识别
   - 估期: 1 天

3. **git-branch** (优先级 P1)
   - 实现: 分支管理 (create/switch/delete)
   - 依赖: git 命令 + GitHub API
   - 测试: 创建、切换、删除、冲突处理
   - 估期: 2 天

### 第 2 阶段：提交与 PR（第 2 周）

4. **git-commit** (优先级 P0)
   - 实现: 提交变更
   - 依赖: 签名配置 (来自 identity harness)
   - 测试: 单文件、多文件、大 commit
   - 估期: 2 天

5. **git-diff** (优先级 P1)
   - 实现: 显示差异
   - 依赖: git 命令
   - 测试: 小改动、大改动、二进制检测
   - 估期: 1-2 天

6. **git-pr** (优先级 P0)
   - 实现: 创建 Pull Request
   - 依赖: GitHub API + 凭据代理
   - 测试: 基本 PR、带描述、冲突检测
   - 估期: 2-3 天

## 代码结构

```
src/tools/git/
├── clone.py          (150-200 行)
├── branch.py         (200-250 行)
├── commit.py         (180-220 行)
├── pr.py             (250-300 行)
├── diff.py           (150-180 行)
├── status.py         (120-150 行)
├── errors.py         (100 行)
└── __init__.py       (导出)

tests/unit/tools/git/
├── test_clone.py     (40+ 用例)
├── test_branch.py    (35+ 用例)
├── test_commit.py    (30+ 用例)
├── test_pr.py        (40+ 用例)
├── test_diff.py      (25+ 用例)
└── test_status.py    (20+ 用例)
```

## 测试目标

- 总计: 190+ 测试用例
- 覆盖率: > 90%
- 通过率: 100%

## 关键依赖

- 凭据代理 (REQ-SEC-005): ✅ 已完成 (Phase 3)
- Policy Gateway (REQ-SEC-003): ✅ 已完成
- RBAC (REQ-SEC-002): ✅ 已完成
- Trace Context: ✅ 已完成
- Identity Harness: ✅ 已完成

## 交付物

1. 代码: 6 个 Git 工具模块
2. 测试: 190+ 用例，100% 通过
3. 文档: API 文档、对标分析、测试报告
4. 集成验证: 与 Policy Gateway、凭据代理集成测试

## 风险识别与应对

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| GitHub API 限流 | 中 | 中 | 实现本地缓存 |
| 凭据过期 | 低 | 高 | 集成凭据刷新机制 |
| 网络超时 | 中 | 中 | 配置重试策略 |
| 权限不足 | 低 | 中 | 清晰的错误消息 |

---

**准备就绪，等待启动信号**
