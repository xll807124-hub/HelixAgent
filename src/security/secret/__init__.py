"""
Secret Scanner - 检测代码中的硬编码密钥和敏感数据

设计:
  - Input: 文件路径和扫描模式
  - Output: 检测匹配 + 置信度 + 上下文
  - Integration: PolicyGateway 前置检查
"""
