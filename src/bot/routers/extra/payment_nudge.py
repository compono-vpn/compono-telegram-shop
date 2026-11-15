from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager, ShowMode, StartMode
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.bot.routers.subscription.handlers import CURRENT_DURATION_KEY
from src.bot.states import Subscription
from src.core.constants import PAYMENT_NUDGE_PREFIX
from src.core.enums import PurchaseType, TransactionStatus
from src.core.utils.adapter import DialogDataAdapter
from src.core.utils.formatters import format_user_log as log
from src.infrastructure.billing import BillingClient
from src.infrastructure.billing.converters import billing_plan_to_dto
from src.models.dto import UserDto

router = Router(name=__name__)


@inject
@router.callback_query(F.data.startswith(PAYMENT_NUDGE_PREFIX))
async def on_payment_nudge_other(
    callback: CallbackQuery,
    user: UserDto,
    dialog_manager: DialogManager,
    billing: FromDishka[BillingClient],
) -> None:
    raw = (callback.data or "").removeprefix(PAYMENT_NUDGE_PREFIX)
    try:
        payment_id = UUID(raw)
    except ValueError:
        logger.warning(f"{log(user)} Malformed payment nudge callback '{callback.data}'")
        await callback.answer()
        return

    transaction = await billing.get_transaction(payment_id)
    if not transaction or transaction.UserTelegramID != user.telegram_id:
        await callback.answer()
        return
    if transaction.Status == TransactionStatus.COMPLETED.value:
        await callback.answer()
        return

    plan_id = transaction.Plan.id if transaction.Plan else 0
    billing_plan = await billing.get_plan(plan_id) if plan_id else None
    if not billing_plan or not transaction.Plan:
        await callback.answer()
        return

    purchase_type = PurchaseType(transaction.PurchaseType or PurchaseType.NEW.value)
    await dialog_manager.start(
        Subscription.PAYMENT_METHOD,
        mode=StartMode.RESET_STACK,
        show_mode=ShowMode.NO_UPDATE,
    )
    dialog_manager.show_mode = ShowMode.DELETE_AND_SEND
    seed = DialogDataAdapter(dialog_manager).save(billing_plan_to_dto(billing_plan))
    await dialog_manager.update(
        {
            "plandto": seed,
            CURRENT_DURATION_KEY: transaction.Plan.duration,
            "purchase_type": purchase_type,
            "only_single_plan": False,
            "only_single_duration": False,
        }
    )
    logger.info(f"{log(user)} Reopened the payment methods from the payment nudge")
    await callback.answer()
