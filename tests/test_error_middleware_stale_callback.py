from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import AnswerCallbackQuery
from aiogram.types import CallbackQuery, Chat, ErrorEvent, Message, Update
from aiogram.types import User as TgUser

from src.bot.middlewares import error as error_module
from src.bot.middlewares.error import ErrorMiddleware, is_stale_callback_error
from src.core.constants import CONTAINER_KEY

TELEGRAM_ID = 730166164
STALE_TEXT = (
    "Telegram server says - Bad Request: query is too old and response timeout expired "
    "or query ID is invalid"
)


def _bad_request(message: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=AnswerCallbackQuery(callback_query_id="1"), message=message)


def _error_event(exc: Exception) -> ErrorEvent:
    user = TgUser(id=TELEGRAM_ID, is_bot=False, first_name="Vitaliy")
    callback = CallbackQuery(
        id="cb-1",
        from_user=user,
        chat_instance="ci",
        data="cancel_survey:x:WILL_THINK",
        message=Message(
            message_id=1,
            date=datetime.now(timezone.utc),
            chat=Chat(id=TELEGRAM_ID, type="private"),
            text="survey",
        ),
    )
    return ErrorEvent(update=Update(update_id=839206884, callback_query=callback), exception=exc)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (_bad_request(STALE_TEXT), True),
        (_bad_request("Bad Request: query ID is invalid"), True),
        (_bad_request("Bad Request: message is not modified"), False),
        (
            TelegramForbiddenError(
                method=AnswerCallbackQuery(callback_query_id="1"), message="query is too old"
            ),
            False,
        ),
        (RuntimeError("query is too old"), False),
    ],
)
def test_is_stale_callback_error(exc: Exception, expected: bool) -> None:
    assert is_stale_callback_error(exc) is expected


@pytest.mark.asyncio
async def test_stale_callback_skips_alert_and_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    redirect = MagicMock()
    redirect.kiq = AsyncMock()
    monkeypatch.setattr(error_module, "redirect_to_main_menu_task", redirect)
    container = MagicMock()
    container.get = AsyncMock()
    handler = AsyncMock()

    result = await ErrorMiddleware().middleware_logic(
        handler, _error_event(_bad_request(STALE_TEXT)), {CONTAINER_KEY: container}
    )

    assert result is None
    handler.assert_not_awaited()
    container.get.assert_not_awaited()
    redirect.kiq.assert_not_awaited()


@pytest.mark.asyncio
async def test_other_bad_request_still_alerts(monkeypatch: pytest.MonkeyPatch) -> None:
    redirect = MagicMock()
    redirect.kiq = AsyncMock()
    monkeypatch.setattr(error_module, "redirect_to_main_menu_task", redirect)
    notification_service = MagicMock()
    notification_service.error_notify = AsyncMock()
    container = MagicMock()
    container.get = AsyncMock(return_value=notification_service)

    await ErrorMiddleware().middleware_logic(
        AsyncMock(),
        _error_event(_bad_request("Bad Request: chat not found")),
        {CONTAINER_KEY: container},
    )

    notification_service.error_notify.assert_awaited_once()
