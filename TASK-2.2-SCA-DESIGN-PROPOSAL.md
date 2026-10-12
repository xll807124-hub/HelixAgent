# 📋 Task 2.2: SCA (Software Composition Analysis) 集成 - 设计方案

**完成时间**: 2026-10-12 21:35 PM UTC+8  
**状态**: 🔄 设计方案待确认  
**预计耗时**: 2-3 天

---

## 1️⃣ 需求分析

### 要解决的问题

1. **第三方依赖的已知漏洞无法发现** → 引入脆弱性到应用
2. **过时的依赖版本安全风险高** → 攻击面暴露
3. **依赖链中的漏洞难以追踪** → 间接漏洞未被发现
4. **没有统一的依赖审计** → 无法做出知情决策

### 边界（MVP 范围）

✅ **包含**：
- Python 依赖审计 (pip-audit, 检查 PyPI)
- JavaScript 依赖审计 (npm audit, 检查 npm registry)
- PR 时快速扫描 (新增和更改的依赖)
- 晚间定期深度扫描 (全部依赖链)
- 与 SAST/Secret 一致的拦截规则 (所有漏洞都拦截)
- 审计日志集成 (REQ-OBS-007)

❌ **不包含**：
- Go/Rust 等其他语言 (V2+ 功能)
- 自动升级建议 (需要人工审核)
- 许可证扫描 (SCA 扫描的一部分,但优先级较低)
- 代码 clone 检测 (超出范围)

---

## 2️⃣ 对标分析

### 竞品实现方式对比

| 维度 | GitHub Dependabot | npm audit | pip-audit | 本项目方案 |
|------|-------------------|-----------|-----------|-----------|
| **工具** | 自研 + 多工具 | npm 官方 | PyPA 官方 | pip-audit + npm audit |
| **语言支持** | 15+ 种 | JavaScript/TS | Python | Python + JavaScript |
| **更新时机** | Pull Request + 定期 | PR 时 | 按需 | PR + 晚间定期 |
| **漏洞源** | NVD + 社区 | npm Registry | PyPI + NVD | 官方数据源 |
| **处理策略** | 自动PR + 审批 | 拒绝 | 警告 | 自动拒绝 |
| **用户体验** | 高 (自动化) | 中 (CLI 驱动) | 低 (本地) | 中高 (集成) |

### 最佳实践

**GitHub Dependabot 优点**:
- ✅ 自动生成修复 PR (开发者友好)
- ✅ 支持多语言和生态 (覆盖广)
- ✅ 漏洞分类准确 (NVD + 社区评估)
- ✅ 与 GitHub 原生集成 (无缝体验)

**本项目应借鉴**:
1. ✅ 自动拦截所有漏洞 (严格模式)
2. ✅ 并行扫描多种依赖文件 (快速)
3. ✅ 清晰的漏洞详情 (文件/版本/修复)
4. ✅ 与安全系统集成 (Policy Gateway + Kill Switch)

**本项目应规避**:
1. ❌ 不自动生成修复 PR (需人工审核依赖版本)
2. ❌ 不支持过多语言 (复杂性高,先聚焦)
3. ❌ 不做复杂的版本冲突解析 (交给开发者)

---

## 3️⃣ 设计方案

### 核心架构

```
┌─────────────────────────────────────┐
│    依赖文件变化 (PR 创建)             │
│  package.json, requirements.txt       │
└────────────────┬────────────────────┘
                 │
                 ↓
        ┌────────────────────┐
        │  SCAOrchestrator   │
        │   (异步编排)        │
        └─────────┬──────────┘
                  │
        ┌─────────┴──────────┬──────────┐
        │                    │          │
        ↓                    ↓          ↓
   ┌─────────┐         ┌────────┐   ┌──────┐
   │npm audit│         │pip-audit  │Rules │
   │ Scan    │         │ Scan   │   │Cache │
   └────┬────┘         └───┬────┘   └──────┘
        │                  │
        └──────────┬───────┘
                   │
                   ↓
        ┌────────────────────┐
        │   Results Processor│
        │   (结果聚合)        │
        └─────────┬──────────┘
                  │
        ┌─────────┴─────────┬──────────┐
        │                   │          │
        ↓                   ↓          ↓
   ┌──────────┐      ┌────────────┐  ┌──────────┐
   │PR Comment│      │Audit Logs  │  │ Policy   │
   │生成      │      │(存储结果)   │  │Gateway   │
   └──────────┘      └────────────┘  │检查      │
                                      └──────────┘
                                           │
                                           ↓
                                      [拦截/通过]
```

### 数据模型

```python
# 漏洞严重程度 (与 SAST 统一)
class VulnerabilitySeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

# 单个漏洞信息
@dataclass
class Vulnerability:
    id: str                    # CVE-XXXX-XXXXX
    package: str               # requests, lodash
    current_version: str       # 2.28.0
    vulnerable_range: str      # <2.28.1
    fix_version: str           # 2.28.1
    severity: VulnerabilitySeverity
    description: str           # 漏洞描述
    references: list[str]      # CVE URL 等
    affected_file: str         # package.json, requirements.txt

# 扫描结果
@dataclass
class SCAResult:
    success: bool
    scan_duration_ms: int
    vulnerabilities: list[Vulnerability]
    critical_count: int
    high_count: int
    error_message: Optional[str]
    
    @property
    def should_block(self) -> bool:
        # 所有漏洞都拦截
        return len(self.vulnerabilities) > 0
```

### 关键模块设计

