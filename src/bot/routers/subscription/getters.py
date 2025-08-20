from typing import Any

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from fluentogram import TranslatorRunner
from loguru import logger

from src.core.constants import USER_KEY
from src.core.utils.adapter import DialogDataAdapter
from src.core.utils.formatters import format_subscription_period
from src.infrastructure.database.models.dto import PlanDto, UserDto
from src.services import NotificationService, PaymentGatewayService, PlanService, UserService


@inject
async def subscription_getter(
    dialog_manager: DialogManager,
    user_service: FromDishka[UserService],
    **kwargs: Any,
) -> dict[str, Any]:
    return {}


@inject
async def plans_getter(
    dialog_manager: DialogManager,
    plan_service: FromDishka[PlanService],
    notification_service: FromDishka[NotificationService],
    **kwargs: Any,
) -> dict[str, Any]:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    plans: list[PlanDto] = await plan_service.get_available_plans(user=user)

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
    user_service: FromDishka[UserService],
    payment_gateway_service: FromDishka[PaymentGatewayService],
    i18n: FromDishka[TranslatorRunner],
    **kwargs: Any,
) -> dict[str, Any]:
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanDto)
    logger.debug(f"Loaded plan: {plan}")
    logger.critical(dialog_manager.dialog_data)

    currency = await payment_gateway_service.get_default_currency()
    durations = [
        {
            "days": duration.days,
            "period": format_subscription_period(days=duration.days, i18n=i18n),
            "price": duration.get_price(currency).price,
            "currency": currency.symbol,
        }
        for duration in plan.durations
    ]

    return {
        "plan": plan.name,
        "type": plan.type,
        "devices": plan.device_limit,
        "traffic": plan.traffic_limit,
        "period": 0,
        "durations": durations,
    }


@inject
async def payment_method_getter(
    dialog_manager: DialogManager,
    user_service: FromDishka[UserService],
    payment_gateway_service: FromDishka[PaymentGatewayService],
    i18n: FromDishka[TranslatorRunner],
    **kwargs: Any,
) -> dict[str, Any]:
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanDto)
    logger.debug(f"Loaded plan: {plan}")

    gateways = await payment_gateway_service.filter_active()
    selected_duration = dialog_manager.dialog_data["selected_duration"]
    duration = plan.get_duration(selected_duration)

    payment_methods = []
    for gateway in gateways:
        price_obj = duration.get_price(gateway.currency)
        if not price_obj:
            continue

        payment_methods.append(
            {
                "method": gateway.type,
                "price": price_obj.price,
                "currency": price_obj.currency.symbol,
            }
        )

    return {
        "plan": plan.name,
        "type": plan.type,
        "devices": plan.device_limit,
        "traffic": plan.traffic_limit,
        "period": format_subscription_period(days=duration.days, i18n=i18n),
        "payment_methods": payment_methods,
    }


@inject
async def confirm_getter(
    dialog_manager: DialogManager,
    user_service: FromDishka[UserService],
    i18n: FromDishka[TranslatorRunner],
    **kwargs: Any,
) -> dict[str, Any]:
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanDto)
    logger.debug(f"Loaded plan: {plan}")

    return {}
