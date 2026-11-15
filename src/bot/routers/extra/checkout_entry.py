from typing import Optional

from aiogram.fsm.state import State
from aiogram_dialog import DialogManager, ShowMode, StartMode

from src.bot.routers.subscription.handlers import CURRENT_DURATION_KEY
from src.core.enums import PurchaseType
from src.core.utils.adapter import DialogDataAdapter
from src.models.dto import PlanDto


async def open_checkout(
    dialog_manager: DialogManager,
    *,
    state: State,
    purchase_type: PurchaseType,
    plan: Optional[PlanDto] = None,
    duration_days: Optional[int] = None,
) -> None:
    await dialog_manager.start(
        state,
        mode=StartMode.RESET_STACK,
        show_mode=ShowMode.NO_UPDATE,
    )
    dialog_manager.show_mode = ShowMode.DELETE_AND_SEND
    seed: dict = {
        "purchase_type": purchase_type,
        "only_single_plan": False,
        "only_single_duration": False,
    }
    if plan is not None:
        seed["plandto"] = DialogDataAdapter(dialog_manager).save(plan)
    if duration_days is not None:
        seed[CURRENT_DURATION_KEY] = duration_days
    await dialog_manager.update(seed)
