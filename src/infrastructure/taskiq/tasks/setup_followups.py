"""Second setup reminder (24 h) and the "did it connect?" check-in (30 min after first fetch).

Only trials created after the feature is deployed are scheduled: the queues are filled by
the trial-created event, never by a scan of existing users.
"""

import asyncio
import time
from datetime import datetime
from typing import Any, Optional

from dishka.integrations.taskiq import FromDishka, inject
from loguru import logger
from redis.asyncio import Redis
from remnapy.exceptions import NotFoundError

from src.bot.keyboards import get_setup_checkin_keyboard, get_setup_reminder_keyboard
from src.core.config import AppConfig
from src.core.enums import UserNotificationType
from src.core.storage.keys import (
    PendingSetupCheckinsKey,
    PendingSetupRemindersKey,
    SetupFetchWatchKey,
)
from src.core.utils.formatters import format_username_to_url
from src.core.utils.message_payload import MessagePayload
from src.infrastructure.billing import BillingClient
from src.infrastructure.taskiq.broker import broker
from src.infrastructure.taskiq.tasks.notifications import user_already_connected
from src.models.dto import UserDto
from src.services.notification import NotificationService
from src.services.reminder_delivery import (
    Sleeper,
    can_receive_reminders,
    claim_and_send,
    reminder_enabled,
)
from src.services.remnawave import RemnawaveService
from src.services.settings import SettingsService
from src.services.subscription import SubscriptionService
from src.services.trial_activation import has_opened_subscription
from src.services.user import UserService

KIND_SETUP_24H = "SETUP_24H"
KIND_SETUP_CHECKIN = "SETUP_CHECKIN"
CHECKIN_DEDUP_KEY = "first"

SETUP_REMINDER_DELAY = 24 * 60 * 60
CHECKIN_DELAY = 30 * 60
WATCH_MAX_AGE = 72 * 60 * 60
MAX_LATENESS = 6 * 60 * 60
RETRY_DELAY = 10 * 60

SUPPORT_TEXT = "Здравствуйте! Не получается подключить VPN."

_REMINDERS_KEY = PendingSetupRemindersKey()
_WATCH_KEY = SetupFetchWatchKey()
_CHECKINS_KEY = PendingSetupCheckinsKey()


def _decode(raw: Any) -> str:
    return raw.decode() if isinstance(raw, bytes) else str(raw)


async def schedule_setup_followups(
    redis_client: Redis,
    telegram_id: int,
    subscription_id: int,
    connect_url: str,
    *,
    now: Optional[float] = None,
) -> None:
    """Queue the 24 h reminder and start watching for the first profile fetch."""
    created = time.time() if now is None else now
    await redis_client.zadd(
        _REMINDERS_KEY.pack(),
        {f"{telegram_id}:{subscription_id}:{connect_url}": created + SETUP_REMINDER_DELAY},
        nx=True,
    )
    await redis_client.zadd(
        _WATCH_KEY.pack(),
        {f"{telegram_id}:{subscription_id}": created},
        nx=True,
    )
    logger.debug(f"Scheduled setup follow-ups for '{telegram_id}' subscription '{subscription_id}'")


def support_url(config: AppConfig) -> str:
    return format_username_to_url(config.bot.support_username.get_secret_value(), SUPPORT_TEXT)


async def _due(redis_client: Redis, key: str, now: float) -> list[tuple[str, float]]:
    rows = await redis_client.zrangebyscore(key, "-inf", now, withscores=True)
    return [(_decode(member), float(score)) for member, score in rows]


async def _requeue_or_drop(
    redis_client: Redis, key: str, member: str, due_at: float, now: float
) -> None:
    if now - due_at > MAX_LATENESS:
        logger.warning(f"Dropping setup follow-up '{key}' item that stayed late for too long")
        return
    await redis_client.zadd(key, {member: now + RETRY_DELAY})


def _trial_matches(user: UserDto, subscription_id: int) -> bool:
    subscription = user.current_subscription
    return bool(
        subscription
        and subscription.id == subscription_id
        and subscription.is_trial
        and subscription.is_active
    )


async def _load_user_with_subscription(
    user_service: Any, subscription_service: SubscriptionService, telegram_id: int
) -> Optional[UserDto]:
    user = await user_service.get(telegram_id)
    if not user:
        return None
    subscription = await subscription_service.get_current(telegram_id)
    user.current_subscription = subscription
    return user


