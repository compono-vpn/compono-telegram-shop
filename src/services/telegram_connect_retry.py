import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from aiogram import Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import Response, TelegramMethod
from aiogram.methods.base import TelegramType
from aiohttp import ClientConnectorError
from loguru import logger

CONNECT_RETRY_DELAYS: tuple[float, ...] = (0.5, 2.0)


def is_connect_failure(error: TelegramNetworkError) -> bool:
    return isinstance(error.__cause__ or error.__context__, ClientConnectorError)


class ConnectRetryMiddleware(BaseRequestMiddleware):
    def __init__(
        self,
        delays: Sequence[float] = CONNECT_RETRY_DELAYS,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        self.delays = tuple(delays)
        self.sleep = sleep

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        for attempt, delay in enumerate(self.delays, start=1):
            try:
                return await make_request(bot, method)
            except TelegramNetworkError as error:
                if not is_connect_failure(error):
                    raise
                logger.warning(
                    f"Could not connect to Telegram for '{type(method).__name__}' "
                    f"(attempt {attempt}), retrying in {delay}s: {error.message}"
                )
                await self.sleep(delay)
        return await make_request(bot, method)
