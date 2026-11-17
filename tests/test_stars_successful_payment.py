"""successful_payment: Telegram has already taken the stars, so billing must complete the payment.

Since the bot sells only for Stars, this handler is the one place a paid order becomes a
subscription. Before, one failed billing call (a pod restart, a timeout) lost the order: the stars
were gone, nothing was granted and nothing retried. And when billing had already cancelled the
payment (its 30-minute timeout racing the user's tap), handle-free answered 200 and skipped it
silently, so the stars were also gone.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.routers.extra import payment as payment_router
from src.bot.routers.extra.payment import on_successful_payment
from src.infrastructure.billing.client import BillingClientError
from tests.conftest import make_user

pytestmark = pytest.mark.asyncio

UID = 555
PAYMENT_ID = "6f1c1f0e-8a0b-4a43-9a51-2a3c2f6d9b11"
CHARGE_ID = "stxCHARGE"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(payment_router, "HANDLE_FREE_RETRY_DELAYS", (0, 0), raising=False)


def _message() -> MagicMock:
    message = MagicMock()
    message.successful_payment = MagicMock(
        invoice_payload=PAYMENT_ID, telegram_payment_charge_id=CHARGE_ID, total_amount=119
    )
    message.answer = AsyncMock()
    return message


def _tx(status: str) -> MagicMock:
    tx = MagicMock()
    tx.Status = status
    tx.UserTelegramID = UID
    return tx


async def _run(billing: AsyncMock, *, dev: bool = False) -> tuple[MagicMock, MagicMock]:
    bot = MagicMock()
    bot.refund_star_payment = AsyncMock()
    message = _message()
    user = make_user(telegram_id=UID)
    if dev:
        user = user.model_copy(update={"role": "DEV"})
    await on_successful_payment(message, user, bot, billing)
    return bot, message


async def test_completed_payment_is_not_refunded():
    billing = AsyncMock()
    billing.get_transaction.return_value = _tx("COMPLETED")
    bot, message = await _run(billing)
    billing.handle_free_payment.assert_awaited_once()
    bot.refund_star_payment.assert_not_awaited()


async def test_transient_billing_error_is_retried():
    billing = AsyncMock()
    billing.handle_free_payment.side_effect = [BillingClientError(503, "unavailable"), None]
    billing.get_transaction.return_value = _tx("COMPLETED")
    bot, _ = await _run(billing)
    assert billing.handle_free_payment.await_count == 2
    bot.refund_star_payment.assert_not_awaited()


async def test_payment_billing_cancelled_meanwhile_is_refunded_and_user_told():
    billing = AsyncMock()
    billing.get_transaction.return_value = _tx("CANCELED")
    bot, message = await _run(billing)
    bot.refund_star_payment.assert_awaited_once_with(
        user_id=UID, telegram_payment_charge_id=CHARGE_ID
    )
    text = message.answer.await_args.args[0]
    assert "вернули" in text


async def test_unknown_payment_is_refunded():
    billing = AsyncMock()
    billing.get_transaction.return_value = None
    bot, _ = await _run(billing)
    bot.refund_star_payment.assert_awaited_once()


async def test_billing_down_raises_for_the_alert_and_does_not_refund():
    billing = AsyncMock()
    billing.handle_free_payment.side_effect = BillingClientError(503, "unavailable")
    billing.get_transaction.side_effect = BillingClientError(503, "unavailable")
    with pytest.raises(BillingClientError):
        await _run(billing)
    assert billing.handle_free_payment.await_count == 3


async def test_dev_payment_is_refunded_only_once():
    billing = AsyncMock()
    billing.get_transaction.return_value = _tx("CANCELED")
    bot, _ = await _run(billing, dev=True)
    bot.refund_star_payment.assert_awaited_once()
