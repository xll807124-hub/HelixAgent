"""
测试辅助工具：创建有效的 Evidence 实体
"""
import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from src.runtime.entities.evidence import (
    Evidence,
    EvidenceResult,
    EvidenceSource,
    EvidenceType,
    VerificationMethod,
    VerifierType,
)


def create_test_evidence(
    evidence_id: str | None = None,
    task_id: str | None = None,
    workflow_id: str | None = None,
    source_action_id: str | None = None,
    producer_worker_id: str | None = None,
    evidence_type: EvidenceType = EvidenceType.TEST_PASSED,
    source: EvidenceSource = EvidenceSource.TOOL,
    result: EvidenceResult = EvidenceResult.PASSED,
    content: dict | None = None,
    trace_id: str | None = None,
    source_revision: str = "abc123def456",
    verification_method: VerificationMethod = VerificationMethod.DETERMINISTIC_CHECK,
    verifier_type: VerifierType = VerifierType.SYSTEM,
    verifier_id: str = "system-verifier",
) -> Evidence:
    """
    创建测试用的 Evidence 实体
    
    Args:
        evidence_id: Evidence ID（默认生成）
        task_id: Task ID（默认生成）
        workflow_id: Workflow ID（默认生成）
        source_action_id: 来源 Action ID
        producer_worker_id: 生产者 Worker ID
        evidence_type: Evidence 类型
        source: Evidence 来源
        result: Evidence 结果
        content: 内容（将存储为 content_inline）
        trace_id: Trace ID（默认生成）
        source_revision: 源代码版本
        verification_method: 验证方法
        verifier_type: 验证者类型
        verifier_id: 验证者 ID
        
    Returns:
        Evidence 实体
    """
    evidence_id = evidence_id or str(uuid4())
    task_id = task_id or str(uuid4())
    workflow_id = workflow_id or str(uuid4())
    trace_id = trace_id or "a" * 32

    content = content or {}
    content_json = json.dumps(content, sort_keys=True)
    content_hash = hashlib.sha256(content_json.encode()).hexdigest()

    now = datetime.now(UTC)

    return Evidence(
        evidence_id=evidence_id,
        task_id=task_id,
        workflow_id=workflow_id,
        source_action_id=source_action_id,
        producer_worker_id=producer_worker_id,
        type=evidence_type,
        source=source,
        source_revision=source_revision,
        verification_method=verification_method,
        verifier_type=verifier_type,
        verifier_id=verifier_id,
        result=result,
        content_schema="generic.v1",
        content_schema_version="1.0.0",
        content_hash=content_hash,
        content_inline=content,
        trace_id=trace_id,
        created_at=now,
        verified_at=now,
    )
