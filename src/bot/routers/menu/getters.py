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


@inject
async def menu_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: UserDto,
    i18n: FromDishka[TranslatorRunner],
    billing: FromDishka[BillingClient],
    referral_service: FromDishka[ReferralService],
    experiment_service: FromDishka[ExperimentService],
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
                    "tg_proxy_available": False,
                    "calls_beta_available": False,
                }
            )
            return base_data

        plan_id = subscription.plan.id if subscription.plan else 0
        try:
            tg_proxies = (
                await billing.get_tg_proxies(plan_id) if subscription.is_active and plan_id else []
            )
        except Exception:
            logger.opt(exception=True).warning("Failed to fetch TG proxies, hiding button")
            tg_proxies = []

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
                "url": SubscriptionService.build_connect_url(
                    subscription.url, config.remnawave.sub_public_domain
                ),
                "tg_proxy_available": len(tg_proxies) > 0,
                "calls_beta_available": (
                    subscription.is_active
                    and not subscription.is_trial
                    and config.calls.is_beta_user(user.telegram_id)
                ),
            }
        )

        return base_data
    except Exception as exception:
        raise MenuRenderingError(str(exception)) from exception


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


@inject
async def tg_proxy_getter(
    dialog_manager: DialogManager,
    user: UserDto,
    billing: FromDishka[BillingClient],
    **kwargs: Any,
) -> dict[str, Any]:
    plan_id = (
        user.current_subscription.plan.id
        if user.current_subscription and user.current_subscription.plan
        else 0
    )
    try:
        proxies = await billing.get_tg_proxies(plan_id)
    except Exception:
        logger.opt(exception=True).warning("Failed to fetch TG proxies")
        proxies = []
    proxy_list = [
        {"id": str(p.id), "server": p.server, "port": p.port, "link": p.link} for p in proxies
    ]

    lines = ["<b>📡 Прокси для Telegram</b>\n"]
    if proxy_list:
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
        for p in proxy_list:
            lines.append(f'▸ <a href="{p["link"]}">Подключить {p["server"]}:{p["port"]}</a>')
        lines.append("\nНажмите на ссылку, прокси подключится автоматически.")
    else:
        lines.append("Нет доступных прокси.")

    return {
        "proxies": proxy_list,
        "proxy_message": "\n".join(lines),
        "has_proxies": len(proxy_list) > 0,
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
