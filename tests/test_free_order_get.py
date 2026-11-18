"""«Получить бесплатно» completes a payment through billing's handle-free, which grants whatever
the payment is for and never checks the amount (compono-billing PaymentUseCase.HandleFreePayment
only queues the completion event). The button is shown only for a 0-star order, but aiogram-dialog
handles a button's callback whether or not its `when` hides it: a press left on an older message or
sent by a modified client on the confirm screen of a paid order would get that order for free.
Since the bot sells for Stars only, handle-free is also the call that completes paid orders, so the
handler must ask billing that the payment really is a free, pending one of this user.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.routers.subscription.handlers import on_get_subscription
from tests.conftest import make_user, unwrap_inject

pytestmark = pytest.mark.asyncio

UID = 777
PAYMENT_ID = "0c7b3a52-1a4c-4bb0-9a5e-1f2a7e2c9d10"


def _tx(final_amount: str, status: str = "PENDING", uid: int = UID) -> MagicMock:
    tx = MagicMock()
    tx.Status = status
    tx.UserTelegramID = uid
    tx.Pricing = MagicMock(final_amount=final_amount)
    return tx


async def _press(tx) -> AsyncMock:
    billing = AsyncMock()
    billing.get_transaction.return_value = tx
    dm = MagicMock()
    dm.middleware_data = {"user": make_user(telegram_id=UID)}
    dm.dialog_data = {"payment_id": PAYMENT_ID}
    await unwrap_inject(on_get_subscription)(AsyncMock(), MagicMock(), dm, billing)
    return billing


async def test_free_pending_order_is_completed():
    billing = await _press(_tx("0"))
    billing.handle_free_payment.assert_awaited_once()


@pytest.mark.parametrize(
    "tx",
    [
        _tx("119"),  # a paid Stars order: hidden button pressed on its confirm screen
        _tx("0", status="CANCELED"),
        _tx("0", uid=UID + 1),
        None,
    ],
)
async def test_order_that_is_not_free_and_pending_is_not_completed(tx):
    billing = await _press(tx)
    billing.handle_free_payment.assert_not_awaited()
