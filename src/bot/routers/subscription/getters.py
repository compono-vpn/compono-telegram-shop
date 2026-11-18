import asyncio
from decimal import Decimal
from typing import Any, cast
from urllib.parse import urlparse

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from fluentogram import TranslatorRunner
from loguru import logger

from src.bot.plan_screen import (
    DurationRow,
    PlanRow,
    duration_text,
    plan_style,
    plans_text,
    saving_percent,
)
from src.bot.proxy_view import (
    await_entitlement,
    build_success_message,
    primary_desktop_url,
    primary_phone_url,
)
from src.core.config import AppConfig
from src.core.crypto_assets import CRYPTO_ASSETS, CRYPTO_ASSETS_BY_ID
from src.core.enums import PaymentGatewayType, PromocodeRewardType, PurchaseType
from src.core.utils.adapter import DialogDataAdapter
from src.core.utils.formatters import (
    i18n_format_days,
    i18n_format_device_limit,
    i18n_format_expire_time,
    i18n_format_traffic_limit,
)
from src.infrastructure.billing import (
    BillingClient,
    billing_gateway_to_dto,
    billing_plan_to_dto,
    billing_price_details_to_dto,
)
from src.infrastructure.billing.converters import billing_subscription_to_dto
from src.infrastructure.billing.models import BillingSubscription
from src.models.dto import PlanDto, PriceDetailsDto, UserDto
from src.services.bot_payments import bot_gateways, display_currency, ruble_payments_enabled
from src.services.channel_incentive import ChannelIncentiveService
from src.services.dedicated_ip import is_ultra_user
from src.services.experiment import ExperimentService
from src.services.remnawave import RemnawaveService
from src.services.subscription import SubscriptionService
from src.services.trial_activation import get_monthly_trial_plan

from .checkout_experiments import build_checkout_context


async def _await_billing_subscription(
    billing: BillingClient,
    telegram_id: int,
    attempts: int = 6,
    delay: float = 0.5,
) -> BillingSubscription | None:
    """Poll billing for a just-purchased subscription.

    Subscription creation is async (driven by a Kafka event), so the connect and
    success screens can render before billing has committed the new row — the raw
    API then returns None and the screen would hard-fail with "no active
    subscription after purchase". Retry briefly (first check is immediate) so the
    screen waits for the subscription to become visible instead of throwing.
    """
    for attempt in range(attempts):
        sub = await billing.get_current_subscription(telegram_id)
        if sub:
            return sub
        if attempt < attempts - 1:
            await asyncio.sleep(delay)
    return None


@inject
async def subscription_getter(
    dialog_manager: DialogManager,
    user: UserDto,
    billing: FromDishka[BillingClient],
    remnawave_service: FromDishka[RemnawaveService],
    **kwargs: Any,
) -> dict[str, Any]:
    has_active = bool(user.current_subscription and not user.current_subscription.is_trial)
    is_unlimited = user.current_subscription.is_unlimited if user.current_subscription else False
    monthly_plan = await get_monthly_trial_plan(user, remnawave_service, billing)
    return {
        "monthly_trial_offer": monthly_plan is not None,
        "monthly_trial_plan": monthly_plan.name if monthly_plan else "",
        "has_active_subscription": has_active,
        "is_not_unlimited": not is_unlimited,
        "is_ultra": is_ultra_user(user),
    }


MONTH_DAYS = 30


def _month_duration_days(plan: PlanDto) -> int | None:
    if plan.get_duration(MONTH_DAYS):
        return MONTH_DAYS
    return min((d.days for d in plan.durations), default=None)


async def _plan_row(
    billing: BillingClient, telegram_id: int, plan: PlanDto, currency: str
) -> PlanRow:
    days = _month_duration_days(plan)
    row = PlanRow(
        plan_id=plan.id,
        name=plan.name,
        tag=getattr(plan, "tag", None),
        traffic_gb=plan.traffic_limit,
        devices=plan.device_limit,
        price=None,
        days=days,
        currency=currency,
    )
    if days is None or plan.id is None:
        return row
    try:
        details = await billing.calculate_price(
            telegram_id=telegram_id, plan_id=plan.id, duration_days=days, currency=currency
        )
        pricing = billing_price_details_to_dto(details)
        row.price = Decimal(str(pricing.final_amount))
        row.discount_percent = int(pricing.discount_percent or 0)
    except Exception:
        logger.opt(exception=True).warning(f"Could not price plan '{plan.id}' for the plan screen")
    return row


