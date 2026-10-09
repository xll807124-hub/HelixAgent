"""
OPA (Open Policy Agent) 客户端

提供与 OPA 服务的通信接口。
"""
# mypy: ignore-errors
# 遗留代码，依赖 requests 库（未安装类型存根）

from typing import Any

import requests
from requests.exceptions import RequestException, Timeout


class OPAClient:
    """OPA 客户端"""

    def __init__(
        self,
        opa_url: str = "http://localhost:8181",
        timeout_seconds: float = 5.0
    ):
        """
        初始化 OPA 客户端
        
        Args:
            opa_url: OPA 服务地址
            timeout_seconds: 请求超时时间
        """
        self.opa_url = opa_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def evaluate_policy(
        self,
        policy_path: str,
        input_data: dict[str, Any]
    ) -> dict[str, Any]:
        """
        评估策略
        
        Args:
            policy_path: 策略路径（例如 "agent/tool_execution"）
            input_data: 输入数据
            
        Returns:
            策略评估结果
            
        Raises:
            ConnectionError: 无法连接到 OPA 服务
            TimeoutError: 请求超时
            ValueError: 策略评估失败
        """
        url = f"{self.opa_url}/v1/data/{policy_path}"

        try:
            response = requests.post(
                url,
                json={"input": input_data},
                headers={"Content-Type": "application/json"},
                timeout=self.timeout_seconds
            )

            if response.status_code != 200:
                raise ValueError(
                    f"OPA 评估失败: HTTP {response.status_code}, {response.text}"
                )

            result = response.json()

            # OPA 返回格式: {"result": {...}}
            if "result" not in result:
                raise ValueError(f"OPA 响应格式错误: {result}")

            return result["result"]  # type: ignore[no-any-return]

        except Timeout:
            raise TimeoutError(
                f"OPA 请求超时: {url} (timeout={self.timeout_seconds}s)"
            )

        except RequestException as e:
            raise ConnectionError(f"无法连接到 OPA 服务: {e}")

    def health_check(self) -> bool:
        """
        健康检查
        
        Returns:
            OPA 服务是否健康
        """
        try:
            response = requests.get(
                f"{self.opa_url}/health",
                timeout=self.timeout_seconds
            )
            return response.status_code == 200
        except RequestException:
            return False

    def load_policy(
        self,
        policy_id: str,
        policy_content: str
    ) -> bool:
        """
        加载策略（通过 Policy API）
        
        Args:
            policy_id: 策略标识
            policy_content: Rego 策略内容
            
        Returns:
            是否成功加载
            
        Raises:
            ValueError: 策略加载失败
        """
        url = f"{self.opa_url}/v1/policies/{policy_id}"

        try:
            response = requests.put(
                url,
                data=policy_content,
                headers={"Content-Type": "text/plain"},
                timeout=self.timeout_seconds
            )

            if response.status_code not in [200, 204]:
                raise ValueError(
                    f"策略加载失败: HTTP {response.status_code}, {response.text}"
                )

            return True

        except RequestException as e:
            raise ConnectionError(f"无法连接到 OPA 服务: {e}")
