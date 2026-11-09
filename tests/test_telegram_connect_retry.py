from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import SendMessage
from aiohttp import ClientConnectorError, ServerDisconnectedError
from pydantic import SecretStr

from src.infrastructure.di.providers.bot import BotProvider
from src.services.telegram_connect_retry import ConnectRetryMiddleware, is_connect_failure

METHOD = SendMessage(chat_id=12345, text="test")


def _network_error(cause: BaseException | None) -> TelegramNetworkError:
    try:
        try:
            if cause is None:
                raise TimeoutError
            raise cause
        except BaseException:
            raise TelegramNetworkError(method=METHOD, message="boom")
    except TelegramNetworkError as error:
        return error


def _connect_reset() -> ClientConnectorError:
    key = SimpleNamespace(host="api.telegram.org", port=443, ssl=True, is_ssl=True)
    return ClientConnectorError(key, ConnectionResetError(104, "Connection reset by peer"))


def test_only_a_failed_connect_counts_as_safe_to_retry():
    assert is_connect_failure(_network_error(_connect_reset()))
    assert not is_connect_failure(_network_error(None))
    assert not is_connect_failure(_network_error(ServerDisconnectedError()))


async def test_failed_connect_is_retried_until_the_request_goes_through():
    make_request = AsyncMock(side_effect=[_network_error(_connect_reset()), "sent"])
    sleep = AsyncMock()
    middleware = ConnectRetryMiddleware(delays=(0.5, 2.0), sleep=sleep)
    assert await middleware(make_request, object(), METHOD) == "sent"
    assert make_request.await_count == 2
    sleep.assert_awaited_once_with(0.5)


async def test_request_that_may_have_reached_telegram_is_not_repeated():
    make_request = AsyncMock(side_effect=_network_error(None))
    sleep = AsyncMock()
    middleware = ConnectRetryMiddleware(delays=(0.5, 2.0), sleep=sleep)
    with pytest.raises(TelegramNetworkError):
        await middleware(make_request, object(), METHOD)
    assert make_request.await_count == 1
    sleep.assert_not_awaited()


async def test_error_surfaces_after_the_last_attempt():
    make_request = AsyncMock(side_effect=[_network_error(_connect_reset()) for _ in range(3)])
    sleep = AsyncMock()
    middleware = ConnectRetryMiddleware(delays=(0.5, 2.0), sleep=sleep)
    with pytest.raises(TelegramNetworkError):
        await middleware(make_request, object(), METHOD)
    assert make_request.await_count == 3
    assert [call.args[0] for call in sleep.await_args_list] == [0.5, 2.0]


async def test_bot_provider_installs_the_retry():
    config = SimpleNamespace(bot=SimpleNamespace(api_server=None, token=SecretStr("1:test")))
    provider = BotProvider()
    bots = provider.get_bot.dependency_sources[0].source(config)
    bot = await bots.__anext__()
    try:
        assert any(isinstance(m, ConnectRetryMiddleware) for m in bot.session.middleware)
    finally:
        await bots.aclose()
