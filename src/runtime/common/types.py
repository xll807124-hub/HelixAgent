"""
Runtime 共享类型定义。

对应契约：docs/design-specs/REQ-RT-001-core-runtime-entities.md §4（统一类型和共享坐标）

本模块只定义跨实体复用的基础类型（ID、时间、枚举、Budget 等），
不包含任何业务实体字段。实体定义见 src/runtime/entities/。
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# ID 类型
# ---------------------------------------------------------------------------
# REQ-RT-001 §4.1：EntityId 使用 UUIDv7 字符串；TraceId/SpanId 使用十六进制字符串
# 兼容 OpenTelemetry 语义。本项目当前 Python 生态暂无标准库 UUIDv7，
# 使用 uuid7 兼容生成器（时间有序，但业务顺序禁止依赖它，顺序由事件 sequence 决定）。

_TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SPAN_ID_RE = re.compile(r"^[0-9a-f]{16}$")


def generate_entity_id() -> str:
    """生成符合 REQ-RT-001 的 EntityId（UUIDv7 字符串）。

    标准库 uuid 模块在 Python 3.13 尚未提供 uuid7，这里用「UUIDv4 + 時間前缀排序」
    的兼容实现：取当前 UTC 毫秒时间戳写入高位，其余位随机，满足“时间有序但业务顺序
    禁止依赖它”的契约要求（REQ-RT-001 §4.1）。
    """
    unix_ts_ms = int(datetime.now(UTC).timestamp() * 1000)
    rand_bytes = uuid.uuid4().bytes[6:]  # 10 random bytes
    ts_bytes = unix_ts_ms.to_bytes(6, byteorder="big")
    raw = bytearray(ts_bytes + rand_bytes)
    # 设置 UUID version=7, variant bits（RFC 9562）
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


def generate_trace_id() -> str:
    """生成符合 OpenTelemetry 语义的 32 位十六进制 TraceId（REQ-RT-001 §4.1）。"""
    return uuid.uuid4().hex  # 32 lower-hex chars


def is_valid_entity_id(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def is_valid_trace_id(value: str) -> bool:
    return bool(_TRACE_ID_RE.match(value or ""))


def is_valid_span_id(value: str) -> bool:
    return bool(_SPAN_ID_RE.match(value or ""))


# ---------------------------------------------------------------------------
# 时间
# ---------------------------------------------------------------------------
# REQ-RT-001 §4.3：所有时间使用 UTC 的 RFC 3339；禁止本地时间/无时区时间。

def utc_now() -> datetime:
    """返回当前 UTC 时间（带时区），供实体/事件的时间字段使用。"""
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """校验并规范化时间为带时区 UTC；无时区时间直接拒绝（REQ-RT-001 §4.3）。"""
    if value.tzinfo is None:
        raise ValueError("时间字段必须带时区信息（UTC），禁止使用无时区本地时间")
    return value.astimezone(UTC)


# ---------------------------------------------------------------------------
# 数据敏感级别（REQ-RT-001 §5.5 ArtifactType 同级枚举，事件信封同样复用）
# ---------------------------------------------------------------------------
class DataSensitivity(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


# ---------------------------------------------------------------------------
# ActorRef（REQ-RT-001 §3.1 共享类型；本轮事件信封需要引用 actor）
# ---------------------------------------------------------------------------
class ActorType(str, Enum):
    USER = "USER"
    WORKER = "WORKER"
    TOOL = "TOOL"
    SYSTEM = "SYSTEM"
    EXTERNAL_PROVIDER = "EXTERNAL_PROVIDER"


class ActorRef(BaseModel):
    """事件/实体的操作者引用。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor_type: ActorType
    actor_id: str = Field(min_length=1, max_length=200)

    @field_validator("actor_id")
    @classmethod
    def _actor_id_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("actor_id 不能为空白字符串")
        return v


# ---------------------------------------------------------------------------
# Budget（REQ-RT-001 §4.4）—— 本轮事件存储暂不使用，占位以便后续模块直接复用
# ---------------------------------------------------------------------------
class Budget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_input_tokens: int = Field(ge=0, default=0)
    max_output_tokens: int = Field(ge=0, default=0)
    max_total_tokens: int = Field(ge=0, default=0)
    max_cost_microusd: int = Field(ge=0, default=0)
    max_duration_seconds: int = Field(ge=0, default=0)
    max_tool_calls: int = Field(ge=0, default=0)