#### **A. NPM Scanner**
```python
class NPMScanner:
    """
    npm 依赖扫描器
    
    功能:
      - 检测 package.json/package-lock.json
      - 运行 npm audit (生成 JSON 报告)
      - 解析漏洞信息
      - 支持快速/深度两种模式
    """
    
    async def scan(
        self,
        repo_path: str,
        deep_scan: bool = False
    ) -> SCAResult:
        """
        扫描 npm 依赖
        
        Args:
            repo_path: 仓库路径
            deep_scan: 是否深度扫描 (包括间接依赖)
        
        Returns:
            SCAResult: 扫描结果
        """
        pass
```

#### **B. Pip Scanner**
```python
class PipScanner:
    """
    Python 依赖扫描器
    
    功能:
      - 检测 requirements.txt/setup.py/pyproject.toml
      - 运行 pip-audit (生成 JSON 报告)
      - 解析漏洞信息
      - 支持快速/深度两种模式
    """
    
    async def scan(
        self,
        repo_path: str,
        deep_scan: bool = False
    ) -> SCAResult:
        """
        扫描 Python 依赖
        
        Args:
            repo_path: 仓库路径
            deep_scan: 是否深度扫描
        
        Returns:
            SCAResult: 扫描结果
        """
        pass
```

#### **C. SCA Orchestrator**
```python
class SCAOrchestrator:
    """
    SCA 编排器
    
    功能:
      - 检测项目类型 (Python/JavaScript/混合)
      - 并行扫描多种依赖
      - 聚合结果
      - 与 Policy Gateway 集成
    """
    
    async def scan_pr(
        self,
        task_id: str,
        repo_path: str,
        pr_number: int
    ) -> SCAResultSummary:
        """扫描 PR (快速模式)"""
        pass
    
    async def full_scan(
        self,
        task_id: str,
        repo_path: str
    ) -> SCAResultSummary:
        """完整扫描 (深度模式)"""
        pass
```

#### **D. Result Processor**
```python
class SCAResultProcessor:
    """
    SCA 结果处理器
    
    功能:
      - 聚合 npm + pip 结果
      - 做出拦截决策
      - 生成 PR Comment
      - 记录审计日志
    """
    
    def process(
        self,
        npm_result: SCAResult,
        pip_result: SCAResult
    ) -> SCAResultSummary:
        """处理结果并做出决策"""
        pass
    
    def generate_pr_comment(
        self,
        summary: SCAResultSummary
    ) -> str:
        """生成 PR Comment"""
        pass
```

### 决策规则 (与 SAST 保持一致)

```python
# 严格模式: 所有漏洞都拦截
class SCADecision(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"

def make_decision(npm_result, pip_result) -> SCADecision:
    """
    决策逻辑:
      - 任何漏洞检测 (CRITICAL/HIGH/MEDIUM/LOW) → BLOCK
      - 扫描失败 → NEUTRAL (不拦截,建议重试)
    """
    if npm_result.vulnerabilities or pip_result.vulnerabilities:
        return SCADecision.BLOCK
    return SCADecision.ALLOW
```

### PR Comment 模板

```markdown
❌ Dependency Scan Failed - Cannot Merge

🚨 **此 PR 包含已知漏洞的依赖**

**npm 依赖 (package.json)**:
- ❌ [CRITICAL] lodash < 4.17.21
  Package: lodash
  Current: 4.17.20
  Fix: 4.17.21+
  Issue: Prototype Pollution in lodash
  [CVE-2021-23337](https://github.com/lodash/lodash/issues/4874)

**Python 依赖 (requirements.txt)**:
- ❌ [HIGH] requests < 2.28.1
  Package: requests
  Current: 2.28.0
  Fix: 2.28.1+
  Issue: DoS via excessive redirects
  [CVE-2023-32681](https://nvd.nist.gov/vuln/detail/CVE-2023-32681)

**修复步骤**:
1. 更新依赖到最新安全版本
2. 本地验证应用功能
3. 重新推送代码

[查看完整报告](link)
```

---

## 4️⃣ 实现计划

### Phase 1 - 核心模块 (1-1.5 天)

- [ ] NPM Scanner (async, JSON 解析, 超时保护)
- [ ] Pip Scanner (async, JSON 解析, 超时保护)
- [ ] SCA Orchestrator (并行执行, 状态管理)
- [ ] Result Processor (聚合 + PR Comment)
- [ ] Policy Integration (与 Policy Gateway 集成)

### Phase 2 - 单元测试 (0.5-1 天)

- [ ] 15-20 个单元测试
- [ ] 覆盖成功/失败/超时等边界情况
- [ ] 集成测试 (与 Orchestrator)

### Phase 3 - 文档与交付 (0.5 天)

- [ ] API 文档
- [ ] 完成报告
- [ ] Git 提交

**总预计**: 2-3 天

---

## ✅ 验收标准

- [ ] npm 和 pip 依赖都能正确扫描
- [ ] 漏洞检测准确率 > 95%
- [ ] PR 扫描在 <20s 内完成 (加上 SAST + Secret = ~50s)
- [ ] 所有漏洞都被阻止 (严格模式)
- [ ] PR Comment 清晰、可执行
- [ ] 审计日志完整 (REQ-OBS-007)
- [ ] 15+ 个单元测试全部通过
- [ ] 无回归 (总体 1,334+ 测试通过)
- [ ] 文档完整 (API + 代码注释)

---

## 📊 预期输出

**代码量**:
- NPM Scanner: ~250 行
- Pip Scanner: ~250 行
- Orchestrator: ~250 行
- Result Processor: ~300 行
- Policy Integration: ~150 行
- 总计: ~1,200 行

**测试**:
- 15-20 个新单元测试
- 总体 1,350+ 通过

**文档**:
- 完成报告
- API 文档
- 集成示例

---

**设计方案已完成**，等待你的确认。

如无异议,我将立即启动开发。

确认？(Y/N)
