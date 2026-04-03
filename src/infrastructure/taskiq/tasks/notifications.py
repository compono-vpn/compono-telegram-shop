import asyncio
import time
from typing import Any, Union, cast

from dishka.integrations.taskiq import FromDishka, inject
from loguru import logger
from redis.asyncio import Redis

from src.bot.keyboards import get_buy_keyboard, get_connect_keyboard, get_renew_keyboard
from src.core.constants import BATCH_DELAY, BATCH_SIZE
from src.core.enums import UserNotificationType
from src.core.storage.keys import PendingNotConnectedRemindersKey
from src.core.utils.iterables import chunked
from src.core.utils.message_payload import MessagePayload
from src.core.utils.types import RemnaUserDto
from src.infrastructure.taskiq.broker import broker
from src.services.notification import NotificationService
from src.services.remnawave import RemnawaveService
from src.services.user import UserService

NOT_CONNECTED_REMINDER_DELAY = 2 * 60 * 60  # 2 hours
NOT_CONNECTED_NOTIFICATION_KEY = "not_connected_reminder"
_PENDING_KEY = PendingNotConnectedRemindersKey()
# Redis dedup: track sent notifications for 90 days
_SENT_NTF_KEY_PREFIX = "sent_ntf:"
_SENT_NTF_TTL = 90 * 24 * 60 * 60  # 90 days


@broker.task
@inject
async def send_error_notification_task(
    error_id: Union[str, int],
    traceback_str: str,
    payload: MessagePayload,
    notification_service: FromDishka[NotificationService],
) -> None:
    await notification_service.error_notify(
        traceback_str=traceback_str,
        payload=payload,
        error_id=error_id,
    )


@broker.task
@inject
async def send_access_opened_notifications_task(
    waiting_user_ids: list[int],
    user_service: FromDishka[UserService],
    notification_service: FromDishka[NotificationService],
) -> None:
    for batch in chunked(waiting_user_ids, BATCH_SIZE):
        for user_telegram_id in batch:
            user = await user_service.get(user_telegram_id)
            await notification_service.notify_user(
                user=user,
                payload=MessagePayload(
                    i18n_key="ntf-access-allowed",
                    auto_delete_after=None,
                    add_close_button=True,
                ),
            )
        await asyncio.sleep(BATCH_DELAY)


@broker.task(retry_on_error=True)
@inject
async def send_subscription_expire_notification_task(
    remna_user: RemnaUserDto,
    ntf_type: UserNotificationType,
    i18n_kwargs: dict[str, Any],
    user_service: FromDishka[UserService],
    notification_service: FromDishka[NotificationService],
) -> None:
    telegram_id = cast(int, remna_user.telegram_id)
    i18n_kwargs_extra: dict[str, Any]

    if ntf_type == UserNotificationType.EXPIRES_IN_3_DAYS:
        i18n_key = "ntf-event-user-expiring"
        i18n_kwargs_extra = {"value": 3}
    elif ntf_type == UserNotificationType.EXPIRES_IN_2_DAYS:
        i18n_key = "ntf-event-user-expiring"
        i18n_kwargs_extra = {"value": 2}
    elif ntf_type == UserNotificationType.EXPIRES_IN_1_DAYS:
        i18n_key = "ntf-event-user-expiring"
        i18n_kwargs_extra = {"value": 1}
    elif ntf_type == UserNotificationType.EXPIRED:
        i18n_key = "ntf-event-user-expired"
        i18n_kwargs_extra = {}
    elif ntf_type == UserNotificationType.EXPIRED_1_DAY_AGO:
        i18n_key = "ntf-event-user-expired-ago"
        i18n_kwargs_extra = {"value": 1}

    user = await user_service.get(telegram_id)

    if not user:
        raise ValueError(f"User '{telegram_id}' not found")

    if not user.current_subscription:
        raise ValueError(f"Current subscription for user '{telegram_id}' not found")

    i18n_kwargs_extra.update({"is_trial": user.current_subscription.is_trial})
    keyboard = get_buy_keyboard() if user.current_subscription.is_trial else get_renew_keyboard()

    await notification_service.notify_user(
        user=user,
        payload=MessagePayload(
            i18n_key=i18n_key,
            i18n_kwargs={**i18n_kwargs, **i18n_kwargs_extra},
            reply_markup=keyboard,
            auto_delete_after=None,
            add_close_button=True,
        ),
        ntf_type=ntf_type,
    )


