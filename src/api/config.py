"""
FastAPI 应用配置（src/api/config.py）。

通过 Pydantic Settings 从环境变量加载，启动期 fail-fast 校验必需配置。
对齐：AGENTS.md §7「配置必须与代码分离」「禁止破坏既有健康检查语义」。
"""
from __future__ import annotations

from functools import lru_cache
from uuid import UUID

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class APISettings(BaseSettings):
    """API 层运行时配置。所有字段均可通过 ENV 覆盖（如 AI_API_PORT=9000）。

    必需字段：缺失时启动即抛错，避免运行期才发现配置不全。
    """

    model_config = SettingsConfigDict(
        env_prefix="AI_API_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 服务
    host: str = Field(default="127.0.0.1", min_length=1, max_length=200)
    port: int = Field(default=8000, ge=1, le=65535)
    workers: int = Field(default=1, ge=1, le=32)
    reload: bool = Field(default=False)

    # API 元数据
    title: str = Field(
        default="AI Agent Platform API",
        min_length=1,
        max_length=200,
    )
    version: str = Field(default="0.1.0", min_length=1, max_length=50)

    # 跨域（MVP 默认关闭；前端另起服务时再开）
    cors_origins: str = Field(default="", max_length=2000)

    # 限流（粗粒度，MVP 用全局内存计数器；生产应替换为 Redis）
    rate_limit_per_minute: int = Field(default=120, ge=1, le=10000)

    # 单组织部署使用显式配置的 token -> principal 映射；空配置时拒绝业务请求。
    auth_required: bool = Field(default=True)
    auth_tokens: dict[str, str] = Field(default_factory=dict, repr=False)
    tool_allowed_paths: list[str] = Field(default_factory=list)

    @field_validator("auth_tokens")
    @classmethod
    def validate_auth_tokens(cls, tokens: dict[str, str]) -> dict[str, str]:
        if any(not token.strip() or not principal.strip() for token, principal in tokens.items()):
            raise ValueError("Auth tokens and principal IDs must be non-empty")
        for principal in tokens.values():
            UUID(principal)  # Task.creator_id uses the Runtime EntityId contract.
        return tokens

    @property
    def cors_origin_list(self) -> list[str]:
        """解析逗号分隔的 CORS 来源字符串。空串返回空列表。"""
        if not self.cors_origins.strip():
            return []
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> APISettings:
    """缓存单例配置对象，避免每次请求重新解析环境变量。"""
    return APISettings()
