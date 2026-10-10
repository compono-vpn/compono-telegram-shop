from typing import Any

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from fluentogram import TranslatorRunner
from loguru import logger

from src.core.config import AppConfig
from src.core.enums import ReferralLevel
from src.core.exceptions import MenuRenderingError
from src.core.utils.formatters import (
    format_username_to_url,
    i18n_format_device_limit,
    i18n_format_expire_time,
    i18n_format_traffic_limit,
)
from src.infrastructure.billing import BillingClient
from src.infrastructure.billing.converters import billing_settings_to_dto
from src.models.dto import UserDto
from src.services.experiment import ExperimentService
from src.services.referral import ReferralService
from src.services.remnawave import RemnawaveService
from src.services.subscription import SubscriptionService


def _proxy_plan_id(user: UserDto) -> int:
    subscription = user.current_subscription
    if subscription and subscription.is_active and not subscription.is_trial and subscription.plan:
        return subscription.plan.id
    return 0


@inject
async def menu_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: UserDto,
    i18n: FromDishka[TranslatorRunner],
    billing: FromDishka[BillingClient],
    referral_service: FromDishka[ReferralService],
    experiment_service: FromDishka[ExperimentService],
    remnawave_service: FromDishka[RemnawaveService],
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        trial_plan = await billing.get_trial_plan()
        has_used_trial = await billing.has_used_trial(user.telegram_id)
        trial_offer_enabled = await experiment_service.is_trial_offer_enabled(user)
        settings = billing_settings_to_dto(await billing.get_settings())
        support_username = config.bot.support_username.get_secret_value()
        ref_link = await referral_service.get_ref_link(user.referral_code)
        support_link = format_username_to_url(support_username, i18n.get("contact-support-help"))

        is_referral_enable = settings.referral.enable

        base_data = {
            "user_id": str(user.telegram_id),
            "user_name": user.name,
            "personal_discount": user.personal_discount,
            "loyalty_discount": user.loyalty_discount,
            "is_beta_tester": 0,
            "support": support_link,
            "invite": i18n.get(
                "referral-invite-message",
                url=ref_link,
                invitee_discount=settings.referral.invitee_reward.amount,
                referrer_days=settings.referral.reward.config.get(ReferralLevel.FIRST, 14),
                long_referrer_days=settings.referral.reward.long_purchase_amount or 30,
            ),
            "has_subscription": user.has_subscription,
            "is_app": config.bot.is_mini_app,
            "is_referral_enable": is_referral_enable,
        }

        subscription = user.current_subscription
        try:
            tg_proxies = await billing.get_tg_proxies(_proxy_plan_id(user))
        except Exception:
            logger.opt(exception=True).warning("Failed to fetch TG proxies, hiding button")
            tg_proxies = []
        base_data["tg_proxy_available"] = bool(tg_proxies)

        if not subscription:
            base_data.update(
                {
                    "status": None,
                    "is_trial": False,
                    "trial_available": bool(
                        not has_used_trial and trial_plan and trial_offer_enabled
                    ),
                    "has_device_limit": False,
                    "connectable": False,
                }
            )
            return base_data

        try:
            base_data["is_beta_tester"] = int(await remnawave_service.is_beta_tester(subscription))
        except Exception:
            logger.opt(exception=True).warning(
                f"Failed to resolve beta tester status for user '{user.telegram_id}'"
            )
        base_data.update(
            {
                "status": subscription.get_status,
                "type": subscription.get_subscription_type,
                "traffic_limit": i18n_format_traffic_limit(subscription.traffic_limit),
                "device_limit": i18n_format_device_limit(subscription.device_limit),
                "expire_time": i18n_format_expire_time(subscription.expire_at),
                "is_trial": subscription.is_trial,
                "traffic_strategy": subscription.traffic_limit_strategy,
                "reset_time": subscription.get_expire_time,
                "has_device_limit": subscription.has_devices_limit
                if subscription.is_active
                else False,
                "connectable": subscription.is_active,
                "is_app": False,
                "url": SubscriptionService.build_connect_url(subscription.url, config.website_url),
                "tg_proxy_available": len(tg_proxies) > 0,
            }
        )

        return base_data
    except Exception as exception:
        raise MenuRenderingError(str(exception)) from exception


