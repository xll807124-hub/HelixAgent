"""
Quota Manager

Weighted quota system based on trust levels, tool count, risk categories.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..models import TrustLevel, get_trust_level_config

logger = logging.getLogger(__name__)


@dataclass
class QuotaConfig:
    """Quota configuration for an organization."""

    org_id: str
    base_quota: float = 1000.0  # Base quota units per hour
    current_usage: float = 0.0
    reset_interval_hours: int = 1
    last_reset: datetime = field(default_factory=datetime.utcnow)

    def should_reset(self) -> bool:
        """Check if quota should reset."""
        return datetime.utcnow() >= self.last_reset + timedelta(hours=self.reset_interval_hours)

    def reset(self) -> None:
        """Reset quota usage."""
        self.current_usage = 0.0
        self.last_reset = datetime.utcnow()
        logger.info(f"Reset quota for org {self.org_id}")

    def remaining(self) -> float:
        """Calculate remaining quota."""
        return max(0.0, self.base_quota - self.current_usage)

    def is_exceeded(self) -> bool:
        """Check if quota is exceeded."""
        return self.current_usage >= self.base_quota


class QuotaManager:
    """
    Weighted quota management system.

    Quota calculation:
    cost = trust_level_weight × tool_count × risk_multiplier × network_multiplier

    Trust level weights:
    - L1: 0.5x
    - L2: 1.0x
    - L3: 3.0x
    - L4: 5.0x
    """

    def __init__(self) -> None:
        self._org_quotas: dict[str, QuotaConfig] = {}

        # Risk multipliers
        self._risk_multipliers = {
            "low": 0.5,
            "medium": 1.0,
            "high": 2.0,
            "critical": 5.0,
        }

        # Network access multiplier
        self._network_multiplier = 1.5

    def initialize_org_quota(
        self,
        org_id: str,
        base_quota: float = 1000.0,
        reset_interval_hours: int = 1,
    ) -> QuotaConfig:
        """
        Initialize quota for an organization.

        Args:
            org_id: Organization ID
            base_quota: Base quota units
            reset_interval_hours: Reset interval in hours

        Returns:
            QuotaConfig
        """
        config = QuotaConfig(
            org_id=org_id,
            base_quota=base_quota,
            reset_interval_hours=reset_interval_hours,
        )

        self._org_quotas[org_id] = config

        logger.info(
            f"Initialized quota for org {org_id}: "
            f"{base_quota} units per {reset_interval_hours}h"
        )

        return config

    def get_quota(self, org_id: str) -> QuotaConfig | None:
        """Get quota config for organization."""
        config = self._org_quotas.get(org_id)

        # Auto-reset if needed
        if config and config.should_reset():
            config.reset()

        return config

    def calculate_cost(
        self,
        trust_level: TrustLevel,
        tool_count: int = 1,
        risk_level: str = "medium",
        requires_network: bool = False,
        requires_credentials: bool = False,
    ) -> float:
        """
        Calculate quota cost for a connector invocation.

        Args:
            trust_level: Connector trust level
            tool_count: Number of tools invoked
            risk_level: Risk level of tools
            requires_network: Whether tools require network access
            requires_credentials: Whether tools require credentials

        Returns:
            Quota cost in units
        """
        # Base weight from trust level
        trust_config = get_trust_level_config(trust_level)
        base_weight = trust_config.quota_weight

        # Risk multiplier
        risk_multiplier = self._risk_multipliers.get(risk_level, 1.0)

        # Network multiplier
        network_multiplier = self._network_multiplier if requires_network else 1.0

        # Credentials multiplier
        cred_multiplier = 1.5 if requires_credentials else 1.0

        # Calculate total cost
        cost = base_weight * tool_count * risk_multiplier * network_multiplier * cred_multiplier

        return cost

    def check_quota(
        self,
        org_id: str,
        cost: float,
    ) -> bool:
        """
        Check if organization has sufficient quota.

        Args:
            org_id: Organization ID
            cost: Quota cost

        Returns:
            True if sufficient quota available
        """
        config = self.get_quota(org_id)
        if not config:
            logger.warning(f"No quota config for org {org_id}, denying by default")
            return False

        return config.remaining() >= cost

    def consume_quota(
        self,
        org_id: str,
        cost: float,
    ) -> bool:
        """
        Consume quota for an organization.

        Args:
            org_id: Organization ID
            cost: Quota cost to consume

        Returns:
            True if quota consumed successfully, False if exceeded
        """
        config = self.get_quota(org_id)
        if not config:
            logger.warning(f"No quota config for org {org_id}")
            return False

        if not self.check_quota(org_id, cost):
            logger.warning(
                f"Quota exceeded for org {org_id}: "
                f"used={config.current_usage:.2f}, cost={cost:.2f}, "
                f"quota={config.base_quota:.2f}"
            )
            return False

        config.current_usage += cost

        logger.debug(
            f"Consumed {cost:.2f} quota for org {org_id} "
            f"(used={config.current_usage:.2f}/{config.base_quota:.2f})"
        )

        return True

    def refund_quota(
        self,
        org_id: str,
        cost: float,
    ) -> None:
        """
        Refund quota (e.g., for failed operations).

        Args:
            org_id: Organization ID
            cost: Quota cost to refund
        """
        config = self.get_quota(org_id)
        if not config:
            return

        config.current_usage = max(0.0, config.current_usage - cost)

        logger.debug(f"Refunded {cost:.2f} quota for org {org_id}")

    def update_base_quota(
        self,
        org_id: str,
        new_base_quota: float,
    ) -> None:
        """
        Update base quota for an organization.

        Args:
            org_id: Organization ID
            new_base_quota: New base quota
        """
        config = self.get_quota(org_id)
        if not config:
            self.initialize_org_quota(org_id, new_base_quota)
            return

        old_quota = config.base_quota
        config.base_quota = new_base_quota

        logger.info(
            f"Updated base quota for org {org_id}: " f"{old_quota:.2f} -> {new_base_quota:.2f}"
        )

    def get_usage_stats(self, org_id: str) -> dict | None:
        """
        Get quota usage statistics for an organization.

        Args:
            org_id: Organization ID

        Returns:
            Usage statistics dictionary
        """
        config = self.get_quota(org_id)
        if not config:
            return None

        return {
            "org_id": org_id,
            "base_quota": config.base_quota,
            "current_usage": config.current_usage,
            "remaining": config.remaining(),
            "usage_percentage": (config.current_usage / config.base_quota * 100)
            if config.base_quota > 0
            else 0,
            "is_exceeded": config.is_exceeded(),
            "last_reset": config.last_reset.isoformat(),
            "reset_interval_hours": config.reset_interval_hours,
        }

    def list_all_quotas(self) -> dict[str, dict]:
        """List quota stats for all organizations."""
        return {
            org_id: stats
            for org_id in self._org_quotas
            if (stats := self.get_usage_stats(org_id)) is not None
        }