async def process_setup_reminders(
    *,
    redis_client: Redis,
    billing: BillingClient,
    user_service: Any,
    subscription_service: SubscriptionService,
    remnawave_service: RemnawaveService,
    notification_service: NotificationService,
    settings_service: SettingsService,
    config: AppConfig,
    sleeper: Sleeper = asyncio.sleep,
    now: Optional[float] = None,
) -> int:
    """Send the one-shot 24 h setup reminder to trial users who never opened their profile."""
    current = time.time() if now is None else now
    due = await _due(redis_client, _REMINDERS_KEY.pack(), current)
    if not due:
        return 0

    enabled = await reminder_enabled(settings_service, UserNotificationType.SETUP_REMINDER_24H)
    sent = 0
    for member, due_at in due:
        await redis_client.zrem(_REMINDERS_KEY.pack(), member)
        if not enabled:
            logger.info("Setup 24h reminder is switched off; dropping a due item")
            continue
        try:
            telegram_id_raw, subscription_id_raw, connect_url = member.split(":", 2)
            telegram_id, subscription_id = int(telegram_id_raw), int(subscription_id_raw)
        except ValueError:
            logger.warning("Dropping malformed setup 24h reminder item")
            continue

        try:
            user = await _load_user_with_subscription(
                user_service, subscription_service, telegram_id
            )
            if (
                user is None
                or not can_receive_reminders(user)
                or not _trial_matches(user, subscription_id)
            ):
                continue
            assert user.current_subscription is not None
            try:
                connected = await user_already_connected(
                    user, user.current_subscription, remnawave_service
                )
            except NotFoundError:
                logger.info(f"Setup 24h reminder skipped for '{telegram_id}': no panel user")
                continue
            if connected:
                logger.debug(f"Setup 24h reminder skipped for '{telegram_id}': already connected")
                continue
            message = await claim_and_send(
                billing=billing,
                notification_service=notification_service,
                user=user,
                kind=KIND_SETUP_24H,
                dedup_key=f"sub-{subscription_id}",
                payload=MessagePayload(
                    i18n_key="ntf-event-setup-reminder-24h",
                    reply_markup=get_setup_reminder_keyboard(connect_url, support_url(config)),
                    auto_delete_after=None,
                    add_close_button=False,
                ),
                ntf_type=UserNotificationType.SETUP_REMINDER_24H,
                sleeper=sleeper,
            )
            sent += 1 if message else 0
        except Exception:
            logger.exception(f"Setup 24h reminder for '{telegram_id}' failed; will retry")
            await _requeue_or_drop(redis_client, _REMINDERS_KEY.pack(), member, due_at, current)
    return sent


def _opened_at(remote: Any) -> Optional[float]:
    opened = getattr(remote, "sub_last_opened_at", None)
    if isinstance(opened, datetime):
        return opened.timestamp()
    if isinstance(opened, (int, float)):
        return float(opened)
    return None


async def watch_first_profile_fetch(
    *,
    redis_client: Redis,
    user_service: Any,
    subscription_service: SubscriptionService,
    remnawave_service: RemnawaveService,
    settings_service: SettingsService,
    now: Optional[float] = None,
) -> int:
    """Move trials whose profile was first fetched into the 30-minute check-in queue."""
    current = time.time() if now is None else now
    rows = await redis_client.zrange(_WATCH_KEY.pack(), 0, -1, withscores=True)
    if not rows:
        return 0

    enabled = await reminder_enabled(settings_service, UserNotificationType.SETUP_CHECKIN)
    queued = 0
    for raw_member, created in rows:
        member, created_at = _decode(raw_member), float(created)
        if current - created_at > WATCH_MAX_AGE:
            await redis_client.zrem(_WATCH_KEY.pack(), member)
            continue
        if not enabled:
            continue
        try:
            telegram_id_raw, subscription_id_raw = member.split(":", 1)
            telegram_id, subscription_id = int(telegram_id_raw), int(subscription_id_raw)
        except ValueError:
            await redis_client.zrem(_WATCH_KEY.pack(), member)
            continue

        try:
            user = await _load_user_with_subscription(
                user_service, subscription_service, telegram_id
            )
            if not user or not _trial_matches(user, subscription_id):
                await redis_client.zrem(_WATCH_KEY.pack(), member)
                continue
            subscription = user.current_subscription
            assert subscription is not None
            remote = await remnawave_service.get_user(subscription.user_remna_id)
            fetched_at = _opened_at(remote) if remote and has_opened_subscription(remote) else None
            if fetched_at is None or fetched_at < created_at:
                continue
            await redis_client.zadd(
                _CHECKINS_KEY.pack(),
                {f"{telegram_id}:{subscription_id}": fetched_at + CHECKIN_DELAY},
                nx=True,
            )
            await redis_client.zrem(_WATCH_KEY.pack(), member)
            queued += 1
            logger.info(f"First profile fetch seen for '{telegram_id}'; check-in queued")
        except Exception:
            logger.exception(f"Could not check first profile fetch for '{member}'")
    return queued


