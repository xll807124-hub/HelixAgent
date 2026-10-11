"""
OPA 客户端单元测试
"""

from unittest.mock import Mock, patch

import pytest

try:
    from src.security.policy_gateway import OPAClient
except ImportError:
    pytest.skip("OPAClient requires requests library (not installed)", allow_module_level=True)


class TestOPAClient:
    """OPA 客户端测试套件"""

    @patch('src.security.policy_gateway.opa_client.requests.post')
    def test_evaluate_policy_success(self, mock_post):
        """测试成功评估策略"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "result": {
                "allow": True,
                "reason": "允许"
            }
        }
        mock_post.return_value = mock_response

        client = OPAClient(opa_url="http://localhost:8181")
        result = client.evaluate_policy(
            "agent/tool_execution",
            {"tool": {"id": "test_tool"}}
        )

        assert result["allow"] is True
        assert result["reason"] == "允许"
        mock_post.assert_called_once()

    @patch('src.security.policy_gateway.opa_client.requests.post')
    def test_evaluate_policy_with_non_200_response(self, mock_post):
        """测试 OPA 返回非 200 状态码"""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response

        client = OPAClient()

        with pytest.raises(ValueError, match="OPA 评估失败"):
            client.evaluate_policy("agent/test", {})

    @patch('src.security.policy_gateway.opa_client.requests.post')
    def test_evaluate_policy_with_invalid_response_format(self, mock_post):
        """测试 OPA 返回无效格式"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"invalid": "format"}
        mock_post.return_value = mock_response

        client = OPAClient()

        with pytest.raises(ValueError, match="OPA 响应格式错误"):
            client.evaluate_policy("agent/test", {})

    @patch('src.security.policy_gateway.opa_client.requests.post')
    def test_evaluate_policy_timeout(self, mock_post):
        """测试 OPA 请求超时"""
        from requests.exceptions import Timeout
        mock_post.side_effect = Timeout("请求超时")

        client = OPAClient(timeout_seconds=1.0)

        with pytest.raises(TimeoutError, match="OPA 请求超时"):
            client.evaluate_policy("agent/test", {})

    @patch('src.security.policy_gateway.opa_client.requests.post')
    def test_evaluate_policy_connection_error(self, mock_post):
        """测试 OPA 连接失败"""
        from requests.exceptions import ConnectionError as RequestsConnectionError
        mock_post.side_effect = RequestsConnectionError("连接失败")

        client = OPAClient()

        with pytest.raises(ConnectionError, match="无法连接到 OPA 服务"):
            client.evaluate_policy("agent/test", {})

    @patch('src.security.policy_gateway.opa_client.requests.get')
    def test_health_check_success(self, mock_get):
        """测试健康检查成功"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        client = OPAClient()
        result = client.health_check()

        assert result is True

    @patch('src.security.policy_gateway.opa_client.requests.get')
    def test_health_check_failure(self, mock_get):
        """测试健康检查失败"""
        from requests.exceptions import RequestException
        mock_get.side_effect = RequestException("连接失败")

        client = OPAClient()
        result = client.health_check()

        assert result is False

    @patch('src.security.policy_gateway.opa_client.requests.put')
    def test_load_policy_success(self, mock_put):
        """测试成功加载策略"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_put.return_value = mock_response

        client = OPAClient()
        policy_content = """
        package agent
        
        default allow = false
        allow {
            input.tool.risk_level == "LOW"
        }
        """

        result = client.load_policy("test_policy", policy_content)

        assert result is True
        mock_put.assert_called_once()

    @patch('src.security.policy_gateway.opa_client.requests.put')
    def test_load_policy_failure(self, mock_put):
        """测试加载策略失败"""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = "Invalid policy"
        mock_put.return_value = mock_response

        client = OPAClient()

        with pytest.raises(ValueError, match="策略加载失败"):
            client.load_policy("bad_policy", "invalid rego")

    @patch('src.security.policy_gateway.opa_client.requests.put')
    def test_load_policy_connection_error(self, mock_put):
        """测试加载策略时连接失败"""
        from requests.exceptions import RequestException
        mock_put.side_effect = RequestException("连接失败")

        client = OPAClient()

        with pytest.raises(ConnectionError, match="无法连接到 OPA 服务"):
            client.load_policy("test_policy", "package test")

    def test_opa_client_custom_url_and_timeout(self):
        """测试自定义 OPA URL 和超时配置"""
        client = OPAClient(
            opa_url="http://custom-opa:9999",
            timeout_seconds=10.0
        )

        assert client.opa_url == "http://custom-opa:9999"
        assert client.timeout_seconds == 10.0

    def test_opa_client_strips_trailing_slash(self):
        """测试 OPA URL 去除尾部斜杠"""
        client = OPAClient(opa_url="http://localhost:8181/")

        assert client.opa_url == "http://localhost:8181"
