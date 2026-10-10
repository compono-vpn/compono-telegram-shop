"""Expiring and expired subscription notices (trial and paid).

Expired notices are driven by billing's ``subscription.expired`` event; expiring notices by a
half-hourly scan. Every notice is claimed once per (user, subscription, event, expiry date) in
billing, switched by the existing per-type settings, and paced below 20 messages per second.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from dishka.integrations.taskiq import FromDishka, inject
from loguru import logger

from src.bot.keyboards import get_buy_keyboard, get_renew_keyboard
from src.core.enums import UserNotificationType
from src.core.utils.message_payload import MessagePayload
from src.infrastructure.billing import BillingClient
from src.infrastructure.taskiq.broker import broker
from src.models.dto import UserDto
from src.services.notification import NotificationService
from src.services.reminder_delivery import (
    Sleeper,
    can_receive_reminders,
    claim_and_send,
    reminder_enabled,
)
from src.services.settings import SettingsService
from src.services.subscription import SubscriptionService
from src.services.user import UserService

KIND_EXPIRED = "SUB_EXPIRED"
EXPIRED_MAX_AGE = timedelta(hours=48)
EXPIRING_WINDOW = timedelta(hours=2)

TRIAL_MARKS_DAYS = (1,)
PAID_MARKS_DAYS = (3, 1)
_EXPIRING_TYPES = {
    3: UserNotificationType.EXPIRES_IN_3_DAYS,
    1: UserNotificationType.EXPIRES_IN_1_DAYS,
}


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _parse_dt(raw: Any) -> Optional[datetime]:
    if isinstance(raw, datetime):
        return _utc(raw)
    if isinstance(raw, str):
        try:
            return _utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def dedup_key(subscription_id: int, expire_at: datetime) -> str:
    return f"sub-{subscription_id}:{expire_at:%Y%m%d}"


def _keyboard(is_trial: bool):  # type: ignore[no-untyped-def]
    return get_buy_keyboard() if is_trial else get_renew_keyboard()


async def notify_subscription_expired(
    *,
    payload: dict,
    billing: BillingClient,
    user_service: UserService,
    subscription_service: SubscriptionService,
    notification_service: NotificationService,
    settings_service: SettingsService,
    sleeper: Sleeper = asyncio.sleep,
    now: Optional[datetime] = None,
) -> bool:
    """Handle one billing ``subscription.expired`` event. True when a message was sent."""
    telegram_id = payload.get("telegram_id")
    subscription_id = payload.get("subscription_id")
    expire_at = _parse_dt(payload.get("expire_at"))
    if not telegram_id or not subscription_id or expire_at is None:
        logger.warning("Expired-subscription event without user, subscription or expiry; skipping")
        return False

    current = now or datetime.now(timezone.utc)
    if current - expire_at > EXPIRED_MAX_AGE:
        logger.info(f"Expired event for '{telegram_id}' is older than 48h; not notifying")
        return False
    if expire_at > current:
        logger.info(f"Expired event for '{telegram_id}' arrived before the expiry time; skipping")
        return False

    if not await reminder_enabled(settings_service, UserNotificationType.EXPIRED):
        logger.info("Expired notice is switched off; skipping")
        return False

    user = await user_service.get(int(telegram_id))
    if not user or not can_receive_reminders(user):
        return False

    current_subscription = await subscription_service.get_current(int(telegram_id))
    if current_subscription is None or current_subscription.id != int(subscription_id):
        logger.info(f"Expired event for '{telegram_id}' skipped: not their current subscription")
        return False
    if current_subscription.is_active and _utc(current_subscription.expire_at) > current:  # type: ignore[operator]
        logger.info(f"Expired event for '{telegram_id}' skipped: subscription already renewed")
        return False

    billing_subscription = await billing.get_subscription(int(subscription_id))
    is_trial = bool(billing_subscription.IsTrial) if billing_subscription else False

    message = await claim_and_send(
        billing=billing,
        notification_service=notification_service,
        user=user,
        kind=KIND_EXPIRED,
        dedup_key=dedup_key(int(subscription_id), expire_at),
        payload=MessagePayload(
            i18n_key="ntf-event-user-expired",
            i18n_kwargs={"is_trial": is_trial},
            reply_markup=_keyboard(is_trial),
            auto_delete_after=None,
            add_close_button=True,
        ),
        ntf_type=UserNotificationType.EXPIRED,
        sleeper=sleeper,
    )
    return message is not None


def due_expiring_marks(
    *, is_trial: bool, expire_at: datetime, now: datetime
) -> list[tuple[int, UserNotificationType]]:
    remaining = expire_at - now
    marks = TRIAL_MARKS_DAYS if is_trial else PAID_MARKS_DAYS
    return [
        (days, _EXPIRING_TYPES[days])
        for days in marks
        if timedelta(days=days) - EXPIRING_WINDOW < remaining <= timedelta(days=days)
    ]


def collect_due_notices(
    subscriptions: list[Any], now: datetime
) -> list[tuple[Any, int, UserNotificationType, datetime]]:
    due: list[tuple[Any, int, UserNotificationType, datetime]] = []
    for subscription in subscriptions:
        expire_at = _utc(subscription.ExpireAt)
        if subscription.Status != "ACTIVE" or expire_at is None:
            continue
        for days, ntf_type in due_expiring_marks(
            is_trial=subscription.IsTrial, expire_at=expire_at, now=now
        ):
            due.append((subscription, days, ntf_type, expire_at))
    return due


async def send_expiring_notifications(
    *,
    billing: BillingClient,
    user_service: UserService,
    subscription_service: SubscriptionService,
    notification_service: NotificationService,
    settings_service: SettingsService,
    sleeper: Sleeper = asyncio.sleep,
    now: Optional[datetime] = None,
) -> int:
    """Send 'expires in N days' notices to subscriptions entering the final N-day window."""
    current = now or datetime.now(timezone.utc)
    due = collect_due_notices(await billing.list_all_subscriptions(), current)
    if not due:
        return 0

    enabled: dict[UserNotificationType, bool] = {}
    sent = 0
    for subscription, days, ntf_type, expire_at in due:
        if ntf_type not in enabled:
            enabled[ntf_type] = await reminder_enabled(settings_service, ntf_type)
        if not enabled[ntf_type]:
            continue
        try:
            user: Optional[UserDto] = await user_service.get(subscription.UserTelegramID)
            if not user or not can_receive_reminders(user):
                continue
            active = await subscription_service.get_current(subscription.UserTelegramID)
            if not active or active.id != subscription.ID or not active.is_active:
                continue
            message = await claim_and_send(
                billing=billing,
                notification_service=notification_service,
                user=user,
                kind=f"SUB_EXPIRING_{days}D",
                dedup_key=dedup_key(subscription.ID, expire_at),
                payload=MessagePayload(
                    i18n_key="ntf-event-user-expiring",
                    i18n_kwargs={"is_trial": subscription.IsTrial, "value": days},
                    reply_markup=_keyboard(subscription.IsTrial),
                    auto_delete_after=None,
                    add_close_button=True,
                ),
                ntf_type=ntf_type,
                sleeper=sleeper,
            )
            sent += 1 if message else 0
        except Exception:
            logger.exception(
                f"Expiring notice for '{subscription.UserTelegramID}' failed; next scan retries"
            )
    return sent


@broker.task(schedule=[{"cron": "*/30 * * * *"}], retry_on_error=False)
@inject
async def send_expiring_notifications_task(
    billing: FromDishka[BillingClient],
    user_service: FromDishka[UserService],
    subscription_service: FromDishka[SubscriptionService],
    notification_service: FromDishka[NotificationService],
    settings_service: FromDishka[SettingsService],
) -> None:
    await send_expiring_notifications(
        billing=billing,
        user_service=user_service,
        subscription_service=subscription_service,
        notification_service=notification_service,
        settings_service=settings_service,
    )
