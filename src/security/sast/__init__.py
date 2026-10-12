"""
SAST (Static Application Security Testing) Scanner
对标 CWE 识别常见安全缺陷

设计:
  - Input: 代码路径和扫描规则
  - Output: 安全问题列表 + 严重程度 + 修复建议
  - Integration: PolicyGateway 前置检查
"""
