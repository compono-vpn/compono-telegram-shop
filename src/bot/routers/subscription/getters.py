from typing import Any, cast

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from fluentogram import TranslatorRunner

from src.core.config import AppConfig
from src.core.enums import PurchaseType
from src.core.utils.adapter import DialogDataAdapter
from src.core.utils.formatters import (
    i18n_format_days,
    i18n_format_device_limit,
    i18n_format_expire_time,
    i18n_format_traffic_limit,
)
from src.infrastructure.billing import BillingClient, billing_plan_to_dto, billing_price_details_to_dto, billing_gateway_to_dto
from src.models.dto import PlanDto, PriceDetailsDto, UserDto
from src.core.enums import PromocodeRewardType
from src.services.subscription import SubscriptionService


@inject
async def subscription_getter(
    dialog_manager: DialogManager,
    user: UserDto,
    **kwargs: Any,
) -> dict[str, Any]:
    has_active = bool(user.current_subscription and not user.current_subscription.is_trial)
    is_unlimited = user.current_subscription.is_unlimited if user.current_subscription else False
    return {
        "has_active_subscription": has_active,
        "is_not_unlimited": not is_unlimited,
    }


@inject
async def plans_getter(
    dialog_manager: DialogManager,
    user: UserDto,
    billing: FromDishka[BillingClient],
    **kwargs: Any,
) -> dict[str, Any]:
    billing_plans = await billing.get_available_plans(user.telegram_id)
    plans = [billing_plan_to_dto(bp) for bp in billing_plans]

    formatted_plans = [
        {
            "id": plan.id,
            "name": plan.name,
        }
        for plan in plans
    ]

    return {
        "plans": formatted_plans,
    }


@inject
async def duration_getter(
    dialog_manager: DialogManager,
    user: UserDto,
    i18n: FromDishka[TranslatorRunner],
    billing: FromDishka[BillingClient],
    **kwargs: Any,
) -> dict[str, Any]:
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanDto)

    if not plan:
        raise ValueError("PlanDto not found in dialog data")

    default_currency = await billing.get_default_currency()
    only_single_plan = dialog_manager.dialog_data.get("only_single_plan", False)
    dialog_manager.dialog_data["is_free"] = False
    durations = []

    for duration in plan.durations:
        key, kw = i18n_format_days(duration.days)
        price_details = await billing.calculate_price(
            telegram_id=user.telegram_id,
            plan_id=plan.id,
            duration_days=duration.days,
            currency=default_currency,
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

    return {
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
    **kwargs: Any,
) -> dict[str, Any]:
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanDto)

    if not plan:
        raise ValueError("PlanDto not found in dialog data")

    billing_gateways = await billing.list_active_gateways()
    gateways = [billing_gateway_to_dto(g) for g in billing_gateways if g.Channel in ("BOT", "ALL")]
    selected_duration = dialog_manager.dialog_data["selected_duration"]
    only_single_duration = dialog_manager.dialog_data.get("only_single_duration", False)
    duration = plan.get_duration(selected_duration)

    if not duration:
        raise ValueError(f"Duration '{selected_duration}' not found in plan '{plan.name}'")

    payment_methods = []
    for gateway in gateways:
        price_details = await billing.calculate_price(
            telegram_id=user.telegram_id,
            plan_id=plan.id,
            duration_days=duration.days,
            currency=gateway.currency.value,
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
    billing_gateway = await billing.get_gateway_by_type(selected_payment_method.value if hasattr(selected_payment_method, 'value') else str(selected_payment_method))
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
    billing_active_gateways = [g for g in await billing.list_active_gateways() if g.Channel in ("BOT", "ALL")]

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
    has_subscription = reward_type in (PromocodeRewardType.SUBSCRIPTION, PromocodeRewardType.DURATION)
    code = dialog_manager.dialog_data.get("promocode_code", "")

    url = ""
    connectable = False

    if has_subscription and user.current_subscription and user.current_subscription.url:
        url = SubscriptionService.build_connect_url(
            user.current_subscription.url, config.remnawave.sub_public_domain
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
        # Fall back to billing API.
        billing_sub = await billing.get_current_subscription(user.telegram_id)
        if not billing_sub:
            raise ValueError(f"User '{user.telegram_id}' has no active subscription after purchase")
        url = billing_sub.URL
    else:
        url = subscription.url

    return {
        "is_app": False,
        "url": SubscriptionService.build_connect_url(url, config.remnawave.sub_public_domain),
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
    subscription = user.current_subscription

    if not subscription:
        # Race condition: notification arrived before subscription was committed.
        # Fall back to billing API.
        from src.infrastructure.billing.converters import billing_subscription_to_dto
        billing_sub = await billing.get_current_subscription(user.telegram_id)
        if billing_sub:
            subscription = billing_subscription_to_dto(billing_sub)
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
        "url": SubscriptionService.build_connect_url(subscription.url, config.remnawave.sub_public_domain),
        "connectable": True,
    }
