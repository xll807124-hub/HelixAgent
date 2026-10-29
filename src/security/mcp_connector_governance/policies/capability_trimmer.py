"""
Capability Trimmer (SEC-007)

把 OrgWhitelistPolicy 中的 OrgCapabilityTrim 规则落地为两件事：
1. tools/list：隐藏被完全限制的工具，并把参数取值限制写进 inputSchema 的 enum；
2. tools/call：拒绝不被允许的调用方法或参数取值。

语义（均为 fail-closed，多条规则取交集即最严格者生效）：
- allowed_methods
  - None：不限制
  - []：该工具对该组织完全不可用
  - 非空：只允许列出的 MCP 方法（如 "tools/call"）；不含 "tools/call" 则工具不可调用
- parameter_restrictions: {参数名: [允许的取值]}
  - 仅约束调用时 *提供了* 的参数；未提供的参数不在此处拒绝（必填校验属于 schema 校验）
  - 取值列表为空：该参数一律不允许提供
  - 数组类参数要求每个元素都在允许列表内
  - 取值比较要求类型一致（True 不等于 1），避免绕过
- rate_limit 不在本模块处理（需要计数状态，属于配额管理范畴）
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from ..models import ToolSchema
from .org_whitelist import OrgCapabilityTrim

logger = logging.getLogger(__name__)

TOOLS_CALL_METHOD = "tools/call"


def _same(a: Any, b: Any) -> bool:
    """类型严格的相等比较。"""
    return type(a) is type(b) and a == b


def _contains(values: Iterable[Any], item: Any) -> bool:
    return any(_same(v, item) for v in values)


def _intersect(a: list[Any], b: list[Any]) -> list[Any]:
    return [x for x in a if _contains(b, x)]


def _union(a: list[Any], b: list[Any]) -> list[Any]:
    return list(a) + [x for x in b if not _contains(a, x)]


@dataclass(frozen=True)
class EffectiveTrim:
    """针对某个工具合并后的生效裁剪规则。"""

    allowed_methods: frozenset[str] | None = None
    parameter_restrictions: dict[str, list[Any]] = field(default_factory=dict)

    def permits_call(self) -> bool:
        return self.allowed_methods is None or TOOLS_CALL_METHOD in self.allowed_methods


def resolve_trims(trims: Iterable[OrgCapabilityTrim], tool_name: str) -> EffectiveTrim:
    """合并适用于 tool_name 的全部规则，多条规则取交集。"""
    methods: set | None = None
    params: dict[str, list[Any]] = {}
    for trim in trims:
        if trim.tool_id != tool_name:
            continue
        if trim.allowed_methods is not None:
            methods = (
                set(trim.allowed_methods)
                if methods is None
                else methods & set(trim.allowed_methods)
            )
        for name, values in (trim.parameter_restrictions or {}).items():
            values = list(values)
            params[name] = _intersect(params[name], values) if name in params else values
    return EffectiveTrim(
        allowed_methods=frozenset(methods) if methods is not None else None,
        parameter_restrictions=params,
    )


def validate_call(effective: EffectiveTrim, arguments: Any) -> str | None:
    """
    校验一次 tools/call。

    Returns:
        None 表示通过，否则为拒绝原因（只包含参数名，不回显参数值）。
    """
    if not effective.permits_call():
        return "Tool call not permitted by organization policy"
    if not effective.parameter_restrictions:
        return None
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return "Tool arguments must be an object"
    for name, allowed in effective.parameter_restrictions.items():
        if name not in arguments:
            continue
        value = arguments[name]
        items = value if isinstance(value, list) else [value]
        if not all(_contains(allowed, item) for item in items):
            return f"Parameter '{name}' value not permitted by organization policy"
    return None


def _narrow_for_schema(tool: ToolSchema, effective: EffectiveTrim) -> dict[str, list[Any]] | None:
    """
    把参数限制与 schema 自带 enum 求交，返回 {参数: 允许值}。
    若某必填参数已无任何可用取值，则该提供方对此工具不可用，返回 None。
    """
    schema = tool.input_schema
    narrowed: dict[str, list[Any]] = {}
    for name, allowed in effective.parameter_restrictions.items():
        prop = schema.properties.get(name)
        if isinstance(prop, dict) and isinstance(prop.get("enum"), list):
            allowed = _intersect(prop["enum"], allowed)
        if not allowed and name in schema.required:
            return None
        narrowed[name] = list(allowed)
    return narrowed


def trim_tool_schema(
    tool: ToolSchema, effectives: list[EffectiveTrim]
) -> ToolSchema | None:
    """
    按所有可访问提供方的裁剪规则，计算对外暴露的工具定义（tools/list）。

    - 没有任何提供方可用：返回 None（完全限制）
    - 某参数只有在 *所有* 可用提供方都限制它时才收窄，取值为各方允许值的并集
    - 不修改注册表中的原对象
    """
    usable: list[dict[str, list[Any]]] = []
    for eff in effectives:
        if not eff.permits_call():
            continue
        narrowed = _narrow_for_schema(tool, eff)
        if narrowed is not None:
            usable.append(narrowed)
    if not usable:
        return None

    merged: dict[str, list[Any]] = {}
    for name in set(usable[0]):
        if all(name in u for u in usable):
            values: list[Any] = []
            for u in usable:
                values = _union(values, u[name])
            merged[name] = values
    if not merged:
        return tool

    properties = copy.deepcopy(tool.input_schema.properties)
    required = list(tool.input_schema.required)
    for name, values in merged.items():
        prop = properties.get(name)
        if not isinstance(prop, dict):
            continue
        if values:
            prop["enum"] = list(values)
        else:
            # 没有任何允许取值：该参数不再对外暴露（必填情形在上面已被判为不可用）
            del properties[name]
            if name in required:
                required.remove(name)
    return replace(
        tool,
        input_schema=replace(tool.input_schema, properties=properties, required=required),
    )
