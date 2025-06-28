from typing import Optional

from aiogram_dialog import DialogManager

from app.core.adapter import DialogDataAdapter
from app.core.enums import Currency, PlanAvailability, PlanType
from app.db.models.dto import PlanDurationSchema, PlanPriceSchema, PlanSchema


def generate_prices(price: float) -> list[PlanPriceSchema]:
    return [PlanPriceSchema(currency=currency, price=price) for currency in Currency]


async def create_getter(dialog_manager: DialogManager, **kwargs) -> dict:
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanSchema)

    if plan is None:
        plan = PlanSchema(
            name="Default Plan",
            type=PlanType.BOTH,
            is_active=True,
            traffic_limit=100,
            device_limit=1,
            durations=[
                PlanDurationSchema(days=7, prices=generate_prices(100)),
                PlanDurationSchema(days=30, prices=generate_prices(100)),
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


async def type_getter(dialog_manager: DialogManager, **kwargs) -> dict:
    return {"types": list(PlanType)}


async def availability_getter(dialog_manager: DialogManager, **kwargs) -> dict:
    return {"availability": list(PlanAvailability)}


async def durations_getter(dialog_manager: DialogManager, **kwargs) -> dict:
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanSchema)
    durations = [duration.model_dump() for duration in plan.durations]
    return {"durations": durations}


def get_prices_for_duration(
    durations: list[PlanDurationSchema],
    target_days: int,
) -> list[Optional[PlanPriceSchema]]:
    for duration in durations:
        if duration.days == target_days:
            return duration.prices
    return []


async def prices_getter(dialog_manager: DialogManager, **kwargs) -> dict:
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanSchema)

    duration_selected = dialog_manager.dialog_data.get("duration_selected")
    prices = get_prices_for_duration(plan.durations, duration_selected)
    prices_data = [price.model_dump() for price in prices] if prices else []

    return {
        "duration": duration_selected,
        "prices": prices_data,
    }


async def price_getter(dialog_manager: DialogManager, **kwargs) -> dict:
    duration_selected = dialog_manager.dialog_data.get("duration_selected")
    currency_selected = dialog_manager.dialog_data.get("currency_selected")

    return {
        "duration": duration_selected,
        "currency": currency_selected,
    }