@inject
async def plans_getter(
    dialog_manager: DialogManager,
    user: UserDto,
    i18n: FromDishka[TranslatorRunner],
    billing: FromDishka[BillingClient],
    **kwargs: Any,
) -> dict[str, Any]:
    billing_plans = await billing.get_available_plans(user.telegram_id)
    plans = [billing_plan_to_dto(bp) for bp in billing_plans]
    currency = await display_currency(billing)

    rows = [await _plan_row(billing, user.telegram_id, plan, currency) for plan in plans]
    formatted_plans = [
        {
            "id": plan.id,
            "name": plan.name,
            "label": row.button(),
            "style": plan_style(plan.id, getattr(plan, "tag", None)),
        }
        for plan, row in zip(plans, rows)
    ]

    return {
        "plans": formatted_plans,
        "plans_text": plans_text(rows),
    }


@inject
async def duration_getter(
    dialog_manager: DialogManager,
    user: UserDto,
    i18n: FromDishka[TranslatorRunner],
    billing: FromDishka[BillingClient],
    experiment_service: FromDishka[ExperimentService],
    channel_incentive_service: FromDishka[ChannelIncentiveService],
    **kwargs: Any,
) -> dict[str, Any]:
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanDto)

    if not plan:
        raise ValueError("PlanDto not found in dialog data")

    default_currency = await display_currency(billing)
    only_single_plan = dialog_manager.dialog_data.get("only_single_plan", False)
    dialog_manager.dialog_data["is_free"] = False
    durations = []
    purchase_type = dialog_manager.dialog_data.get("purchase_type")

    for duration in plan.durations:
        key, kw = i18n_format_days(duration.days)
        experiment_context = build_checkout_context(
            experiment_service,
            user,
            plan=plan,
            duration_days=duration.days,
            purchase_type=purchase_type,
        )
        channel_discount = await channel_incentive_service.discount_context(user)
        price_details = await billing.calculate_price(
            telegram_id=user.telegram_id,
            plan_id=plan.id,
            duration_days=duration.days,
            currency=default_currency,
            experiment=experiment_context.billing_experiment if experiment_context else None,
            channel_discount=channel_discount,
        )
        pricing = billing_price_details_to_dto(price_details)
        from src.core.enums import Currency  # noqa: PLC0415

        currency_enum = Currency(default_currency)
        durations.append(
            {
                "days": duration.days,
                "period": i18n.get(key, **kw),
                "final_amount": pricing.final_amount,
                "discount_percent": pricing.discount_percent,
                "original_amount": pricing.original_amount,
                "currency": currency_enum.symbol,
                "has_discount": int(pricing.discount_percent > 0),
            }
        )

    # Saving of a longer period against paying for one month each time, from list prices.
    month = next((d for d in durations if d["days"] == MONTH_DAYS), None)
    month_price = Decimal(str(month["original_amount"])) if month else None
    for item in durations:
        item["label"] = DurationRow(
            days=item["days"],
            price=Decimal(str(item["final_amount"])),
            currency=default_currency,
            saving_percent=saving_percent(
                item["days"], Decimal(str(item["original_amount"])), month_price
            ),
        ).button()
    header_row = PlanRow(
        plan_id=plan.id,
        name=plan.name,
        tag=getattr(plan, "tag", None),
        traffic_gb=plan.traffic_limit,
        devices=plan.device_limit,
        price=None,
        days=None,
        currency=default_currency,
    )

    return {
        "duration_text": duration_text(
            header_row, max((int(d["discount_percent"] or 0) for d in durations), default=0)
        ),
        "style": plan_style(plan.id, getattr(plan, "tag", None)),
        "plan": plan.name,
        "description": plan.description or False,
        "type": plan.type,
        "devices": i18n_format_device_limit(plan.device_limit),
        "traffic": i18n_format_traffic_limit(plan.traffic_limit),
        "durations": durations,
        "period": 0,
        "final_amount": 0,
        "currency": "",
        "only_single_plan": only_single_plan,
    }