async def process_setup_checkins(
    *,
    redis_client: Redis,
    billing: BillingClient,
    user_service: Any,
    subscription_service: SubscriptionService,
    notification_service: NotificationService,
    settings_service: SettingsService,
    sleeper: Sleeper = asyncio.sleep,
    now: Optional[float] = None,
) -> int:
    """Ask "did it connect?" once, 30 minutes after the first profile fetch."""
    current = time.time() if now is None else now
    due = await _due(redis_client, _CHECKINS_KEY.pack(), current)
    if not due:
        return 0

    enabled = await reminder_enabled(settings_service, UserNotificationType.SETUP_CHECKIN)
    sent = 0
    for member, due_at in due:
        await redis_client.zrem(_CHECKINS_KEY.pack(), member)
        if not enabled:
            logger.info("Setup check-in is switched off; dropping a due item")
            continue
        if current - due_at > MAX_LATENESS:
            logger.info("Dropping a setup check-in that is too late to be useful")
            continue
        try:
            telegram_id_raw, subscription_id_raw = member.split(":", 1)
            telegram_id, subscription_id = int(telegram_id_raw), int(subscription_id_raw)
        except ValueError:
            logger.warning("Dropping malformed setup check-in item")
            continue

        try:
            user = await _load_user_with_subscription(
                user_service, subscription_service, telegram_id
            )
            if (
                user is None
                or not can_receive_reminders(user)
                or not _trial_matches(user, subscription_id)
            ):
                continue
            message = await claim_and_send(
                billing=billing,
                notification_service=notification_service,
                user=user,
                kind=KIND_SETUP_CHECKIN,
                dedup_key=CHECKIN_DEDUP_KEY,
                payload=MessagePayload(
                    i18n_key="ntf-event-setup-checkin",
                    reply_markup=get_setup_checkin_keyboard(),
                    auto_delete_after=None,
                    add_close_button=False,
                ),
                ntf_type=UserNotificationType.SETUP_CHECKIN,
                sleeper=sleeper,
            )
            sent += 1 if message else 0
        except Exception:
            logger.exception(f"Setup check-in for '{telegram_id}' failed; will retry")
            await _requeue_or_drop(redis_client, _CHECKINS_KEY.pack(), member, due_at, current)
    return sent


@broker.task(schedule=[{"cron": "*/5 * * * *"}], retry_on_error=False)
@inject
async def process_setup_reminders_task(
    redis_client: FromDishka[Redis],
    billing: FromDishka[BillingClient],
    user_service: FromDishka[UserService],
    subscription_service: FromDishka[SubscriptionService],
    remnawave_service: FromDishka[RemnawaveService],
    notification_service: FromDishka[NotificationService],
    settings_service: FromDishka[SettingsService],
    config: FromDishka[AppConfig],
) -> None:
    await process_setup_reminders(
        redis_client=redis_client,
        billing=billing,
        user_service=user_service,
        subscription_service=subscription_service,
        remnawave_service=remnawave_service,
        notification_service=notification_service,
        settings_service=settings_service,
        config=config,
    )


@broker.task(schedule=[{"cron": "*/5 * * * *"}], retry_on_error=False)
@inject
async def watch_first_profile_fetch_task(
    redis_client: FromDishka[Redis],
    user_service: FromDishka[UserService],
    subscription_service: FromDishka[SubscriptionService],
    remnawave_service: FromDishka[RemnawaveService],
    settings_service: FromDishka[SettingsService],
) -> None:
    await watch_first_profile_fetch(
        redis_client=redis_client,
        user_service=user_service,
        subscription_service=subscription_service,
        remnawave_service=remnawave_service,
        settings_service=settings_service,
    )


@broker.task(schedule=[{"cron": "*/5 * * * *"}], retry_on_error=False)
@inject
async def process_setup_checkins_task(
    redis_client: FromDishka[Redis],
    billing: FromDishka[BillingClient],
    user_service: FromDishka[UserService],
    subscription_service: FromDishka[SubscriptionService],
    notification_service: FromDishka[NotificationService],
    settings_service: FromDishka[SettingsService],
) -> None:
    await process_setup_checkins(
        redis_client=redis_client,
        billing=billing,
        user_service=user_service,
        subscription_service=subscription_service,
        notification_service=notification_service,
        settings_service=settings_service,
    )
