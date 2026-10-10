"""User-initiated upgrade offers; importing a profile is not VPN activation."""

import asyncio
from collections.abc import Sequence
from typing import Any

from loguru import logger

from src.core.enums import PlanAvailability, SetupCheckinAnswer
from src.infrastructure.billing import BillingClient, billing_plan_to_dto
from src.models.dto import PlanDto, UserDto
from src.services.remnawave import RemnawaveService


def has_verified_traffic(remote_user: Any) -> bool:
    traffic = getattr(remote_user, "user_traffic", None)
    return any(
        isinstance(value, (int, float)) and value > 0
        for value in (
            getattr(traffic, "used_traffic_bytes", None),
            getattr(traffic, "lifetime_used_traffic_bytes", None),
        )
    )


def has_opened_subscription(remote_user: Any) -> bool:
    return bool(getattr(remote_user, "sub_last_opened_at", None))


async def has_confirmed_connection(billing: BillingClient, telegram_id: int) -> bool:
    """True when the user answered "yes, it works" to the post-setup check-in."""
    try:
        reminders = await billing.list_user_reminders(telegram_id, "SETUP_CHECKIN")
    except Exception:
        logger.warning("Could not read the setup check-in answer; treating as unconfirmed")
        return False
    if not isinstance(reminders, list):
        return False
    return any(
        getattr(row, "answer", None) == SetupCheckinAnswer.CONNECTED.value for row in reminders
    )


def is_connected(remote_user: Any, devices: Sequence[Any]) -> bool:
    return (
        bool(devices) or has_verified_traffic(remote_user) or has_opened_subscription(remote_user)
    )


async def get_monthly_trial_plan(
    user: UserDto, remnawave: RemnawaveService, billing: BillingClient
) -> PlanDto | None:
    subscription = user.current_subscription
    if (
        user.is_blocked
        or not subscription
        or not subscription.is_trial
        or not subscription.is_active
    ):
        return None
    try:
        async with asyncio.timeout(3):
            remote = await remnawave.get_user(subscription.user_remna_id)
            if not has_verified_traffic(remote) and not await has_confirmed_connection(
                billing, user.telegram_id
            ):
                return None
            plans = [
                billing_plan_to_dto(p) for p in await billing.get_available_plans(user.telegram_id)
            ]
            candidates = [
                p
                for p in plans
                if p.is_active and p.availability != PlanAvailability.TRIAL and p.get_duration(30)
            ]
            return min(candidates, key=lambda p: (p.order_index, p.id or 0), default=None)
    except Exception:
        logger.warning("Trial upgrade offer unavailable; keeping ordinary subscription menu")
        return None
