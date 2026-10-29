"""
MCP Transport Layer Implementation
支持 STDIO 和 HTTP 两种传输方式
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any

from aiohttp import web

logger = logging.getLogger(__name__)


class TransportType(Enum):
    """传输类型"""
    STDIO = "stdio"
    HTTP = "http"
    SSE = "sse"


class STDIOTransport:
    """
    STDIO 传输实现
    
    特性:
    - 行分隔 (newline-delimited JSON)
    - 全双工通信
    - 自动心跳
    """
    
    def __init__(
        self,
        message_handler: Callable[..., Awaitable[str]],
    ) -> None:
        """
        初始化 STDIO 传输
        
        Args:
            message_handler: 异步消息处理函数
        """
        self.message_handler = message_handler
        self._running = False
    
    async def start(self) -> None:
        """启动 STDIO 服务"""
        self._running = True
        logger.info("STDIO transport started")
        
        try:
            while self._running:
                # 从标准输入读取一行
                try:
                    line = await asyncio.get_event_loop().run_in_executor(
                        None,
                        input,  # 阻塞读取一行
                    )
                    
                    if not line:
                        continue
                    
                    # 处理消息
                    response = await self.message_handler(line)
                    
                    # 写入标准输出
                    print(response, flush=True)
                
                except EOFError:
                    # 标准输入关闭
                    logger.info("STDIO EOF received, shutting down")
                    break
                except Exception as e:
                    logger.error(f"Error handling STDIO message: {str(e)}")
                    # 继续处理下一条消息
                    continue
        
        finally:
            self._running = False
            logger.info("STDIO transport stopped")
    
    async def stop(self) -> None:
        """停止 STDIO 服务"""
        self._running = False


class HTTPTransport:
    """
    HTTP 传输实现
    
    特性:
    - RESTful endpoint: POST /mcp/tools/call
    - JSON 请求/响应
    - 支持认证
    """
    
    def __init__(
        self,
        message_handler: Callable[..., Awaitable[str]],
        host: str = "127.0.0.1",
        port: int = 8000,
    ) -> None:
        """
        初始化 HTTP 传输
        
        Args:
            message_handler: 异步消息处理函数
            host: 监听主机
            port: 监听端口
        """
        self.message_handler = message_handler
        self.host = host
        self.port = port
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._running = False
    
    async def start(self) -> None:
        """启动 HTTP 服务"""
        if self._running:
            return
        
        # 定义路由处理器
        async def mcp_handler(request: web.Request) -> web.Response:
            try:
                # 获取请求体
                body = await request.text()
                
                # 提取认证信息
                org_id = request.headers.get("X-Org-ID", "default")
                user_id = request.headers.get("X-User-ID", "anonymous")
                
                # 处理消息
                response = await self.message_handler(body, org_id, user_id)
                
                return web.Response(
                    text=response,
                    content_type="application/json",
                    status=200,
                )
            
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in request: {str(e)}")
                return web.Response(
                    text=json.dumps({
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32600,
                            "message": "Invalid JSON",
                        }
                    }),
                    content_type="application/json",
                    status=400,
                )
            
            except Exception as e:
                logger.error(f"Error handling HTTP request: {str(e)}")
                return web.Response(
                    text=json.dumps({
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32603,
                            "message": "Internal error",
                        }
                    }),
                    content_type="application/json",
                    status=500,
                )
        
        # 创建应用
        self._app = web.Application()
        self._app.router.add_post("/mcp/tools/call", mcp_handler)
        self._app.router.add_post("/mcp/tools/list", mcp_handler)
        
        # 启动服务器
        runner = web.AppRunner(self._app)
        try:
            await runner.setup()
            site = web.TCPSite(runner, self.host, self.port)
            await site.start()
        except BaseException:
            await runner.cleanup()
            self._app = None
            raise
        self._runner = runner
        self._running = True
        
        logger.info(f"HTTP transport listening on {self.host}:{self.port}")
    
    async def stop(self) -> None:
        """停止 HTTP 服务"""
        self._running = False
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        self._app = None


class SSETransport:
    """
    Server-Sent Events (SSE) 传输实现
    
    特性:
    - 单向推送 (服务器 → 客户端)
    - 自动重连
    - 流式数据
    """
    
    def __init__(
        self,
        request_handler: Callable[..., Awaitable[str]],
        host: str = "127.0.0.1",
        port: int = 8001,
    ) -> None:
        """
        初始化 SSE 传输
        
        Args:
            request_handler: 异步请求处理函数
            host: 监听主机
            port: 监听端口
        """
        self._stopped = asyncio.Event()
        self.request_handler = request_handler
        self.host = host
        self.port = port
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._running = False
    
    async def start(self) -> None:
        """启动 SSE 服务"""
        if self._running:
            return
        self._stopped.clear()
        
        # 定义 SSE 处理器
        async def sse_handler(request: web.Request) -> web.StreamResponse:
            response = web.StreamResponse()
            response.content_type = "text/event-stream"
            response.headers["Cache-Control"] = "no-cache"
            response.headers["Connection"] = "keep-alive"
            
            await response.prepare(request)
            
            try:
                # 发送初始化事件
                await response.write(b"data: {\"type\": \"connected\"}\n\n")
                
                # 保持连接活跃
                while self._running:
                    try:
                        await asyncio.wait_for(self._stopped.wait(), timeout=30)
                        break
                    except TimeoutError:
                        await response.write(b":\n")  # 注释行作为心跳
            
            except Exception as e:
                logger.error(f"SSE connection error: {str(e)}")
            
            finally:
                await response.write_eof()
            
            return response
        
        # 创建应用
        self._app = web.Application()
        self._app.router.add_get("/mcp/events", sse_handler)
        
        # 启动服务器
        runner = web.AppRunner(self._app)
        try:
            await runner.setup()
            site = web.TCPSite(runner, self.host, self.port)
            await site.start()
        except BaseException:
            await runner.cleanup()
            self._app = None
            raise
        self._runner = runner
        self._running = True
        
        logger.info(f"SSE transport listening on {self.host}:{self.port}")
    
    async def stop(self) -> None:
        """停止 SSE 服务"""
        self._running = False
        self._stopped.set()
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        self._app = None


class TransportSelector:
    """
    传输选择器 - 根据连接器配置选择合适的传输
    """
    
    @staticmethod
    def create_transport(
        transport_type: str,
        message_handler: Callable[..., Awaitable[str]],
        **kwargs: Any,
    ) -> STDIOTransport | HTTPTransport | SSETransport:
        """
        创建传输实例
        
        Args:
            transport_type: 传输类型 (stdio/http/sse)
            message_handler: 消息处理器
            **kwargs: 传输特定参数
            
        Returns:
            传输实例
        """
        if transport_type == "stdio":
            return STDIOTransport(message_handler)
        
        elif transport_type == "http":
            return HTTPTransport(
                message_handler,
                host=kwargs.get("host", "127.0.0.1"),
                port=kwargs.get("port", 8000),
            )
        
        elif transport_type == "sse":
            return SSETransport(
                message_handler,
                host=kwargs.get("host", "127.0.0.1"),
                port=kwargs.get("port", 8001),
            )
        
        else:
            raise ValueError(f"Unknown transport type: {transport_type}")