@inject
async def payment_method_getter(
    dialog_manager: DialogManager,
    user: UserDto,
    billing: FromDishka[BillingClient],
    i18n: FromDishka[TranslatorRunner],
    experiment_service: FromDishka[ExperimentService],
    channel_incentive_service: FromDishka[ChannelIncentiveService],
    **kwargs: Any,
) -> dict[str, Any]:
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanDto)

    if not plan:
        raise ValueError("PlanDto not found in dialog data")

    billing_gateways = await billing.list_active_gateways()
    gateways = [billing_gateway_to_dto(g) for g in bot_gateways(billing_gateways)]
    selected_duration = dialog_manager.dialog_data["selected_duration"]
    only_single_duration = dialog_manager.dialog_data.get("only_single_duration", False)
    duration = plan.get_duration(selected_duration)

    if not duration:
        raise ValueError(f"Duration '{selected_duration}' not found in plan '{plan.name}'")

    payment_methods = []
    purchase_type = dialog_manager.dialog_data.get("purchase_type")
    experiment_context = build_checkout_context(
        experiment_service,
        user,
        plan=plan,
        duration_days=duration.days,
        purchase_type=purchase_type,
    )
    channel_discount = await channel_incentive_service.discount_context(user)

    for gateway in gateways:
        price_details = await billing.calculate_price(
            telegram_id=user.telegram_id,
            plan_id=plan.id,
            duration_days=duration.days,
            currency=gateway.currency.value,
            experiment=experiment_context.billing_experiment if experiment_context else None,
            channel_discount=channel_discount,
        )
        pricing = billing_price_details_to_dto(price_details)
        payment_methods.append(
            {
                "gateway_type": gateway.type,
                "price": pricing.final_amount,
                "currency": gateway.currency.symbol,
                "has_discount": int(pricing.discount_percent > 0),
            }
        )

    key, kw = i18n_format_days(duration.days)

    return {
        "plan": plan.name,
        "description": plan.description or False,
        "type": plan.type,
        "devices": i18n_format_device_limit(plan.device_limit),
        "traffic": i18n_format_traffic_limit(plan.traffic_limit),
        "period": i18n.get(key, **kw),
        "payment_methods": payment_methods,
        "final_amount": 0,
        "currency": "",
        "only_single_duration": only_single_duration,
        "stars_only": int(not ruble_payments_enabled()),
    }


async def crypto_asset_getter(
    dialog_manager: DialogManager,
    **kwargs: Any,
) -> dict[str, Any]:
    return {
        "crypto_assets": [{"id": asset.id, "label": asset.label} for asset in CRYPTO_ASSETS],
    }


@inject
async def confirm_getter(
    dialog_manager: DialogManager,
    i18n: FromDishka[TranslatorRunner],
    billing: FromDishka[BillingClient],
    **kwargs: Any,
) -> dict[str, Any]:
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanDto)

    if not plan:
        raise ValueError("PlanDto not found in dialog data")

    selected_duration = dialog_manager.dialog_data["selected_duration"]
    only_single_duration = dialog_manager.dialog_data.get("only_single_duration", False)
    is_free = dialog_manager.dialog_data.get("is_free", False)
    selected_payment_method = dialog_manager.dialog_data["selected_payment_method"]
    purchase_type = dialog_manager.dialog_data["purchase_type"]
    billing_gateway = await billing.get_gateway_by_type(
        selected_payment_method.value
        if hasattr(selected_payment_method, "value")
        else str(selected_payment_method)
    )
    duration = plan.get_duration(selected_duration)

    if not duration:
        raise ValueError(f"Duration '{selected_duration}' not found in plan '{plan.name}'")

    if not billing_gateway:
        raise ValueError(f"Not found PaymentGateway by selected type '{selected_payment_method}'")

    payment_gateway = billing_gateway_to_dto(billing_gateway)
    result_url = dialog_manager.dialog_data["payment_url"]
    pricing_data = dialog_manager.dialog_data["final_pricing"]
    pricing = PriceDetailsDto.model_validate_json(pricing_data)

    key, kw = i18n_format_days(duration.days)
    billing_active_gateways = bot_gateways(await billing.list_active_gateways())

    is_plaidly = selected_payment_method == PaymentGatewayType.PLAIDLY
    crypto_asset_id = dialog_manager.dialog_data.get("selected_crypto_asset")
    crypto_asset = CRYPTO_ASSETS_BY_ID.get(crypto_asset_id) if crypto_asset_id else None
    is_webapp = bool(
        is_plaidly and result_url and urlparse(result_url).hostname == "checkout.plaidly.io"
    )

    return {
        "purchase_type": purchase_type,
        "plan": plan.name,
        "description": plan.description or False,
        "type": plan.type,
        "devices": i18n_format_device_limit(plan.device_limit),
        "traffic": i18n_format_traffic_limit(plan.traffic_limit),
        "period": i18n.get(key, **kw),
        "payment_method": selected_payment_method,
        "final_amount": pricing.final_amount,
        "discount_percent": pricing.discount_percent,
        "original_amount": pricing.original_amount,
        "currency": payment_gateway.currency.symbol,
        "url": result_url,
        "only_single_gateway": len(billing_active_gateways) == 1,
        "only_single_duration": only_single_duration,
        "is_free": is_free,
        "show_ruble_note": int(not is_free and not ruble_payments_enabled()),
        "stars_only": int(not ruble_payments_enabled()),
        "is_plaidly": is_plaidly,
        "is_webapp": is_webapp,
        "crypto_asset": crypto_asset.label if crypto_asset else False,
    }


