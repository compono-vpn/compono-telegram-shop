"""Tests for the FastAPI lifespan shutdown path.

Covers the BDT-409 hazard: normal pod shutdown called
`webhook_service.delete()` unconditionally. With RollingUpdate / >1 replica
/ BOT_RESET_WEBHOOK=true, the shared Telegram webhook (one per bot token,
not per pod) got deleted every time a single pod exited, turning a routine
deploy or scale-down into a webhook outage for every other still-running
replica.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from src.core.config.app import AppConfig
from src.lifespan import lifespan
from src.services.command import CommandService
from src.services.notification import NotificationService
from src.services.remnawave import RemnawaveService
from src.services.settings import SettingsService
from src.services.webhook import WebhookService


def _make_app():
    config = MagicMock()
    webhook_service = AsyncMock()
    webhook_service.has_error = MagicMock(return_value=False)
    command_service = AsyncMock()
    settings_service = AsyncMock()
    settings_service.get.return_value = MagicMock(
        access_mode="OPEN", purchases_allowed=True, registration_allowed=True
    )
    remnawave_service = AsyncMock()
    notification_service = AsyncMock()

    request_container = MagicMock()

    async def get(cls):
        return {
            AppConfig: config,
            WebhookService: webhook_service,
            CommandService: command_service,
            SettingsService: settings_service,
            RemnawaveService: remnawave_service,
            NotificationService: notification_service,
        }[cls]

    request_container.get = AsyncMock(side_effect=get)
    request_container.close = AsyncMock()

    @asynccontextmanager
    async def scoped(scope=None):
        yield request_container

    container = MagicMock(side_effect=scoped)
    container.close = AsyncMock()

    bot = AsyncMock()
    bot_info = MagicMock(
        can_join_groups=True, can_read_all_group_messages=False, supports_inline_queries=True
    )
    bot.get_me.return_value = bot_info

    async def container_get(cls):
        return bot

    container.get = AsyncMock(side_effect=container_get)

    dispatcher = MagicMock()
    dispatcher.resolve_used_update_types.return_value = ["message"]

    telegram_webhook_endpoint = AsyncMock()

    app = MagicMock()
    app.state = SimpleNamespace(
        dispatcher=dispatcher,
        telegram_webhook_endpoint=telegram_webhook_endpoint,
        dishka_container=container,
    )

    return app, webhook_service, command_service, telegram_webhook_endpoint


class TestLifespanShutdown:
    async def test_normal_shutdown_does_not_delete_webhook(self):
        app, webhook_service, command_service, telegram_webhook_endpoint = _make_app()

        async with lifespan(app):
            pass

        webhook_service.delete.assert_not_awaited()
        webhook_service.setup.assert_awaited_once()
        telegram_webhook_endpoint.shutdown.assert_awaited_once()
        command_service.delete.assert_awaited_once()

    async def test_startup_still_sets_up_webhook(self):
        app, webhook_service, *_ = _make_app()

        async with lifespan(app):
            assert app.state.ready is True

        webhook_service.setup.assert_awaited_once()
