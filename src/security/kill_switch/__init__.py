"""
Kill Switch 公共导出（src/security/kill_switch/__init__.py）。
"""
from .gate import KillSwitchGate
from .manager import RECOVERY_CONFIRM_WINDOW, KillSwitchManager
from .models import (
    BlockReason,
    RecoveryConfirmEvent,
    RecoveryRequestEvent,
    StatusView,
    TriggerEvent,
)
from .state import (
    KillSwitchScope,
    KillSwitchState,
    is_valid_transition,
)
from .triggers import (
    AnomalyTrigger,
    CredentialLeakTrigger,
    PolicyViolationTrigger,
    Trigger,
    TriggerRegistry,
)

__all__ = [
    "AnomalyTrigger",
    "BlockReason",
    "CredentialLeakTrigger",
    "KillSwitchGate",
    "KillSwitchManager",
    "KillSwitchScope",
    "KillSwitchState",
    "PolicyViolationTrigger",
    "RECOVERY_CONFIRM_WINDOW",
    "RecoveryConfirmEvent",
    "RecoveryRequestEvent",
    "StatusView",
    "Trigger",
    "TriggerEvent",
    "TriggerRegistry",
    "is_valid_transition",
]