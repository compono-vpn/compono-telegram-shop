from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from fluentogram import TranslatorRunner
from loguru import logger

from src.bot.routers.extra.checkout_entry import open_checkout
from src.bot.states import Subscription
from src.core.constants import RECOVERY_OFFER_PREFIX
from src.core.enums import PurchaseType
from src.core.metrics import RECOVERY_OFFER_ACCEPTED_TOTAL
from src.core.utils.formatters import format_user_log as log
from src.infrastructure.billing import BillingClient
from src.infrastructure.billing.converters import billing_plan_to_dto
from src.models.dto import PlanDto, UserDto
from src.services.recovery_offer import OfferActivation, activate_offer, offer_payment_id

router = Router(name=__name__)


async def _abandoned_plan(
    billing: BillingClient, user: UserDto, payment_id: str
) -> tuple[PlanDto | None, PurchaseType]:
    try:
        transaction = await billing.get_transaction(UUID(payment_id))
    except ValueError:
        return None, PurchaseType.NEW
    if not transaction or transaction.UserTelegramID != user.telegram_id or not transaction.Plan:
        return None, PurchaseType.NEW
    billing_plan = await billing.get_plan(transaction.Plan.id) if transaction.Plan.id else None
    if not billing_plan:
        return None, PurchaseType.NEW
    purchase_type = PurchaseType(transaction.PurchaseType or PurchaseType.NEW.value)
    return billing_plan_to_dto(billing_plan), purchase_type


@inject
@router.callback_query(F.data.startswith(RECOVERY_OFFER_PREFIX))
async def on_recovery_offer_accept(
    callback: CallbackQuery,
    user: UserDto,
    dialog_manager: DialogManager,
    billing: FromDishka[BillingClient],
    i18n: FromDishka[TranslatorRunner],
) -> None:
    payment_id = offer_payment_id((callback.data or "").removeprefix(RECOVERY_OFFER_PREFIX))

    activation = await activate_offer(billing, user.telegram_id)
    if activation is OfferActivation.UNAVAILABLE:
        if isinstance(callback.message, Message):
            await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer(text=i18n.get("msg-recovery-offer-unavailable"), show_alert=True)
        return
    if activation is OfferActivation.FAILED:
        await callback.answer(text=i18n.get("msg-recovery-offer-failed"), show_alert=True)
        return

    source = "payment" if payment_id else "trial_expired"
    RECOVERY_OFFER_ACCEPTED_TOTAL.labels(source=source).inc()
    logger.info(f"{log(user)} Accepted the 30% first-month offer ({source})")

    plan, purchase_type = None, PurchaseType.NEW
    if payment_id:
        plan, purchase_type = await _abandoned_plan(billing, user, payment_id)

    if plan is not None:
        await open_checkout(
            dialog_manager,
            state=Subscription.DURATION,
            purchase_type=purchase_type,
            plan=plan,
        )
    else:
        await open_checkout(
            dialog_manager, state=Subscription.PLANS, purchase_type=PurchaseType.NEW
        )
    await callback.answer()
