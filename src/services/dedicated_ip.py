from typing import Any, Optional

from loguru import logger

from src.bot.keyboards import get_dedicated_ip_keyboard
from src.core.enums import DedicatedIpCountry
from src.core.metrics import DEDICATED_IP_OFFERED_TOTAL
from src.core.utils.message_payload import MessagePayload
from src.infrastructure.billing import BillingClient
from src.models.dto import UserDto
from src.services.notification import NotificationService

ULTRA_TAG = "ULTRA"
KIND = "DEDICATED_IP"
DEDUP_KEY = "v1"


def is_ultra_tag(tag: Optional[str]) -> bool:
    return isinstance(tag, str) and tag.strip().upper() == ULTRA_TAG


def is_ultra_user(user: UserDto) -> bool:
    subscription = user.current_subscription
    return bool(
        subscription
        and subscription.is_active
        and not subscription.is_trial
        and subscription.plan
        and is_ultra_tag(subscription.plan.tag)
    )


def _billing_plan_tag(subscription: Any) -> Optional[str]:
    plan = getattr(subscription, "Plan", None)
    return getattr(plan, "tag", None) if plan else None


def is_active_ultra_billing_subscription(subscription: Any) -> bool:
    return bool(
        subscription
        and not getattr(subscription, "IsTrial", False)
        and is_ultra_tag(_billing_plan_tag(subscription))
    )


async def get_choice(billing: BillingClient, telegram_id: int) -> Optional[DedicatedIpCountry]:
    reminders = await billing.list_user_reminders(telegram_id, KIND)
    for reminder in reminders:
        if reminder.dedup_key != DEDUP_KEY or not reminder.answer:
            continue
        try:
            return DedicatedIpCountry(reminder.answer)
        except ValueError:
            logger.warning(f"Unknown dedicated IP country '{reminder.answer}' for '{telegram_id}'")
    return None


async def send_country_prompt(
    *,
    user: UserDto,
    billing: BillingClient,
    notification_service: NotificationService,
    i18n_key: str,
) -> bool:
    await billing.claim_user_reminder(user.telegram_id, KIND, DEDUP_KEY)
    message = await notification_service.notify_user(
        user=user,
        payload=MessagePayload(
            i18n_key=i18n_key,
            reply_markup=get_dedicated_ip_keyboard(),
            auto_delete_after=None,
            add_close_button=False,
        ),
    )
    return message is not None


async def offer_country_choice(
    *,
    user: UserDto,
    plan_tag: Optional[str],
    billing: BillingClient,
    notification_service: NotificationService,
) -> bool:
    if not is_ultra_tag(plan_tag):
        return False

    try:
        if await get_choice(billing, user.telegram_id) is not None:
            return False
        sent = await send_country_prompt(
            user=user,
            billing=billing,
            notification_service=notification_service,
            i18n_key="ntf-dedicated-ip-offer",
        )
    except Exception:
        logger.opt(exception=True).warning(
            f"Could not offer the dedicated IP country to '{user.telegram_id}'"
        )
        return False

    if sent:
        DEDICATED_IP_OFFERED_TOTAL.inc()
        logger.info(f"Offered the dedicated IP country to '{user.telegram_id}'")
    return sent