@inject
async def promocode_success_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: UserDto,
    **kwargs: Any,
) -> dict[str, Any]:
    reward_type_value = dialog_manager.dialog_data.get("promocode_reward_type")
    reward_type = PromocodeRewardType(reward_type_value) if reward_type_value else None
    has_subscription = reward_type in (
        PromocodeRewardType.SUBSCRIPTION,
        PromocodeRewardType.DURATION,
    )
    code = dialog_manager.dialog_data.get("promocode_code", "")

    url = ""
    connectable = False

    if has_subscription and user.current_subscription and user.current_subscription.url:
        url = SubscriptionService.build_connect_url(
            user.current_subscription.url, config.website_url
        )
        connectable = True

    return {
        "code": code,
        "has_subscription": int(has_subscription),
        "is_app": False,
        "url": url,
        "connectable": connectable,
    }


@inject
async def getter_connect(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: UserDto,
    billing: FromDishka[BillingClient],
    **kwargs: Any,
) -> dict[str, Any]:
    subscription = user.current_subscription
    if not subscription:
        # Race condition: notification arrived before subscription was committed.
        # Poll the billing API briefly before giving up.
        billing_sub = await _await_billing_subscription(billing, user.telegram_id)
        if not billing_sub:
            raise ValueError(f"User '{user.telegram_id}' has no active subscription after purchase")
        url = billing_sub.URL
    else:
        url = subscription.url

    return {
        "is_app": False,
        "url": SubscriptionService.build_connect_url(url, config.website_url),
        "connectable": True,
    }


@inject
async def success_payment_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: UserDto,
    billing: FromDishka[BillingClient],
    **kwargs: Any,
) -> dict[str, Any]:
    start_data = cast(dict[str, Any], dialog_manager.start_data)
    purchase_type: PurchaseType = start_data["purchase_type"]

    # Always fetch from billing API: user.current_subscription can be stale on
    # CHANGE-type purchases (the user DTO was loaded before the new sub was
    # committed, so it returns the previous plan name). Creation is async, so poll
    # briefly — the success screen can render before billing commits the new sub.
    billing_sub = await _await_billing_subscription(billing, user.telegram_id)
    if billing_sub:
        subscription = billing_subscription_to_dto(billing_sub)
    elif user.current_subscription:
        subscription = user.current_subscription
    else:
        raise ValueError(f"User '{user.telegram_id}' has no active subscription after purchase")

    return {
        "purchase_type": purchase_type,
        "plan_name": subscription.plan.name,
        "traffic_limit": i18n_format_traffic_limit(subscription.traffic_limit),
        "device_limit": i18n_format_device_limit(subscription.device_limit),
        "expire_time": i18n_format_expire_time(subscription.expire_at),
        "added_duration": i18n_format_days(subscription.plan.duration),
        "is_app": False,
        "url": SubscriptionService.build_connect_url(subscription.url, config.website_url),
        "connectable": True,
    }


async def proxy_confirm_getter(dialog_manager: DialogManager, **kwargs: Any) -> dict[str, Any]:
    start_data = cast(dict[str, Any], dialog_manager.start_data)
    return {
        "url": start_data["payment_url"],
        "price": start_data["price"],
        "stars_only": int(not start_data.get("rubles")),
    }


@inject
async def proxy_success_getter(
    dialog_manager: DialogManager,
    user: UserDto,
    billing: FromDishka[BillingClient],
    **kwargs: Any,
) -> dict[str, Any]:
    view = await await_entitlement(billing, user)
    phone_url = primary_phone_url(view) if view.entitled else ""
    desktop_url = primary_desktop_url(view) if view.entitled else ""
    return {
        "proxy_message": build_success_message(view),
        "phone_url": phone_url,
        "desktop_url": desktop_url,
        "has_phone": bool(phone_url),
        "has_desktop": bool(desktop_url),
        "has_personal": view.has_personal,
    }
