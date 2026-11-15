"""The nudge button works through the real aiogram-dialog stack: one message, seeded state."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import EditMessageText, SendMessage, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update
from aiogram.types import User as TgUser
from aiogram_dialog import Dialog, Window, setup_dialogs
from aiogram_dialog.widgets.text import Format
from dishka import Provider, Scope, make_async_container, provide
from dishka.integrations.aiogram import AiogramProvider, inject_router, setup_dishka

from src.bot.routers.extra import payment_nudge
from src.bot.states import Subscription
from src.core.constants import PAYMENT_NUDGE_PREFIX
from src.infrastructure.billing import BillingClient
from src.infrastructure.billing.models import BillingPlan, BillingPlanDuration
from tests.conftest import make_user

TG = 1903024824


class Session(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []
        self._next_id = 100

    async def close(self) -> None:
        return None

    async def stream_content(self, *args: Any, **kwargs: Any):
        raise NotImplementedError
        yield b""

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: Any = None) -> Any:
        self.calls.append(method)
        if isinstance(method, (SendMessage, EditMessageText)):
            self._next_id += 1
            return Message(
                message_id=getattr(method, "message_id", None) or self._next_id,
                date=datetime.now(timezone.utc),
                chat=Chat(id=TG, type="private"),
                text=method.text,
                reply_markup=method.reply_markup,
            )
        return True


async def _method_list_data(dialog_manager: Any, **kwargs: Any) -> dict[str, Any]:
    data = dialog_manager.dialog_data
    return {
        "plan": data["plandto"]["name"],
        "days": data["selected_duration"],
        "purchase_type": str(data["purchase_type"]),
    }


@pytest.fixture
async def env():
    session = Session()
    bot = Bot(token="123456:ABC-TEST", session=session)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(
        Dialog(
            Window(
                Format("{plan}|{days}|{purchase_type}"),
                getter=_method_list_data,
                state=Subscription.PAYMENT_METHOD,
            )
        )
    )
    setup_dialogs(dp)
    user = make_user(telegram_id=TG, name="Lisa")

    async def inject_user(handler: Any, event: Any, data: dict[str, Any]) -> Any:
        data["user"] = user
        return await handler(event, data)

    dp.update.outer_middleware(inject_user)
    dp.include_router(payment_nudge.router)

    billing = AsyncMock()
    billing.get_transaction.return_value = MagicMock(
        UserTelegramID=TG,
        Status="PENDING",
        PurchaseType="NEW",
        Plan=MagicMock(id=1, duration=30),
    )
    billing.get_plan.return_value = BillingPlan(
        ID=1, Name="Старт", Type="BOTH", Durations=[BillingPlanDuration(ID=1, Days=30)]
    )

    class Deps(Provider):
        scope = Scope.REQUEST

        @provide
        def billing_client(self) -> BillingClient:
            return billing

    container = make_async_container(Deps(), AiogramProvider())
    setup_dishka(container, dp)
    inject_router(dp)
    yield bot, dp, session
    await container.close()


async def test_button_sends_the_method_screen_once_with_the_payment_seeded(env) -> None:
    bot, dp, session = env
    nudge = Message(
        message_id=55,
        date=datetime.now(timezone.utc),
        chat=Chat(id=TG, type="private"),
        from_user=TgUser(id=1, is_bot=True, first_name="bot"),
        text="nudge",
    )
    callback = CallbackQuery(
        id="cb",
        from_user=TgUser(id=TG, is_bot=False, first_name="Lisa"),
        chat_instance="ci",
        data=f"{PAYMENT_NUDGE_PREFIX}{uuid4()}",
        message=nudge,
    )

    await dp.feed_update(bot, Update(update_id=1, callback_query=callback))
    await asyncio.sleep(0.05)

    sent = [c for c in session.calls if isinstance(c, SendMessage)]
    assert len(sent) == 1
    assert sent[0].text.startswith("Старт|30|")
