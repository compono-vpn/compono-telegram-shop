from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.bot.routers.extra.checkout_entry import open_checkout
from src.bot.states import Subscription
from src.core.constants import PAYMENT_NUDGE_PREFIX
from src.core.enums import PurchaseType, TransactionStatus
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

    await open_checkout(
        dialog_manager,
        state=Subscription.PAYMENT_METHOD,
        purchase_type=PurchaseType(transaction.PurchaseType or PurchaseType.NEW.value),
        plan=billing_plan_to_dto(billing_plan),
        duration_days=transaction.Plan.duration,
    )
    logger.info(f"{log(user)} Reopened the payment methods from the payment nudge")
    await callback.answer()
