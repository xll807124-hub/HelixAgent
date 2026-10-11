"""src/api/endpoints/admin/ 公共导出。"""
from .auth import require_admin_token
from .kill_switch import router as kill_switch_router

__all__ = ["kill_switch_router", "require_admin_token"]