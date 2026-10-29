"""
Persistence Layer - PostgreSQL Implementation
数据持久化 - PostgreSQL 实现
"""

import json
import logging
from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class DatabaseConnection(Protocol):
    """Async database operations required by these repositories."""

    async def execute(self, query: str, *args: object) -> str: ...

    async def fetchrow(self, query: str, *args: object) -> Mapping[str, Any] | None: ...

    async def fetch(self, query: str, *args: object) -> Sequence[Mapping[str, Any]]: ...


class DatabasePool(Protocol):
    def acquire(self) -> AbstractAsyncContextManager[DatabaseConnection]: ...


class ConnectorRepository:
    """
    连接器持久化仓库
    """
    
    def __init__(self, db_pool: DatabasePool) -> None:
        """
        初始化仓库
        
        Args:
            db_pool: 数据库连接池
        """
        self.db_pool = db_pool
    
    async def create_connector(
        self,
        connector_id: str,
        org_id: str,
        config: dict[str, Any],
        status: dict[str, Any],
    ) -> bool:
        """创建连接器"""
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO connectors (
                    connector_id, org_id, config, status, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6)
                """,
                connector_id,
                org_id,
                json.dumps(config),
                json.dumps(status),
                datetime.utcnow(),
                datetime.utcnow(),
            )
        return True
    
    async def get_connector(self, connector_id: str) -> dict | None:
        """获取连接器"""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM connectors WHERE connector_id = $1",
                connector_id
            )
        
        if not row:
            return None
        
        return dict(row)
    
    async def update_connector_status(
        self,
        connector_id: str,
        status: dict[str, Any],
    ) -> bool:
        """更新连接器状态"""
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE connectors 
                SET status = $1, updated_at = $2
                WHERE connector_id = $3
                """,
                json.dumps(status),
                datetime.utcnow(),
                connector_id,
            )
        return True
    
    async def list_by_org(self, org_id: str) -> list[dict]:
        """列出组织的所有连接器"""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM connectors WHERE org_id = $1",
                org_id
            )
        
        return [dict(row) for row in rows]


