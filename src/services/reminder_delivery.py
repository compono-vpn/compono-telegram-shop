"""Idempotent, rate-limited delivery shared by the setup and expiry reminders."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Optional

from aiogram.exceptions import (
    TelegramAPIError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import Message
from loguru import logger

from src.core.enums import UserNotificationType
from src.core.utils.message_payload import MessagePayload
from src.infrastructure.billing import BillingClient
from src.models.dto import UserDto
from src.services.notification import NotificationService
from src.services.settings import SettingsService

SEND_INTERVAL_SECONDS = 0.06  # ~16 messages per second, below the 20/s ceiling

Sleeper = Callable[[float], Awaitable[None]]

_TRANSIENT_TELEGRAM_ERRORS = (TelegramRetryAfter, TelegramNetworkError, TelegramServerError)


async def reminder_enabled(
    settings_service: SettingsService, ntf_type: UserNotificationType
) -> bool:
    """Read the switch fresh from billing so a change applies on the next run.

    Fails closed: if the setting cannot be read, nothing is sent.
    """
    try:
        await settings_service.refresh()
        return await settings_service.is_notification_enabled(ntf_type)
    except Exception:
        logger.warning(f"Could not read the '{ntf_type.value}' switch; not sending")
        return False


def can_receive_reminders(user: Optional[UserDto]) -> bool:
    return bool(user and not user.is_blocked and not user.is_bot_blocked)


async def claim_and_send(
    *,
    billing: BillingClient,
    notification_service: NotificationService,
    user: UserDto,
    kind: str,
    dedup_key: str,
    payload: MessagePayload,
    ntf_type: UserNotificationType,
    sleeper: Sleeper = asyncio.sleep,
) -> Optional[Message]:
    """Send at most one message per (user, kind, dedup_key), ever.

    The durable claim is taken first. A transient failure releases the claim and
    re-raises so the caller can retry; a permanent Telegram refusal (blocked bot,
    deleted chat) keeps the claim so the user is never retried.
    """
    if not await billing.claim_user_reminder(user.telegram_id, kind, dedup_key):
        logger.debug(f"Reminder '{kind}' for '{user.telegram_id}' already claimed; skipping")
        return None

    try:
        message = await notification_service.notify_user(
            user=user, payload=payload, ntf_type=ntf_type
        )
    except _TRANSIENT_TELEGRAM_ERRORS:
        await _release_quietly(billing, user.telegram_id, kind, dedup_key)
        raise
    except TelegramAPIError as exception:
        logger.warning(
            f"Reminder '{kind}' to '{user.telegram_id}' refused by Telegram: {exception}"
        )
        return None
    except Exception:
        await _release_quietly(billing, user.telegram_id, kind, dedup_key)
        raise

    if message is not None:
        logger.info(
            f"Sent reminder '{kind}' to '{user.telegram_id}' message_id={message.message_id}"
        )
    else:
        logger.info(f"Reminder '{kind}' to '{user.telegram_id}' was not delivered")

    await sleeper(SEND_INTERVAL_SECONDS)
    return message


async def _release_quietly(
    billing: BillingClient, telegram_id: int, kind: str, dedup_key: str
) -> None:
    try:
        await billing.release_user_reminder(telegram_id, kind, dedup_key)
    except Exception:
        logger.exception(f"Could not release reminder claim '{kind}' for '{telegram_id}'")
