"""A rollout must not cut off an update the bot is still handling.

The webhook answers Telegram 200 before handling the update, so Telegram never sends it again. On
shutdown the endpoint used to cancel every update still in progress. For successful_payment that
means: the stars are taken, and if the cancel lands before handle-free reached billing (or before a
refund of a payment billing cancelled), nothing completes the order, nothing gives the stars back
and nobody is told. Since the bot sells only for Stars, every order goes through that handler.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.endpoints import telegram as telegram_endpoint
from src.api.endpoints.telegram import TelegramWebhookEndpoint

pytestmark = pytest.mark.asyncio


def _endpoint() -> TelegramWebhookEndpoint:
    dispatcher = MagicMock()
    dispatcher.workflow_data = {}
    dispatcher.emit_shutdown = AsyncMock()
    return TelegramWebhookEndpoint(dispatcher, "secret")


async def test_update_in_progress_finishes_before_shutdown():
    endpoint = _endpoint()
    finished = asyncio.Event()

    async def handle() -> None:
        await asyncio.sleep(0.2)
        finished.set()

    task = asyncio.create_task(handle())
    endpoint._feed_update_tasks.add(task)
    task.add_done_callback(endpoint._feed_update_tasks.discard)

    await endpoint.shutdown()
    assert finished.is_set()
    endpoint.dispatcher.emit_shutdown.assert_awaited_once()


async def test_update_still_running_after_the_drain_time_is_cancelled(monkeypatch):
    monkeypatch.setattr(telegram_endpoint, "SHUTDOWN_DRAIN_SECONDS", 0.05)
    endpoint = _endpoint()
    task = asyncio.create_task(asyncio.sleep(30))
    endpoint._feed_update_tasks.add(task)

    await endpoint.shutdown()
    assert task.cancelled()
