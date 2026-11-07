from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageReplyMarkup,
    EditMessageText,
    SendMessage,
    TelegramMethod,
)
from aiogram.types import CallbackQuery, Chat, Message, Update
from aiogram.types import User as TgUser
from aiogram_dialog import BgManagerFactory, Dialog, ShowMode, StartMode, Window, setup_dialogs
from aiogram_dialog.widgets.kbd import Button
from aiogram_dialog.widgets.text import Const
from dishka import Provider, Scope, make_async_container, provide
from dishka.integrations.aiogram import AiogramProvider, inject_router, setup_dishka

from src.bot.routers import setup_error_handlers
from src.bot.states import MainMenu
from src.services.notification import NotificationService
from tests.conftest import make_user

TELEGRAM_ID = 1903024824


class RecordingSession(BaseSession):
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
                chat=Chat(id=TELEGRAM_ID, type="private"),
                text=method.text,
                reply_markup=method.reply_markup,
            )
        return True

    def of(self, kind: type) -> list[Any]:
        return [c for c in self.calls if isinstance(c, kind)]


class Harness:
    def __init__(self) -> None:
        self.session = RecordingSession()
        self.bot = Bot(token="123456:ABC-TEST", session=self.session)
        self.storage = MemoryStorage()
        self.dp = Dispatcher(storage=self.storage)
        self.notifications = AsyncMock(spec=NotificationService)
        self.menu_presses = 0

        async def on_press(callback: Any, button: Any, manager: Any) -> None:
            self.menu_presses += 1

        dialog = Dialog(
            Window(
                Const("menu"),
                Button(Const("go"), id="go", on_click=on_press),
                state=MainMenu.MAIN,
            )
        )
        self.dp.include_router(dialog)
        self.bg_factory: BgManagerFactory = setup_dialogs(self.dp)

        user = make_user(telegram_id=TELEGRAM_ID, name="Lisa")

        async def inject_user(handler: Any, event: Any, data: dict[str, Any]) -> Any:
            data["user"] = user
            return await handler(event, data)

        self.dp.update.outer_middleware(inject_user)
        setup_error_handlers(self.dp)

        harness = self

        class Deps(Provider):
            scope = Scope.REQUEST

            @provide
            def notifications(self) -> NotificationService:
                return harness.notifications

            @provide
            def bg(self) -> BgManagerFactory:
                return harness.bg_factory

        self.container = make_async_container(Deps(), AiogramProvider())
        setup_dishka(self.container, self.dp)
        inject_router(self.dp)

    def bg(self):
        return self.bg_factory.bg(bot=self.bot, user_id=TELEGRAM_ID, chat_id=TELEGRAM_ID)

    async def settle(self) -> None:
        for _ in range(5):
            await asyncio.sleep(0.02)

    async def start_menu(self, mode: StartMode = StartMode.RESET_STACK) -> str:
        await self.bg().start(MainMenu.MAIN, mode=mode, show_mode=ShowMode.SEND)
        await self.settle()
        return self.session.of(SendMessage)[-1].reply_markup.inline_keyboard[0][0].callback_data

    async def press(self, callback_data: str, message_id: int = 101) -> None:
        tg_user = TgUser(id=TELEGRAM_ID, is_bot=False, first_name="Lisa")
        message = Message(
            message_id=message_id,
            date=datetime.now(timezone.utc),
            chat=Chat(id=TELEGRAM_ID, type="private"),
            from_user=TgUser(id=1, is_bot=True, first_name="bot"),
            text="menu",
        )
        callback = CallbackQuery(
            id="cb1",
            from_user=tg_user,
            chat_instance="ci",
            data=callback_data,
            message=message,
        )
        await self.dp.feed_update(self.bot, Update(update_id=1, callback_query=callback))
        await self.settle()

    async def close(self) -> None:
        await self.container.close()


@pytest.fixture
async def harness():
    h = Harness()
    yield h
    await h.close()


async def test_press_on_menu_with_live_context_still_works(harness: Harness) -> None:
    data = await harness.start_menu()

    await harness.press(data)

    assert harness.menu_presses == 1
    harness.notifications.notify_user.assert_not_awaited()


async def test_press_after_stack_reset_recovers_into_fresh_menu(harness: Harness) -> None:
    old_data = await harness.start_menu()
    await harness.start_menu(StartMode.RESET_STACK)
    sent_before = len(harness.session.of(SendMessage))
    stripped_before = len(harness.session.of(EditMessageReplyMarkup))

    await harness.press(old_data)

    assert harness.menu_presses == 0
    assert len(harness.session.of(AnswerCallbackQuery)) == 1
    stripped = harness.session.of(EditMessageReplyMarkup)
    assert len(stripped) == stripped_before + 1
    assert stripped[-1].reply_markup is None and stripped[-1].message_id == 101
    sent = harness.session.of(SendMessage)
    assert len(sent) == sent_before + 1
    assert sent[-1].text == "menu"
    payload = harness.notifications.notify_user.await_args.kwargs["payload"]
    assert payload.i18n_key == "ntf-menu-refreshed"


async def test_press_after_storage_loss_recovers_and_new_menu_works(harness: Harness) -> None:
    old_data = await harness.start_menu()
    harness.storage.storage.clear()

    await harness.press(old_data)

    assert harness.menu_presses == 0
    new_data = harness.session.of(SendMessage)[-1].reply_markup.inline_keyboard[0][0].callback_data
    assert new_data != old_data

    await harness.press(new_data, message_id=102)

    assert harness.menu_presses == 1


async def test_failed_restart_keeps_the_error_notice(harness: Harness) -> None:
    old_data = await harness.start_menu()
    harness.storage.storage.clear()
    failing = AsyncMock()
    failing.bg.side_effect = RuntimeError("boom")
    harness.bg_factory = failing

    await harness.press(old_data)

    payload = harness.notifications.notify_user.await_args.kwargs["payload"]
    assert payload.i18n_key == "ntf-error-lost-context"


def test_recovery_notice_keys_exist_in_ru_bundle() -> None:
    bundle = Path("assets/translations/ru/notifications.ftl").read_text(encoding="utf-8")

    assert "ntf-menu-refreshed = <i>Меню обновлено</i>" in bundle
    assert "ntf-error-lost-context =" in bundle