@broker.task(retry_on_error=True)
@inject
async def send_subscription_limited_notification_task(
    remna_user: RemnaUserDto,
    i18n_kwargs: dict[str, Any],
    user_service: FromDishka[UserService],
    notification_service: FromDishka[NotificationService],
) -> None:
    telegram_id = cast(int, remna_user.telegram_id)
    user = await user_service.get(telegram_id)

    if not user:
        raise ValueError(f"User '{telegram_id}' not found")

    if not user.current_subscription:
        raise ValueError(f"Current subscription for user '{telegram_id}' not found")

    i18n_kwargs_extra = {
        "is_trial": user.current_subscription.is_trial,
        "traffic_strategy": user.current_subscription.traffic_limit_strategy,
        "reset_time": user.current_subscription.get_expire_time,
    }

    keyboard = get_buy_keyboard() if user.current_subscription.is_trial else get_renew_keyboard()

    await notification_service.notify_user(
        user=user,
        payload=MessagePayload(
            i18n_key="ntf-event-user-limited",
            i18n_kwargs={**i18n_kwargs, **i18n_kwargs_extra},
            reply_markup=keyboard,
            auto_delete_after=None,
            add_close_button=True,
        ),
        ntf_type=UserNotificationType.LIMITED,
    )


async def schedule_not_connected_reminder(
    redis_client: Redis,
    user_telegram_id: int,
    connect_url: str,
) -> None:
    """Store a pending reminder in Redis sorted set. No long-running task needed."""
    send_at = time.time() + NOT_CONNECTED_REMINDER_DELAY
    member = f"{user_telegram_id}:{connect_url}"
    await redis_client.zadd(_PENDING_KEY.pack(), {member: send_at}, nx=True)
    logger.debug(f"Scheduled not-connected reminder for '{user_telegram_id}' at {send_at}")


@broker.task(schedule=[{"cron": "*/5 * * * *"}], retry_on_error=False)
@inject
async def process_pending_not_connected_reminders_task(
    user_service: FromDishka[UserService],
    remnawave_service: FromDishka[RemnawaveService],
    notification_service: FromDishka[NotificationService],
    redis_client: FromDishka[Redis],
) -> None:
    """Cron task: every 5 min, process reminders whose delay has elapsed."""
    now = time.time()
    key = _PENDING_KEY.pack()

    due_items: list[bytes] = await redis_client.zrangebyscore(key, "-inf", now)
    if not due_items:
        return

    logger.info(f"Processing {len(due_items)} pending not-connected reminders")

    for raw_member in due_items:
        member = raw_member.decode() if isinstance(raw_member, bytes) else raw_member
        await redis_client.zrem(key, member)

        sep = member.index(":")
        user_telegram_id = int(member[:sep])
        connect_url = member[sep + 1 :]

        # Redis-based dedup (replaces DB sent_notifications table)
        dedup_key = f"{_SENT_NTF_KEY_PREFIX}{user_telegram_id}:{NOT_CONNECTED_NOTIFICATION_KEY}"
        already_sent = await redis_client.exists(dedup_key)
        if already_sent:
            logger.debug(
                f"Skipping not-connected reminder for '{user_telegram_id}': already sent (Redis)"
            )
            continue

        user = await user_service.get(user_telegram_id)
        if not user or not user.current_subscription:
            logger.debug(
                f"Skipping not-connected reminder for '{user_telegram_id}': no user/subscription"
            )
            continue

        if not user.current_subscription.is_active:
            logger.debug(
                f"Skipping not-connected reminder for '{user_telegram_id}': subscription inactive"
            )
            continue

        devices = await remnawave_service.get_devices_user(user)
        if devices:
            logger.debug(
                f"Skipping not-connected reminder for '{user_telegram_id}': already connected"
            )
            continue

        logger.info(f"Sending not-connected reminder to '{user_telegram_id}'")
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(
                i18n_key="ntf-event-user-not-connected",
                reply_markup=get_connect_keyboard(connect_url),
                auto_delete_after=None,
                add_close_button=True,
            ),
            ntf_type=UserNotificationType.NOT_CONNECTED,
        )

        # Mark as sent in Redis with TTL
        await redis_client.setex(dedup_key, _SENT_NTF_TTL, "1")