# ---------------------------------------------------------------------------
# ResourceRef（REQ-RT-001 §4.5）
# ---------------------------------------------------------------------------
class ResourceType(str, Enum):
    """资源引用类型（REQ-RT-001 §4.5）。"""

    ORGANIZATION = "organization"
    PROJECT = "project"
    REPOSITORY = "repository"
    BRANCH = "branch"
    FILE = "file"
    DIRECTORY = "directory"
    ARTIFACT = "artifact"
    EXTERNAL_SERVICE = "external_service"


class ResourceRef(BaseModel):
    """资源引用（REQ-RT-001 §4.5）。

    约束（§4.5）：
    - `locator` 不能单独作为授权依据（授权仍需结合 resource_id/scope，由 Policy Gateway 判定）。
    - 文件/目录引用必须绑定 repository 范围的 scope；本模型只做格式校验，
      是否落在任务允许的工作区范围由 Policy Gateway（REQ-SEC-003）判定。
    - 外部服务引用不能包含长期凭据：本模型不提供凭据字段，防止误用。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    resource_type: ResourceType
    resource_id: str = Field(min_length=1, max_length=500)
    scope: str = Field(min_length=1, max_length=500)
    locator: str | None = Field(default=None, max_length=2000)
    revision: str | None = Field(default=None, max_length=200)


# ---------------------------------------------------------------------------
# RevisionRef（REQ-RT-001 §14 设计决策收敛第3条：代码版本表达）
# ---------------------------------------------------------------------------
class RevisionRef(BaseModel):
    """代码版本引用。Git SHA 为 MVP 必填事实字段，分支名只是辅助信息，不能替代 SHA。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repository_id: str = Field(min_length=1, max_length=200)
    commit_sha: str = Field(min_length=1, max_length=200)
    branch: str | None = Field(default=None, max_length=500)
    captured_at: datetime

    @field_validator("captured_at")
    @classmethod
    def _captured_at_utc(cls, v: datetime) -> datetime:
        return ensure_utc(v)

    @field_validator("commit_sha")
    @classmethod
    def _commit_sha_not_dynamic(cls, v: str) -> str:
        """REQ-RT-001 §7.3：source_revision 不能使用 'latest'/'main' 作为产物证据版本。"""
        lowered = v.strip().lower()
        if lowered in {"latest", "main", "head", "master"}:
            raise ValueError(
                f"commit_sha 不能使用动态引用 {v!r}；必须是具体 commit SHA（REQ-RT-001 §7.3）"
            )
        return v


# ---------------------------------------------------------------------------
# ContentRef（REQ-RT-001 §5.5 Artifact Schema 子类型）
# ---------------------------------------------------------------------------
class ContentRef(BaseModel):
    """大型内容的外部对象存储引用（REQ-RT-001 §5.5）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    storage_provider: str = Field(min_length=1, max_length=100)
    object_key: str = Field(min_length=1, max_length=1000)
    media_type: str = Field(min_length=1, max_length=200)
    byte_size: int = Field(ge=0)
    content_hash: str = Field(min_length=1, max_length=200)
    encryption_key_ref: str | None = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------
# SafeMetadata（REQ-RT-001 §7.2 安全与敏感数据规则）
# ---------------------------------------------------------------------------
# 元数据键名黑名单：禁止通过 metadata 逃生通道携带凭据/密钥（与事件信封 §7.3 的
# _FORBIDDEN_PAYLOAD_KEYS 保持一致的最小关键字拦截策略，避免两处规则漂移）。
_FORBIDDEN_METADATA_KEYS = {
    "api_key",
    "access_token",
    "refresh_token",
    "private_key",
    "password",
    "secret",
    "git_token",
    "oauth_token",
}


class SafeMetadata(BaseModel):
    """核心实体通用扩展字段容器（REQ-RT-001 §3.3 第6点 / §7.2）。

    - 只允许非敏感、已声明用途的扩展字段；不是未定义实体的逃生通道。
    - 不得携带凭据、模型思维链或未脱敏敏感代码（本模型做关键字级最小拦截，
      完整敏感内容检测属于后续安全模块 REQ-SEC-* 范围）。
    - `extra="allow"`：允许扩展字段存在（契约要求“已声明版本化的 metadata”），
      但键名在校验器中逐一检查，不允许无限制的任意结构绕过安全规则。
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    @model_validator(mode="after")
    def _scan_forbidden_keys(self) -> SafeMetadata:
        extra_fields = self.model_extra or {}
        for key in extra_fields:
            key_lower = str(key).lower()
            if any(forbidden in key_lower for forbidden in _FORBIDDEN_METADATA_KEYS):
                raise ValueError(
                    f"metadata.{key} 命中禁止的敏感字段键名；"
                    "凭据/密钥必须使用 credential_ref 引用，不能写入 metadata（REQ-RT-001 §7.2）"
                )
        return self