@inject
async def connect_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: UserDto,
    **kwargs: Any,
) -> dict[str, Any]:
    subscription = user.current_subscription
    url = ""
    if subscription and subscription.url:
        url = SubscriptionService.build_connect_url(subscription.url, config.website_url)
    return {"url": url}


@inject
async def devices_getter(
    dialog_manager: DialogManager,
    user: UserDto,
    remnawave_service: FromDishka[RemnawaveService],
    **kwargs: Any,
) -> dict[str, Any]:
    if not user.current_subscription:
        logger.warning(f"User '{user.telegram_id}' has no subscription, returning empty devices")
        return {
            "current_count": 0,
            "max_count": i18n_format_device_limit(0),
            "devices": [],
            "devices_empty": True,
        }

    try:
        devices = await remnawave_service.get_devices_user(user)
    except Exception:
        logger.opt(exception=True).warning(f"Failed to fetch devices for user '{user.telegram_id}'")
        devices = []

    formatted_devices = [
        {
            "short_hwid": device.hwid[:32],
            "hwid": device.hwid,
            "platform": device.platform or "",
            "device_model": device.device_model or "",
            "user_agent": device.user_agent or "",
        }
        for device in devices
    ]

    dialog_manager.dialog_data["hwid_map"] = formatted_devices

    return {
        "current_count": len(devices),
        "max_count": i18n_format_device_limit(user.current_subscription.device_limit),
        "devices": formatted_devices,
        "devices_empty": len(devices) == 0,
    }


@inject
async def invite_getter(
    dialog_manager: DialogManager,
    user: UserDto,
    config: AppConfig,
    i18n: FromDishka[TranslatorRunner],
    billing: FromDishka[BillingClient],
    referral_service: FromDishka[ReferralService],
    **kwargs: Any,
) -> dict[str, Any]:
    settings = billing_settings_to_dto(await billing.get_settings())
    referral_settings = settings.referral
    reward_type = referral_settings.reward.type.value
    is_points = referral_settings.reward.is_points

    referrals = await referral_service.get_referral_count(user.telegram_id)
    payments = await referral_service.get_reward_count(user.telegram_id)
    ref_link = await referral_service.get_ref_link(user.referral_code)
    support_username = config.bot.support_username.get_secret_value()
    support_link = format_username_to_url(
        support_username, i18n.get("contact-support-withdraw-points")
    )

    return {
        "reward_type": reward_type,
        "referrals": referrals,
        "payments": payments,
        "points": user.points,
        "is_points_reward": is_points,
        "has_points": True if user.points > 0 else False,
        "referral_link": ref_link,
        "invite": i18n.get(
            "referral-invite-message",
            url=ref_link,
            invitee_discount=referral_settings.invitee_reward.amount,
            referrer_days=referral_settings.reward.config.get(ReferralLevel.FIRST, 14),
            long_referrer_days=referral_settings.reward.long_purchase_amount or 30,
        ),
        "withdraw": support_link,
        "invitee_discount": referral_settings.invitee_reward.amount,
        "long_reward_amount": referral_settings.reward.long_purchase_amount or 30,
        "long_reward_min_days": referral_settings.reward.long_purchase_min_days,
    }


@inject
async def info_getter(app_config: FromDishka[AppConfig], **kwargs: Any) -> dict[str, Any]:
    domain = app_config.hydra_primary_domain
    return {
        "privacy_url": f"https://{domain}/ru/privacy/",
        "terms_url": f"https://{domain}/ru/terms/",
    }


def _phone_proxy_lines(phone_proxies: list[dict[str, Any]], show_plans_offer: bool) -> list[str]:
    lines = ["📱 <b>Телефон</b>"]
    if phone_proxies:
        for p in phone_proxies:
            lines.append(f'▸ <a href="{p["link"]}">Подключить {p["server"]}:{p["port"]}</a>')
    elif show_plans_offer:
        lines.append("▸ Прокси для телефона входит в платный тариф.")
    else:
        lines.append("▸ Прокси для телефона временно недоступны — на телефоне используйте VPN.")
    return lines


