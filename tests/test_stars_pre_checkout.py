"""pre_checkout_query must refuse an invoice whose billing payment can no longer be completed.

A Telegram Stars invoice link stays payable after billing cancels the payment (billing cancels
PENDING payments after 30 minutes) and can be paid again after it was paid once. Billing only moves
PENDING -> COMPLETED, so paying such a link would take the user's stars and grant nothing. Since the
bot sells only for Stars, the pre-checkout answer is the one place to stop that.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.bot.routers.extra.payment import on_pre_checkout
from tests.conftest import make_user
from tests.test_stars_successful_payment import FakeRedis

pytestmark = pytest.mark.asyncio

UID = 555


def _query(payload: str, amount: int = 119) -> MagicMock:
    query = MagicMock()
    query.invoice_payload = payload
    query.total_amount = amount
    query.currency = "XTR"
    query.answer = AsyncMock()
    return query


def _tx(status: str = "PENDING", uid: int = UID, gateway: str = "TELEGRAM_STARS") -> MagicMock:
    tx = MagicMock()
    tx.Status = status
    tx.UserTelegramID = uid
    tx.GatewayType = gateway
    tx.Pricing = MagicMock(final_amount="119")
    return tx


async def _answer(tx, payload: str | None = None, redis=None) -> tuple[bool, MagicMock]:
    billing = AsyncMock()
    if isinstance(tx, Exception):
        billing.get_transaction.side_effect = tx
    else:
        billing.get_transaction.return_value = tx
    query = _query(payload if payload is not None else str(uuid4()))
    await on_pre_checkout(query, make_user(telegram_id=UID), billing, redis or FakeRedis())
    kwargs = query.answer.await_args.kwargs
    return kwargs["ok"], query


async def test_pending_stars_payment_of_this_user_is_accepted():
    ok, _ = await _answer(_tx())
    assert ok is True


@pytest.mark.parametrize("status", ["CANCELED", "COMPLETED", "REFUNDED", "FAILED"])
async def test_payment_that_cannot_complete_is_refused(status):
    ok, query = await _answer(_tx(status=status))
    assert ok is False
    assert query.answer.await_args.kwargs.get("error_message")


async def test_unknown_payment_is_refused():
    ok, _ = await _answer(None)
    assert ok is False


async def test_payment_of_another_user_is_refused():
    ok, _ = await _answer(_tx(uid=UID + 1))
    assert ok is False


async def test_non_stars_payment_is_refused():
    ok, _ = await _answer(_tx(gateway="PLATEGA"))
    assert ok is False


async def test_billing_error_refuses_instead_of_taking_stars():
    ok, _ = await _answer(RuntimeError("billing down"))
    assert ok is False


async def test_malformed_or_empty_payload_is_refused():
    ok, _ = await _answer(_tx(), payload="not-a-uuid")
    assert ok is False
    ok, _ = await _answer(_tx(), payload="")
    assert ok is False


async def test_invoice_already_charged_once_is_refused_while_billing_completes_it():
    # Billing's Kafka consumer can lag: the payment is still PENDING after the user paid, and the
    # confirm screen still shows the same invoice link. A second payment would be a second charge.
    payload = str(uuid4())
    redis = FakeRedis({f"stars_charge:{payload}": b"stxFIRST"})
    ok, query = await _answer(_tx(), payload=payload, redis=redis)
    assert ok is False
    assert query.answer.await_args.kwargs.get("error_message")


async def test_redis_down_does_not_block_a_payment():
    ok, _ = await _answer(_tx(), redis=FakeRedis(fail=True))
    assert ok is True
