from typing import Any, Optional

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.core.enums import Currency, PlanAvailability, PlanType
from src.core.utils.adapter import DialogDataAdapter
from src.infrastructure.database.models.dto import PlanDto, PlanDurationDto, PlanPriceDto
from src.services import PlanService


@inject
async def plans_getter(
    dialog_manager: DialogManager,
    plan_service: FromDishka[PlanService],
    **kwargs: Any,
) -> dict[str, Any]:
    plans: list[PlanDto] = await plan_service.get_all()
    formatted_plans = [
        {
            "id": plan.id,
            "name": plan.name,
            "is_active": plan.is_active,
        }
        for plan in plans
    ]

    return {
        "plans": formatted_plans,
    }


def generate_prices(price: float) -> list[PlanPriceDto]:
    return [PlanPriceDto(currency=currency, price=price) for currency in Currency]


async def plan_getter(dialog_manager: DialogManager, **kwargs: Any) -> dict[str, Any]:
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanDto)

    if plan is None:
        plan = PlanDto(
            name="Default Plan",
            type=PlanType.BOTH,
            is_active=False,
            traffic_limit=100,
            device_limit=1,
            durations=[
                PlanDurationDto(days=7, prices=generate_prices(100)),
                PlanDurationDto(days=30, prices=generate_prices(100)),
            ],
            availability=PlanAvailability.ALL,
            allowed_users_ids=None,
        )
        adapter.save(plan)

    helpers = {
        "has_traffic_limit": plan.type in {PlanType.TRAFFIC, PlanType.BOTH},
        "has_device_limit": plan.type in {PlanType.DEVICES, PlanType.BOTH},
    }

    data = plan.model_dump()
    data.update(helpers)
    return data


async def type_getter(dialog_manager: DialogManager, **kwargs: Any) -> dict[str, Any]:
    return {"types": list(PlanType)}


async def availability_getter(dialog_manager: DialogManager, **kwargs: Any) -> dict[str, Any]:
    return {"availability": list(PlanAvailability)}


async def durations_getter(dialog_manager: DialogManager, **kwargs: Any) -> dict[str, Any]:
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanDto)

    if not plan:
        return {}

    durations = [duration.model_dump() for duration in plan.durations]
    return {"durations": durations}


def get_prices_for_duration(
    durations: list[PlanDurationDto],
    target_days: int,
) -> Optional[list[PlanPriceDto]]:
    for duration in durations:
        if duration.days == target_days:
            return duration.prices
    return []


async def prices_getter(dialog_manager: DialogManager, **kwargs: Any) -> dict[str, Any]:
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanDto)

    if not plan:
        return {}

    duration_selected = dialog_manager.dialog_data["duration_selected"]
    prices = get_prices_for_duration(plan.durations, duration_selected)
    prices_data = [price.model_dump() for price in prices] if prices else []

    return {
        "duration": duration_selected,
        "prices": prices_data,
    }


async def price_getter(dialog_manager: DialogManager, **kwargs: Any) -> dict[str, Any]:
    duration_selected = dialog_manager.dialog_data.get("duration_selected")
    currency_selected = dialog_manager.dialog_data.get("currency_selected")
    logger.info(currency_selected)
    return {
        "duration": duration_selected,
        "currency": currency_selected,
    }


async def allowed_users_getter(dialog_manager: DialogManager, **kwargs: Any) -> dict[str, Any]:
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanDto)

    return {"allowed_users": plan.allowed_user_ids if plan.allowed_user_ids else []}
