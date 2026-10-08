"""
单元测试：src/runtime/idempotency/digest.py

测试覆盖：
- RequestDigestCalculator 请求摘要计算
- 规范化规则（排序、去空值、嵌套处理）
- 确定性（相同输入产生相同摘要）
- 敏感字段判断

验收标准：
- 相同请求产生相同摘要（确定性）
- 参数顺序不影响摘要（字典排序）
- None 值被移除
- 嵌套结构正确处理
"""

import pytest

from src.runtime.idempotency.digest import RequestDigestCalculator


class TestRequestDigestCalculator:
    """冒烟 + 边界：RequestDigestCalculator 请求摘要计算"""

    def test_smoke_calculate_simple_request(self) -> None:
        """冒烟：计算简单请求摘要"""
        calculator = RequestDigestCalculator()
        request = {"file": "test.py", "content": "print('hello')"}
        
        digest = calculator.calculate(request)
        
        assert digest.startswith("sha256:")
        assert len(digest) == 71  # "sha256:" + 64 hex chars

    def test_smoke_same_request_produces_same_digest(self) -> None:
        """冒烟：相同请求产生相同摘要（确定性）"""
        calculator = RequestDigestCalculator()
        request = {"file": "test.py", "content": "print('hello')"}
        
        digest1 = calculator.calculate(request)
        digest2 = calculator.calculate(request)
        
        assert digest1 == digest2

    def test_smoke_different_request_produces_different_digest(self) -> None:
        """冒烟：不同请求产生不同摘要"""
        calculator = RequestDigestCalculator()
        request1 = {"file": "test.py", "content": "print('hello')"}
        request2 = {"file": "test.py", "content": "print('world')"}
        
        digest1 = calculator.calculate(request1)
        digest2 = calculator.calculate(request2)
        
        assert digest1 != digest2

    def test_boundary_parameter_order_does_not_affect_digest(self) -> None:
        """边界：参数顺序不影响摘要（字典排序）"""
        calculator = RequestDigestCalculator()
        request1 = {"file": "test.py", "content": "hello", "mode": "write"}
        request2 = {"content": "hello", "mode": "write", "file": "test.py"}
        
        digest1 = calculator.calculate(request1)
        digest2 = calculator.calculate(request2)
        
        assert digest1 == digest2

    def test_boundary_none_values_are_removed(self) -> None:
        """边界：None 值被移除"""
        calculator = RequestDigestCalculator()
        request1 = {"file": "test.py", "content": "hello"}
        request2 = {"file": "test.py", "content": "hello", "mode": None}
        
        digest1 = calculator.calculate(request1)
        digest2 = calculator.calculate(request2)
        
        # None 值移除后，两个请求应该产生相同摘要
        assert digest1 == digest2

    def test_boundary_nested_dict_normalized(self) -> None:
        """边界：嵌套字典正确规范化"""
        calculator = RequestDigestCalculator()
        request = {
            "operation": "create_pr",
            "details": {
                "title": "Fix bug",
                "body": "Description",
                "base": "main",
            }
        }
        
        digest = calculator.calculate(request)
        
        assert digest.startswith("sha256:")
        # 验证嵌套结构不会导致错误
        assert len(digest) == 71

    def test_boundary_nested_list_normalized(self) -> None:
        """边界：嵌套列表正确规范化"""
        calculator = RequestDigestCalculator()
        request = {
            "operation": "batch_write",
            "files": [
                {"path": "a.py", "content": "A"},
                {"path": "b.py", "content": "B"},
            ]
        }
        
        digest = calculator.calculate(request)
        
        assert digest.startswith("sha256:")
        assert len(digest) == 71

    def test_boundary_empty_dict(self) -> None:
        """边界：空字典"""
        calculator = RequestDigestCalculator()
        request = {}
        
        digest = calculator.calculate(request)
        
        assert digest.startswith("sha256:")
        # 空字典也应该有确定的摘要
        assert len(digest) == 71

    def test_smoke_is_sensitive_field(self) -> None:
        """冒烟：敏感字段判断"""
        calculator = RequestDigestCalculator()
        
        # 敏感字段
        assert calculator.is_sensitive_field("password") is True
        assert calculator.is_sensitive_field("token") is True
        assert calculator.is_sensitive_field("api_key") is True
        assert calculator.is_sensitive_field("secret") is True
        assert calculator.is_sensitive_field("private_key") is True
        
        # 非敏感字段
        assert calculator.is_sensitive_field("file") is False
        assert calculator.is_sensitive_field("content") is False
        assert calculator.is_sensitive_field("name") is False

    def test_boundary_sensitive_field_case_insensitive(self) -> None:
        """边界：敏感字段判断不区分大小写"""
        calculator = RequestDigestCalculator()
        
        assert calculator.is_sensitive_field("PASSWORD") is True
        assert calculator.is_sensitive_field("Token") is True
        assert calculator.is_sensitive_field("API_KEY") is True
