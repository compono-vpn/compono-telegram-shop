from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

from src.bot.keyboards import get_dedicated_ip_keyboard
from src.core.config import AppConfig
from src.core.enums import DedicatedIpCountry
from src.core.metrics import DEDICATED_IP_OFFERED_TOTAL
from src.core.utils.message_payload import MessagePayload
from src.infrastructure.billing import BillingClient
from src.models.dto import UserDto
from src.services.notification import NotificationService
from src.services.ops_notify import post_ops_event

ULTRA_TAG = "ULTRA"
KIND = "DEDICATED_IP"
DEDUP_KEY = "v1"
PROVISION_SCRIPT = "tools/compono-dedicated-ip.sh"
ENDED_STATUSES = frozenset({"EXPIRED", "DISABLED", "DELETED"})


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


def _not_ended(subscription: Any) -> bool:
    status = str(getattr(subscription, "Status", "") or "").upper()
    if status in ENDED_STATUSES:
        return False
    expire_at = getattr(subscription, "ExpireAt", None)
    if not isinstance(expire_at, datetime):
        return True
    if expire_at.tzinfo is None:
        expire_at = expire_at.replace(tzinfo=timezone.utc)
    return expire_at > datetime.now(timezone.utc)


def is_active_ultra_billing_subscription(subscription: Any) -> bool:
    return bool(
        subscription
        and not getattr(subscription, "IsTrial", False)
        and is_ultra_tag(_billing_plan_tag(subscription))
        and _not_ended(subscription)
    )


def provision_command(
    action: str, telegram_id: int, country: Optional[DedicatedIpCountry] = None
) -> str:
    suffix = f" {country.value}" if country else ""
    return f"{PROVISION_SCRIPT} {action} {telegram_id}{suffix}"


async def post_ip_card(
    config: AppConfig,
    *,
    telegram_id: int,
    title: str,
    summary: str,
    command: str,
    country: Optional[DedicatedIpCountry],
    extra: Optional[dict[str, Any]] = None,
) -> bool:
    details: dict[str, Any] = {
        "telegram_id": telegram_id,
        "country": country.value if country else "none",
        **(extra or {}),
        "command": command,
    }
    return await post_ops_event(
        config,
        title=title,
        summary=summary,
        details=details,
        key=f"compono-ultra-ip:{telegram_id}",
    )


async def flag_release_after_expiry(
    *,
    telegram_id: int,
    billing: BillingClient,
    config: AppConfig,
) -> bool:
    country = await get_choice(billing, telegram_id)
    if country is None:
        return False
    current = await billing.get_current_subscription(telegram_id)
    if is_active_ultra_billing_subscription(current):
        return False
    return await post_ip_card(
        config,
        telegram_id=telegram_id,
        title=f"Ultra ended: release IP {country.value}",
        summary=f"Ultra for {telegram_id} expired. Release the dedicated IP.",
        command=provision_command("remove", telegram_id),
        country=country,
    )


async def flag_check_after_renewal(
    *,
    telegram_id: int,
    country: DedicatedIpCountry,
    config: AppConfig,
) -> bool:
    return await post_ip_card(
        config,
        telegram_id=telegram_id,
        title=f"Ultra paid again: check IP {country.value}",
        summary=(
            f"Ultra client {telegram_id} paid again. If the IP was released, add it back; "
            "otherwise verify it."
        ),
        command=(
            f"{provision_command('verify', telegram_id)} || "
            f"{provision_command('add', telegram_id, country)}"
        ),
        country=country,
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
    config: Optional[AppConfig] = None,
) -> bool:
    if not is_ultra_tag(plan_tag):
        return False

    try:
        chosen = await get_choice(billing, user.telegram_id)
        if chosen is not None:
            if config is not None:
                await flag_check_after_renewal(
                    telegram_id=user.telegram_id, country=chosen, config=config
                )
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
