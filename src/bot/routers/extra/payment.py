from uuid import UUID

from aiogram import Bot, F, Router
from aiogram.types import Message, PreCheckoutQuery
from dishka import FromDishka
from loguru import logger

from src.core.enums import TransactionStatus
from src.core.utils.formatters import format_user_log as log
from src.infrastructure.billing import BillingClient
from src.models.dto import UserDto
from src.services.bot_payments import is_bot_payment_gateway

router = Router(name=__name__)


# Shown by Telegram when the invoice can no longer be paid (max 255 characters).
STALE_INVOICE_ERROR = (
    "Этот счёт уже оплачен или устарел. Откройте оплату заново: меню «Подписка» → «Купить»."
)
RETRY_ERROR = "Не получилось проверить счёт. Попробуйте ещё раз через минуту."


@router.pre_checkout_query()
async def on_pre_checkout(
    pre_checkout_query: PreCheckoutQuery,
    user: UserDto,
    billing: FromDishka[BillingClient],
) -> None:
    """Accept only an invoice whose billing payment can still complete.

    A Stars invoice link stays payable after billing cancels its payment (PENDING for 30 minutes)
    and can be paid again after it was paid once. Billing completes only PENDING payments, so such
    a charge would take the stars and grant nothing.
    """
    logger.info(f"{log(user)} Initiated a pre-checkout query")
    try:
        payment_id = UUID(pre_checkout_query.invoice_payload or "")
    except ValueError:
        logger.warning(f"{log(user)} Pre-checkout query rejected: bad payload")
        await pre_checkout_query.answer(ok=False, error_message=STALE_INVOICE_ERROR)
        return

    try:
        transaction = await billing.get_transaction(payment_id)
    except Exception:
        logger.opt(exception=True).warning(
            f"{log(user)} Pre-checkout query for '{payment_id}' rejected: billing lookup failed"
        )
        await pre_checkout_query.answer(ok=False, error_message=RETRY_ERROR)
        return

    reason = None
    if transaction is None:
        reason = "payment not found"
    elif transaction.UserTelegramID != user.telegram_id:
        reason = f"payment belongs to '{transaction.UserTelegramID}'"
    elif not is_bot_payment_gateway(transaction.GatewayType):
        reason = f"gateway '{transaction.GatewayType}' is not Stars"
    elif transaction.Status != TransactionStatus.PENDING.value:
        reason = f"payment is {transaction.Status}"
    if reason:
        logger.warning(f"{log(user)} Pre-checkout query for '{payment_id}' rejected: {reason}")
        await pre_checkout_query.answer(ok=False, error_message=STALE_INVOICE_ERROR)
        return

    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(
    message: Message,
    user: UserDto,
    bot: Bot,
    billing: FromDishka[BillingClient],
) -> None:
    payment = message.successful_payment

    if not payment:
        return

    if user.is_dev:
        logger.info(f"{log(user)} Refunding test payment '{payment.telegram_payment_charge_id}'")
        await bot.refund_star_payment(
            user_id=user.telegram_id,
            telegram_payment_charge_id=payment.telegram_payment_charge_id,
        )

    await billing.handle_free_payment(payment_id=UUID(payment.invoice_payload))
