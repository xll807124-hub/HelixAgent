"""
Tool Schema Models for MCP Connector Governance

Implements tool definition, schema digest, and capability trimming.
"""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def canonical_digest(value: Any) -> str:
    """Strict JSON fingerprint: never coerce tuple values or non-string object keys."""
    def validate(item: Any) -> None:
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise ValueError("JSON object keys must be strings")
                validate(child)
        elif type(item) is list:
            for child in item:
                validate(child)
        elif item is not None and type(item) not in (str, int, float, bool):
            raise ValueError("Non-JSON definition value")
    validate(value)
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def as_utc(value: datetime) -> datetime:
    """Legacy naive timestamps represent UTC, never machine-local time."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass
class ToolInputSchema:
    """JSON Schema for tool input parameters."""
    
    type: str = "object"
    properties: dict[str, Any] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)
    additional_properties: bool | dict[str, Any] = False
    raw_schema: dict[str, Any] | None = None
    
    def to_dict(self) -> dict[str, Any]:
        known = {
            "type": self.type,
            "properties": self.properties,
            "required": self.required,
            "additionalProperties": self.additional_properties,
        }
        if self.raw_schema is None:
            return deepcopy(known)
        # Preserve unknown keywords and the distinction between absent and explicit defaults.
        result = deepcopy(self.raw_schema)
        defaults = {"type": "object", "properties": {}, "required": [],
                    "additionalProperties": False}
        for key, value in known.items():
            if key in result or value != defaults[key]:
                result[key] = deepcopy(value)
        return result


@dataclass
class ToolRiskProfile:
    """Risk profile for a tool."""
    
    risk_level: str  # "low", "medium", "high", "critical"
    is_read_only: bool
    requires_human_approval: bool
    data_sensitivity: str  # "L1", "L2", "L3", "L4"
    network_access_required: bool
    filesystem_access_required: bool
    credential_access_required: bool
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_level": self.risk_level,
            "is_read_only": self.is_read_only,
            "requires_human_approval": self.requires_human_approval,
            "data_sensitivity": self.data_sensitivity,
            "network_access_required": self.network_access_required,
            "filesystem_access_required": self.filesystem_access_required,
            "credential_access_required": self.credential_access_required,
        }


@dataclass
class ToolCapability:
    """Capability declarations for a tool."""
    
    allowed_domains: list[str] = field(default_factory=list)  # Network whitelist
    allowed_file_patterns: list[str] = field(default_factory=list)  # File access patterns
    required_scopes: list[str] = field(default_factory=list)  # OAuth scopes
    max_execution_time_seconds: int = 30
    max_retry_count: int = 3
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_domains": self.allowed_domains,
            "allowed_file_patterns": self.allowed_file_patterns,
            "required_scopes": self.required_scopes,
            "max_execution_time_seconds": self.max_execution_time_seconds,
            "max_retry_count": self.max_retry_count,
        }


@dataclass
class ToolSchema:
    """
    Complete tool schema with digest verification.
    
    Schema digest = SHA256(tool_name + canonical_json(input_schema))
    """
    
    tool_name: str
    description: str
    input_schema: ToolInputSchema
    risk_profile: ToolRiskProfile
    capability: ToolCapability
    version: str = "1.0.0"
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    extra_definition: dict[str, Any] = field(default_factory=dict)
    
    def compute_schema_digest(self) -> str:
        """
        Compute SHA256 digest of the tool schema.
        
        Legacy diagnostic only. Admission uses compute_definition_digest instead.
        """
        canonical_data = {
            "tool_name": self.tool_name,
            "input_schema": self.input_schema.to_dict(),
        }
        canonical_json = json.dumps(canonical_data, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()
    
    def compute_full_hash(self) -> str:
        """
        Compute full hash including risk profile and capabilities.
        
        Used for detecting any changes to tool definition.
        """
        full_data = {
            "tool_name": self.tool_name,
            "description": self.description,
            "input_schema": self.input_schema.to_dict(),
            "risk_profile": self.risk_profile.to_dict(),
            "capability": self.capability.to_dict(),
            "version": self.version,
            "extra_definition": self.extra_definition,
        }
        return canonical_digest(full_data)

    def compute_definition_digest(self) -> str:
        """Versioned full definition; timestamps are deliberately excluded."""
        if not isinstance(self.tool_name, str) or not self.tool_name.strip():
            raise ValueError("Tool name is required")
        if not isinstance(self.description, str) or not isinstance(self.version, str):
            raise ValueError("Description and version must be strings")
        return "tool-v1:" + self.compute_full_hash()
    
    def is_breaking_change(self, old_schema: "ToolSchema") -> bool:
        """
        Determine if this schema is a breaking change from old schema.
        
        Breaking changes:
        - Rename tool
        - Add new required parameter
        - Remove existing parameter
        - Change parameter type
        - Increase risk level
        - Add new required capabilities
        
        Safe changes:
        - Add optional parameter
        - Update description
        - Reduce risk level
        """
        # Different tool name = breaking
        if self.tool_name != old_schema.tool_name:
            return True
        
        # New required parameters = breaking
        old_required = set(old_schema.input_schema.required)
        new_required = set(self.input_schema.required)
        if new_required - old_required:  # New required params added
            return True
        
        # Removed parameters = breaking
        old_props = set(old_schema.input_schema.properties.keys())
        new_props = set(self.input_schema.properties.keys())
        if old_props - new_props:  # Parameters removed
            return True
        
        # Risk level increased = breaking
        risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        old_risk = risk_order.get(old_schema.risk_profile.risk_level, 0)
        new_risk = risk_order.get(self.risk_profile.risk_level, 0)
        if new_risk > old_risk:
            return True
        
        # New required scopes = breaking
        old_scopes = set(old_schema.capability.required_scopes)
        new_scopes = set(self.capability.required_scopes)
        if new_scopes - old_scopes:
            return True
        
        return False
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "tool_name": self.tool_name,
            "description": self.description,
            "input_schema": self.input_schema.to_dict(),
            "risk_profile": self.risk_profile.to_dict(),
            "capability": self.capability.to_dict(),
            "version": self.version,
            "schema_digest": self.compute_schema_digest(),
            "full_hash": self.compute_full_hash(),
            "definition_digest": self.compute_definition_digest(),
            "extra_definition": deepcopy(self.extra_definition),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
    
    @classmethod
    def from_mcp_tool_definition(cls, mcp_tool: dict[str, Any]) -> "ToolSchema":
        """
        Parse MCP tools/list response into ToolSchema.
        
        MCP Spec format:
        {
          "name": "get_weather",
          "description": "Get weather for a location",
          "inputSchema": {
            "type": "object",
            "properties": { ... },
            "required": [ ... ]
          }
        }
        """
        canonical_digest(mcp_tool)
        tool_name = mcp_tool.get("name", "")
        description = mcp_tool.get("description", "")
        
        # Parse input schema
        input_schema_data = mcp_tool.get("inputSchema", {})
        if (not isinstance(input_schema_data, dict)
                or input_schema_data.get("type", "object") != "object"
                or not isinstance(input_schema_data.get("properties", {}), dict)
                or not isinstance(input_schema_data.get("required", []), list)
                or any(not isinstance(name, str) for name in input_schema_data.get("required", []))
                or not isinstance(input_schema_data.get("additionalProperties", False),
                                  bool | dict)):
            raise ValueError("Invalid MCP input schema")
        input_schema = ToolInputSchema(
            type=input_schema_data.get("type", "object"),
            properties=deepcopy(input_schema_data.get("properties", {})),
            required=deepcopy(input_schema_data.get("required", [])),
            additional_properties=deepcopy(input_schema_data.get("additionalProperties", False)),
            raw_schema=deepcopy(input_schema_data),
        )
        
        # Default risk profile (should be enhanced with ML/heuristics)
        risk_profile = ToolRiskProfile(
            risk_level="medium",  # Default to medium, override with analysis
            is_read_only=True,  # Conservative default
            requires_human_approval=False,
            data_sensitivity="L2",
            network_access_required=True,
            filesystem_access_required=False,
            credential_access_required=False,
        )
        
        # Default capability
        capability = ToolCapability()
        
        result = cls(
            tool_name=tool_name,
            description=description,
            input_schema=input_schema,
            risk_profile=risk_profile,
            capability=capability,
            extra_definition=deepcopy({key: value for key, value in mcp_tool.items()
                                      if key not in ("name", "description", "inputSchema")}),
        )
        result.compute_definition_digest()
        return result


@dataclass
class ToolApproval:
    """Records approval for a specific tool schema."""
    
    tool_name: str
    schema_digest: str  # Binds approval to specific schema version
    approved_by: str  # User ID
    approved_at: datetime
    approval_type: str  # "two_person", "security_lead", "task_specific"
    valid_until: datetime | None = None  # Expiry for time-limited approvals
    approval_notes: str = ""
    
    def is_valid(self, now: datetime | None = None) -> bool:
        """Check if approval is still valid."""
        if now is None:
            now = datetime.now(UTC)
        
        if self.valid_until and as_utc(now) >= as_utc(self.valid_until):
            return False
        
        return True
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "schema_digest": self.schema_digest,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat(),
            "approval_type": self.approval_type,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "approval_notes": self.approval_notes,
        }
