from datetime import datetime, timezone
from html import escape
from typing import Any, Optional

from aiogram import Bot
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


COUNTRY_LABELS = {
    DedicatedIpCountry.LT: "🇱🇹 Литва",
    DedicatedIpCountry.SE: "🇸🇪 Швеция",
    DedicatedIpCountry.NL: "🇳🇱 Нидерланды",
}

# The name compono-api (v0.43.0+, table identity.compono_dedicated_ips) gives this country's
# «Белый список» entry for a user with a dedicated IP there; the entry also moves to the top.
SERVER_NAMES = {
    DedicatedIpCountry.LT: "🇱🇹 Lithuania · Выделенный IP",
    DedicatedIpCountry.SE: "🇸🇪 Sweden · Выделенный IP",
    DedicatedIpCountry.NL: "🇳🇱 Netherlands · Выделенный IP",
}


def server_name(country: DedicatedIpCountry) -> str:
    return SERVER_NAMES[country]


def support_task_text(
    *,
    title: str,
    summary: str,
    telegram_id: int,
    username: Optional[str],
    country: Optional[DedicatedIpCountry],
    command: str,
    subscription_id: Optional[int] = None,
) -> str:
    who = f"@{escape(username)} · " if username else ""
    lines = [
        f"🌐 <b>{escape(title)}</b>",
        "",
        f"Клиент: {who}<code>{telegram_id}</code>",
        f"Страна: {COUNTRY_LABELS.get(country, '—') if country else '—'}",
    ]
    if subscription_id:
        lines.append(f"Подписка: <code>{subscription_id}</code>")
    lines += ["", escape(summary), "", f"<code>{escape(command)}</code>"]
    return "\n".join(lines)


async def send_ip_task(
    bot: Bot,
    config: AppConfig,
    *,
    title: str,
    summary: str,
    telegram_id: int,
    command: str,
    country: Optional[DedicatedIpCountry],
    username: Optional[str] = None,
    subscription_id: Optional[int] = None,
) -> bool:
    text = support_task_text(
        title=title,
        summary=summary,
        telegram_id=telegram_id,
        username=username,
        country=country,
        command=command,
        subscription_id=subscription_id,
    )
    try:
        await bot.send_message(
            chat_id=config.bot.support_chat_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return True
    except Exception:
        logger.opt(exception=True).warning(
            f"Could not DM support about the dedicated IP of '{telegram_id}', using the ops card"
        )
    return await post_ops_event(
        config,
        title=title,
        summary=summary,
        details={"telegram_id": str(telegram_id), "command": command},
        key=f"compono-ultra-ip:{telegram_id}",
    )


async def flag_release_after_expiry(
    *,
    telegram_id: int,
    billing: BillingClient,
    bot: Bot,
    config: AppConfig,
) -> bool:
    country = await get_choice(billing, telegram_id)
    if country is None:
        return False
    current = await billing.get_current_subscription(telegram_id)
    if is_active_ultra_billing_subscription(current):
        return False
    return await send_ip_task(
        bot,
        config,
        title="Ультра закончился: снять IP",
        summary="Подписка закончилась. Снимите выделенный IP.",
        telegram_id=telegram_id,
        command=provision_command("remove", telegram_id),
        country=country,
    )


async def flag_check_after_renewal(
    *,
    user: UserDto,
    country: DedicatedIpCountry,
    bot: Bot,
    config: AppConfig,
) -> bool:
    return await send_ip_task(
        bot,
        config,
        title="Ультра оплачен снова: проверить IP",
        summary=(
            "Проверьте выделенный IP. Если его сняли, подключите заново. "
            f"У клиента первым в списке серверов стоит «{server_name(country)}»."
        ),
        telegram_id=user.telegram_id,
        username=user.username,
        command=(
            f"{provision_command('verify', user.telegram_id)} || "
            f"{provision_command('add', user.telegram_id, country)}"
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
    bot: Optional[Bot] = None,
) -> bool:
    if not is_ultra_tag(plan_tag):
        return False

    try:
        chosen = await get_choice(billing, user.telegram_id)
        if chosen is not None:
            if config is not None and bot is not None:
                await flag_check_after_renewal(user=user, country=chosen, bot=bot, config=config)
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