def _desktop_proxy_lines(desktop_proxies: list[dict[str, Any]]) -> list[str]:
    stable = [p for p in desktop_proxies if not p["is_public"]]
    backup = [p for p in desktop_proxies if p["is_public"]]
    lines = ["", "💻 <b>Компьютер</b> (Telegram Desktop 7.1.1 и новее)"]
    for p in stable:
        lines.append(f'▸ <a href="{p["link"]}">Подключить {p["server"]}</a> — стабильный')
    if stable and backup:
        lines.append("Запасные, если стабильный не подключается:")
    for p in backup:
        lines.append(f'▸ <a href="{p["link"]}">Подключить {p["server"]}</a>')
    if not stable and len(desktop_proxies) > 1:
        lines.append("Если один не подключается — попробуйте другой.")
    return lines


def _proxy_message(proxy_list: list[dict[str, Any]], show_plans_offer: bool) -> str:
    lines = ["<b>📡 Прокси для Telegram</b>\n"]
    if not proxy_list:
        lines.append("Нет доступных прокси.")
        return "\n".join(lines)
    phone_proxies = [p for p in proxy_list if p["kind"] != "WEB"]
    desktop_proxies = [p for p in proxy_list if p["kind"] == "WEB"]
    lines.append(
        "Telegram-прокси позволяет пользоваться мессенджером"
        " даже без включённого VPN. Полезно, когда VPN"
        " недоступен или вы хотите сэкономить трафик.\n"
    )
    lines.append(
        "⚠️ <b>Важно:</b> подключайте прокси с"
        " <b>выключенным VPN</b> — иначе соединение"
        " может не установиться.\n"
    )
    lines.extend(_phone_proxy_lines(phone_proxies, show_plans_offer))
    if desktop_proxies:
        lines.extend(_desktop_proxy_lines(desktop_proxies))
    if show_plans_offer:
        lines.append("")
        lines.append(
            "⭐ <b>В платном тарифе</b>: прокси для телефона и свой стабильный"
            " прокси для компьютера — им пользуются только подписчики."
        )
    lines.append("\nНажмите на ссылку, прокси подключится автоматически.")
    return "\n".join(lines)


@inject
async def tg_proxy_getter(
    dialog_manager: DialogManager,
    user: UserDto,
    billing: FromDishka[BillingClient],
    **kwargs: Any,
) -> dict[str, Any]:
    plan_id = _proxy_plan_id(user)
    try:
        proxies = await billing.get_tg_proxies(plan_id)
    except Exception:
        logger.opt(exception=True).warning("Failed to fetch TG proxies")
        proxies = []
    proxy_list = [
        {
            "id": str(p.id),
            "server": p.server,
            "port": p.port,
            "link": p.link,
            "kind": p.kind,
            "is_public": p.is_public,
        }
        for p in proxies
    ]
    show_plans_offer = plan_id == 0

    return {
        "proxies": proxy_list,
        "proxy_message": _proxy_message(proxy_list, show_plans_offer),
        "has_proxies": len(proxy_list) > 0,
        "show_plans_offer": show_plans_offer,
        "show_vpn_offer": not user.current_subscription or not user.current_subscription.is_active,
    }


@inject
async def invite_about_getter(
    dialog_manager: DialogManager,
    i18n: FromDishka[TranslatorRunner],
    billing: FromDishka[BillingClient],
    **kwargs: Any,
) -> dict[str, Any]:
    settings = billing_settings_to_dto(await billing.get_settings())
    referral_settings = settings.referral
    reward_strategy = referral_settings.reward.strategy.value
    reward_type = referral_settings.reward.type.value
    config_levels = referral_settings.reward.config
    accrual_strategy = referral_settings.accrual_strategy.value
    max_level = referral_settings.level.value

    # Check if all reward values are identical
    values = list(config_levels.values())
    identical_reward = len(values) <= 1 or all(v == values[0] for v in values)

    reward_levels: dict[str, str] = {}
    for level, val in config_levels.items():
        lvl_int = level.value
        if lvl_int <= max_level:
            reward_levels[f"reward_level_{lvl_int}"] = i18n.get(
                "msg-invite-reward",
                value=val,
                reward_strategy_type=reward_strategy,
                reward_type=reward_type,
            )

    return {
        **reward_levels,
        "reward_type": reward_type,
        "reward_strategy_type": reward_strategy,
        "accrual_strategy": accrual_strategy,
        "identical_reward": identical_reward,
        "max_level": max_level,
        "invitee_discount": referral_settings.invitee_reward.amount,
        "long_reward_amount": referral_settings.reward.long_purchase_amount or 30,
        "long_reward_min_days": referral_settings.reward.long_purchase_min_days,
    }
