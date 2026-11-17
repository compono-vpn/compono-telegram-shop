import asyncio
from typing import Any, Optional
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
UNCOMPLETED_PAYMENT_TEXT = (
    "Этот счёт уже был закрыт, поэтому подписку оформить не получилось. Звёзды вернули на ваш "
    "счёт. Откройте оплату заново: меню «Подписка» → «Купить»."
)
# Waits between billing retries after a successful Stars payment (3 attempts in all).
HANDLE_FREE_RETRY_DELAYS = (1, 3)
# handle-free only queues a Kafka event; billing's consumer completes the payment a moment later.
# Waits between reads of the payment status while it is still PENDING (about 20 s in all).
COMPLETION_POLL_DELAYS = (0.5, 1, 1.5, 2, 3, 5, 7)


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

    refunded = False
    if user.is_dev:
        logger.info(f"{log(user)} Refunding test payment '{payment.telegram_payment_charge_id}'")
        await bot.refund_star_payment(
            user_id=user.telegram_id,
            telegram_payment_charge_id=payment.telegram_payment_charge_id,
        )
        refunded = True

    # Telegram has already taken the stars: a failed billing call must not lose the order.
    payment_id = UUID(payment.invoice_payload)
    await _complete_in_billing(billing, payment_id, user)

    # Billing completes only PENDING payments and skips any other one (its 30-minute timeout can
    # cancel the payment between our pre-checkout answer and this message). handle-free completes
    # nothing itself: it queues a Kafka event, so PENDING right after it is normal.
    transaction = await _wait_until_settled(billing, payment_id)
    if transaction is not None and transaction.Status == TransactionStatus.COMPLETED.value:
        return
    if transaction is not None and transaction.Status == TransactionStatus.PENDING.value:
        # Billing is slow, not refusing: the payment can still complete, so the stars stay.
        # Raising sends #EventError so a person checks it.
        raise RuntimeError(
            f"Stars payment '{payment_id}' (charge '{payment.telegram_payment_charge_id}') is "
            f"still PENDING in billing after handle-free; check that it completes"
        )

    status = transaction.Status if transaction else "not found"
    logger.error(
        f"{log(user)} Stars payment '{payment_id}' was charged but billing has it {status}; "
        f"refunding charge '{payment.telegram_payment_charge_id}'"
    )
    if not refunded:
        await bot.refund_star_payment(
            user_id=user.telegram_id,
            telegram_payment_charge_id=payment.telegram_payment_charge_id,
        )
    await message.answer(UNCOMPLETED_PAYMENT_TEXT)


async def _complete_in_billing(billing: BillingClient, payment_id: UUID, user: UserDto) -> None:
    for attempt, delay in enumerate((*HANDLE_FREE_RETRY_DELAYS, None), start=1):
        try:
            await billing.handle_free_payment(payment_id=payment_id)
            return
        except Exception:
            if delay is None:
                raise
            logger.opt(exception=True).warning(
                f"{log(user)} Billing could not complete Stars payment '{payment_id}' "
                f"(attempt {attempt}), retrying in {delay}s"
            )
            await asyncio.sleep(delay)


async def _wait_until_settled(billing: BillingClient, payment_id: UUID) -> Optional[Any]:
    """Read the payment until it leaves PENDING, or give up and return the last read."""
    transaction = await billing.get_transaction(payment_id)
    for delay in COMPLETION_POLL_DELAYS:
        if transaction is None or transaction.Status != TransactionStatus.PENDING.value:
            return transaction
        await asyncio.sleep(delay)
        transaction = await billing.get_transaction(payment_id)
    return transaction