class ToolRepository:
    """
    工具持久化仓库
    """
    
    def __init__(self, db_pool: DatabasePool) -> None:
        self.db_pool = db_pool
    
    async def register_tool(
        self,
        connector_id: str,
        tool_name: str,
        schema: dict[str, Any],
        schema_digest: str,
    ) -> bool:
        """注册工具"""
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tools (
                    connector_id, tool_name, schema, schema_digest, 
                    created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (connector_id, tool_name) 
                DO UPDATE SET schema = $3, schema_digest = $4, updated_at = $6
                """,
                connector_id,
                tool_name,
                json.dumps(schema),
                schema_digest,
                datetime.utcnow(),
                datetime.utcnow(),
            )
        return True
    
    async def get_tool(
        self,
        connector_id: str,
        tool_name: str,
    ) -> dict | None:
        """获取工具"""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM tools 
                WHERE connector_id = $1 AND tool_name = $2
                """,
                connector_id,
                tool_name,
            )
        
        if not row:
            return None
        
        return dict(row)
    
    async def get_by_schema_digest(
        self,
        connector_id: str,
        schema_digest: str,
    ) -> dict | None:
        """按 Schema 摘要获取工具"""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM tools 
                WHERE connector_id = $1 AND schema_digest = $2
                """,
                connector_id,
                schema_digest,
            )
        
        if not row:
            return None
        
        return dict(row)


class QuotaRepository:
    """
    配额持久化仓库
    """
    
    def __init__(self, db_pool: DatabasePool) -> None:
        self.db_pool = db_pool
    
    async def initialize_quota(
        self,
        org_id: str,
        base_quota: float,
    ) -> bool:
        """初始化配额"""
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO quotas (org_id, base_quota, current_usage, reset_at)
                VALUES ($1, $2, 0, $3)
                ON CONFLICT (org_id) DO NOTHING
                """,
                org_id,
                base_quota,
                datetime.utcnow(),
            )
        return True
    
    async def get_quota(self, org_id: str) -> dict | None:
        """获取配额信息"""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM quotas WHERE org_id = $1",
                org_id
            )
        
        if not row:
            return None
        
        return dict(row)
    
    async def consume_quota(
        self,
        org_id: str,
        amount: float,
    ) -> bool:
        """消耗配额"""
        async with self.db_pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE quotas 
                SET current_usage = current_usage + $1
                WHERE org_id = $2 AND (current_usage + $1) <= base_quota
                """,
                amount,
                org_id,
            )
        
        return result != "UPDATE 0"


class AuditRepository:
    """
    审计日志持久化仓库
    """
    
    def __init__(self, db_pool: DatabasePool) -> None:
        self.db_pool = db_pool
    
    async def log_event(
        self,
        org_id: str,
        event_type: str,
        actor: str,
        resource_type: str,
        resource_id: str,
        action: str,
        result: str,
        metadata: dict[str, Any],
    ) -> bool:
        """记录审计事件"""
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_logs (
                    org_id, event_type, actor, resource_type, resource_id,
                    action, result, metadata, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                org_id,
                event_type,
                actor,
                resource_type,
                resource_id,
                action,
                result,
                json.dumps(metadata),
                datetime.utcnow(),
            )
        return True
    
    async def query_events(
        self,
        org_id: str,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """查询审计事件"""
        query = "SELECT * FROM audit_logs WHERE org_id = $1"
        params: list[str | int] = [org_id]
        
        if event_type:
            query += " AND event_type = $2"
            params.append(event_type)
        
        query += " ORDER BY created_at DESC LIMIT $" + str(len(params) + 1)
        params.append(limit)
        
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        
        return [dict(row) for row in rows]


class DatabaseSchema:
    """
    数据库 Schema 定义和迁移
    """
    
    SCHEMA_SQL = """
    -- Connectors table
    CREATE TABLE IF NOT EXISTS connectors (
        connector_id VARCHAR(255) PRIMARY KEY,
        org_id VARCHAR(255) NOT NULL,
        config JSONB NOT NULL,
        status JSONB NOT NULL,
        created_at TIMESTAMP NOT NULL,
        updated_at TIMESTAMP NOT NULL,
        INDEX idx_org_id (org_id),
        INDEX idx_updated_at (updated_at)
    );
    
    -- Tools table
    CREATE TABLE IF NOT EXISTS tools (
        id SERIAL PRIMARY KEY,
        connector_id VARCHAR(255) NOT NULL,
        tool_name VARCHAR(255) NOT NULL,
        schema JSONB NOT NULL,
        schema_digest VARCHAR(64) NOT NULL,
        created_at TIMESTAMP NOT NULL,
        updated_at TIMESTAMP NOT NULL,
        UNIQUE (connector_id, tool_name),
        INDEX idx_schema_digest (schema_digest)
    );
    
    -- Quotas table
    CREATE TABLE IF NOT EXISTS quotas (
        org_id VARCHAR(255) PRIMARY KEY,
        base_quota NUMERIC(10,2) NOT NULL,
        current_usage NUMERIC(10,2) NOT NULL DEFAULT 0,
        reset_at TIMESTAMP NOT NULL,
        INDEX idx_reset_at (reset_at)
    );
    
    -- Audit logs table
    CREATE TABLE IF NOT EXISTS audit_logs (
        id BIGSERIAL PRIMARY KEY,
        org_id VARCHAR(255) NOT NULL,
        event_type VARCHAR(50) NOT NULL,
        actor VARCHAR(255) NOT NULL,
        resource_type VARCHAR(50) NOT NULL,
        resource_id VARCHAR(255) NOT NULL,
        action VARCHAR(50) NOT NULL,
        result VARCHAR(50) NOT NULL,
        metadata JSONB,
        created_at TIMESTAMP NOT NULL,
        INDEX idx_org_id_created (org_id, created_at),
        INDEX idx_event_type (event_type)
    );
    
    -- Approvals table
    CREATE TABLE IF NOT EXISTS approvals (
        id SERIAL PRIMARY KEY,
        connector_id VARCHAR(255) NOT NULL,
        schema_digest VARCHAR(64) NOT NULL,
        approval_status VARCHAR(50) NOT NULL,
        approved_by VARCHAR(255),
        approved_at TIMESTAMP,
        created_at TIMESTAMP NOT NULL,
        UNIQUE (connector_id, schema_digest)
    );
    """
    
    @staticmethod
    async def initialize_schema(db_pool: DatabasePool) -> bool:
        """初始化数据库 Schema"""
        try:
            async with db_pool.acquire() as conn:
                # 执行 Schema 创建语句
                await conn.execute(DatabaseSchema.SCHEMA_SQL)
            
            logger.info("Database schema initialized successfully")
            return True
        
        except Exception as e:
            logger.error(f"Failed to initialize database schema: {str(e)}")
            return False
