"""
RT-007 Idempotency Key 与副作用边界 — 请求摘要计算

本模块实现请求参数的规范化和摘要计算（REQ-RT-007 §4.1）

设计原则：
- 规范化请求参数（排序、去空值、敏感字段脱敏）
- 计算请求摘要（SHA256）
- 相同逻辑请求产生相同摘要
- 参数顺序不影响摘要（字典排序）
"""

import hashlib
import json
from typing import Any


class RequestDigestCalculator:
    """请求摘要计算器（REQ-RT-007 §4.1）
    
    负责将请求参数规范化为确定性的摘要哈希，用于幂等冲突检测。
    
    规范化规则：
    1. 字典键按字母顺序排序
    2. 移除值为 None 的键
    3. 敏感字段脱敏（不影响摘要，但不记录明文）
    4. 递归处理嵌套字典和列表
    5. 序列化为 JSON 后计算 SHA256
    
    Example:
        calculator = RequestDigestCalculator()
        digest = calculator.calculate({"file": "test.py", "content": "print('hello')"})
        # digest: "sha256:abc123..."
    """
    
    # 敏感字段列表（这些字段的值在日志/审计中会被脱敏，但仍参与摘要计算）
    SENSITIVE_FIELDS = {
        "password",
        "token",
        "secret",
        "api_key",
        "private_key",
        "credential",
        "authorization",
    }
    
    def calculate(self, request: dict[str, Any]) -> str:
        """计算请求摘要
        
        Args:
            request: 请求参数字典
        
        Returns:
            摘要字符串，格式为 "sha256:{hex_digest}"
        """
        # 规范化参数
        normalized = self._normalize(request)
        
        # 序列化为 JSON（确保键排序）
        json_str = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
        
        # 计算 SHA256 哈希
        hash_obj = hashlib.sha256(json_str.encode("utf-8"))
        hex_digest = hash_obj.hexdigest()
        
        return f"sha256:{hex_digest}"
    
    def _normalize(self, value: Any) -> Any:
        """递归规范化值
        
        规范化规则：
        - None 值移除（在父级字典中处理）
        - 字典：递归规范化值，移除 None 值，按键排序
        - 列表：递归规范化每个元素
        - 其他类型：保持原样
        """
        if value is None:
            return None
        
        if isinstance(value, dict):
            # 递归规范化字典，移除 None 值，排序
            normalized = {}
            for k, v in sorted(value.items()):
                normalized_v = self._normalize(v)
                if normalized_v is not None:  # 移除 None 值
                    normalized[k] = normalized_v
            return normalized
        
        if isinstance(value, list):
            # 递归规范化列表
            return [self._normalize(item) for item in value]
        
        # 其他类型（str, int, bool, float）保持原样
        return value
    
    def is_sensitive_field(self, field_name: str) -> bool:
        """判断字段是否敏感（用于日志脱敏）
        
        注意：敏感字段仍然参与摘要计算，只是在日志/审计中会被脱敏。
        """
        return field_name.lower() in self.SENSITIVE_FIELDS
