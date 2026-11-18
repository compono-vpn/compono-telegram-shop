"""A successful_payment must pass every gate middleware: the stars are already taken.

Throttling (0.5 s per user), access mode (blocked user, RESTRICTED, purchases off), rules and the
required channel each used to drop it silently: no handle-free, no refund, no alert.
"""

import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Chat, Message, SuccessfulPayment, User

from src.bot.middlewares.access import AccessMiddleware
from src.bot.middlewares.channel import ChannelMiddleware
from src.bot.middlewares.rules import RulesMiddleware
from src.bot.middlewares.throttling import ThrottlingMiddleware
from src.core.constants import CONTAINER_KEY, USER_KEY
from src.services.access import AccessService
from src.services.notification import NotificationService
from src.services.settings import SettingsService

UID = 555001


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
            invoice_payload="ad1fd163-4e72-43fc-9346-eb4893757c90",
            telegram_payment_charge_id="stx-1",
            provider_payment_charge_id="",
        )
    )


def _data() -> dict[str, Any]:
    access = MagicMock(spec=AccessService)
    access.is_access_allowed = AsyncMock(return_value=False)  # blocked user / RESTRICTED mode
    settings = MagicMock(spec=SettingsService)
    settings.is_rules_required = AsyncMock(return_value=True)
    settings.is_channel_required = AsyncMock(return_value=True)
    settings.get = AsyncMock(side_effect=AssertionError("gate ran on a payment"))
    services = {
        AccessService: access,
        SettingsService: settings,
        NotificationService: MagicMock(spec=NotificationService, notify_user=AsyncMock()),
    }
    config = MagicMock()
    config.bot.channel_address = None

    async def get(kind: Any) -> Any:
        from src.core.config import AppConfig

        return config if kind is AppConfig else services[kind]

    container = MagicMock()
    container.get = get
    user = MagicMock(telegram_id=UID, is_rules_accepted=False, is_privileged=False)
    return {CONTAINER_KEY: container, USER_KEY: user}


def _throttled() -> ThrottlingMiddleware:
    middleware = ThrottlingMiddleware()
    middleware.cache[UID] = None  # the user tapped something a moment ago
    return middleware


GATES = [
    pytest.param(_throttled, id="throttling"),
    pytest.param(AccessMiddleware, id="access"),
    pytest.param(RulesMiddleware, id="rules"),
    pytest.param(ChannelMiddleware, id="channel"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("make", GATES)
async def test_gate_lets_a_successful_payment_through(make: Any) -> None:
    handler = AsyncMock(return_value="handled")
    assert await make()(handler, _payment(), _data()) == "handled"
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_throttling_still_drops_an_ordinary_message() -> None:
    handler = AsyncMock()
    await _throttled()(handler, _message(text="hi"), _data())
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_access_still_stops_an_ordinary_message_of_a_blocked_user() -> None:
    handler = AsyncMock()
    await AccessMiddleware()(handler, _message(text="hi"), _data())
    handler.assert_not_awaited()
