"""A successful_payment must survive a short billing outage while the user is loaded.

UserMiddleware reads the user from billing before any handler runs. When that failed, the payment
handler (with its own billing retries and a named alert) never ran: the stars stayed taken, the
order never reached billing and the #EventError named no payment.
"""

import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Chat, Message, SuccessfulPayment, User

from src.bot.middlewares.user import UserMiddleware
from src.core.config import AppConfig
from src.core.constants import CONTAINER_KEY, USER_KEY
from src.infrastructure.billing import BillingClient
from src.infrastructure.billing.client import BillingClientError
from src.services.notification import NotificationService
from src.services.referral import ReferralService
from src.services.user import UserService

UID = 555002
PAYMENT_ID = "ad1fd163-4e72-43fc-9346-eb4893757c91"
CHARGE_ID = "stx-blip"


def _message(**extra: Any) -> Message:
    return Message(
        message_id=1,
        date=datetime.datetime.now(),
        chat=Chat(id=UID, type="private"),
        from_user=User(id=UID, is_bot=False, first_name="U"),
        **extra,
    )


def _payment() -> Message:
    return _message(
        successful_payment=SuccessfulPayment(
            currency="XTR",
            total_amount=119,
            invoice_payload=PAYMENT_ID,
            telegram_payment_charge_id=CHARGE_ID,
            provider_payment_charge_id="",
        )
    )


def _data(get: AsyncMock) -> dict[str, Any]:
    user_service = MagicMock(spec=UserService)
    user_service.get = get
    user_service.compare_and_update = AsyncMock()
    user_service.update_recent_activity = AsyncMock()
    billing = MagicMock(spec=BillingClient)
    billing.get_current_subscription = AsyncMock(return_value=None)
    config = MagicMock()
    config.bot.dev_id = 1
    services = {
        UserService: user_service,
        BillingClient: billing,
        AppConfig: config,
        NotificationService: MagicMock(spec=NotificationService),
        ReferralService: MagicMock(spec=ReferralService),
    }

    async def container_get(kind: Any) -> Any:
        return services[kind]

    container = MagicMock()
    container.get = container_get
    return {CONTAINER_KEY: container}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("asyncio.sleep", AsyncMock())


def _user() -> MagicMock:
    return MagicMock(telegram_id=UID)


@pytest.mark.asyncio
async def test_payment_waits_out_a_short_billing_outage() -> None:
    down = BillingClientError(0, "connection refused")
    get = AsyncMock(side_effect=[down, down, _user()])
    data = _data(get)
    handler = AsyncMock(return_value="handled")
    assert await UserMiddleware()(handler, _payment(), data) == "handled"
    handler.assert_awaited_once()
    assert data[USER_KEY].telegram_id == UID


@pytest.mark.asyncio
async def test_payment_alert_names_the_payment_when_billing_stays_down() -> None:
    get = AsyncMock(side_effect=BillingClientError(0, "connection refused"))
    handler = AsyncMock()
    with pytest.raises(RuntimeError) as raised:
        await UserMiddleware()(handler, _payment(), _data(get))
    handler.assert_not_awaited()
    assert PAYMENT_ID in str(raised.value)
    assert CHARGE_ID in str(raised.value)
    assert get.await_count == 3


@pytest.mark.asyncio
async def test_ordinary_message_is_not_retried() -> None:
    get = AsyncMock(side_effect=BillingClientError(0, "connection refused"))
    with pytest.raises(BillingClientError):
        await UserMiddleware()(AsyncMock(), _message(text="hi"), _data(get))
    assert get.await_count == 1
