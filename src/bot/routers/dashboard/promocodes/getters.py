from typing import Any

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.core.enums import PromocodeRewardType
from src.core.utils.adapter import DialogDataAdapter
from src.core.utils.formatters import i18n_format_days, i18n_format_limit, i18n_format_traffic_limit
from src.infrastructure.database.models.dto import PromocodeDto
from src.services.plan import PlanService
from src.services.promocode import PromocodeService


async def configurator_getter(dialog_manager: DialogManager, **kwargs: Any) -> dict[str, Any]:
    adapter = DialogDataAdapter(dialog_manager)
    promocode = adapter.load(PromocodeDto)

    if promocode is None:
        promocode = PromocodeDto()
        adapter.save(promocode)

    data = promocode.model_dump()

    if promocode.reward:
        if promocode.reward_type == PromocodeRewardType.DURATION:
            reward = i18n_format_days(promocode.reward)
            data.update({"reward": reward})
        elif promocode.reward_type == PromocodeRewardType.TRAFFIC:
            reward = i18n_format_traffic_limit(promocode.reward)
            data.update({"reward": reward})

    helpers = {
        "promocode_type": promocode.reward_type,
        "availability_type": promocode.availability,
        "max_activations": i18n_format_limit(promocode.max_activations),
        "lifetime": i18n_format_days(promocode.lifetime),
        "purchase_discount_max_days": i18n_format_limit(promocode.purchase_discount_max_days or -1),
    }

    if promocode.plan:
        plan = {
            "plan_name": promocode.plan.name,
            "plan_type": promocode.plan.type,
            "plan_traffic_limit": promocode.plan.traffic_limit,
            "plan_device_limit": promocode.plan.device_limit,
            "plan_duration": promocode.plan.duration,
        }
        data.update(plan)
    elif promocode.reward_type == PromocodeRewardType.SUBSCRIPTION:
        data.update({
            "plan_name": "—",
            "plan_type": "—",
            "plan_traffic_limit": "—",
            "plan_device_limit": "—",
            "plan_duration": "—",
        })

    data.update(helpers)

    return data


@inject
async def list_getter(
    dialog_manager: DialogManager,
    promocode_service: FromDishka[PromocodeService],
    **kwargs: Any,
) -> dict[str, Any]:
    promocodes = await promocode_service.get_all()

    formatted = [
        {
            "id": p.id,
            "name": f"{'🟢' if p.is_active else '🔴'} {p.code} ({p.reward_type})",
        }
        for p in promocodes
    ]

    return {"promocodes": formatted}


@inject
async def plan_select_getter(
    dialog_manager: DialogManager,
    plan_service: FromDishka[PlanService],
    **kwargs: Any,
) -> dict[str, Any]:
    plans = await plan_service.get_all()
    active_plans = [p for p in plans if p.is_active]

    formatted_plans = [
        {
            "plan_id": plan.id,
            "plan_name": plan.name,
        }
        for plan in active_plans
    ]

    return {"plans": formatted_plans}


@inject
async def plan_duration_getter(
    dialog_manager: DialogManager,
    plan_service: FromDishka[PlanService],
    **kwargs: Any,
) -> dict[str, Any]:
    selected_plan_id = dialog_manager.dialog_data["selected_plan_id"]
    plan = await plan_service.get(selected_plan_id)

    if not plan:
        raise ValueError(f"Plan '{selected_plan_id}' not found")

    durations = [duration.model_dump() for duration in plan.durations]
    return {"durations": durations}
