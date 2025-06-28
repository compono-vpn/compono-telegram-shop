from typing import Any, Awaitable, Callable, Optional

from aiogram.types import Message

from app.core.constants import USER_KEY
from app.core.enums import Command, MiddlewareEventType
from app.core.formatters import format_log_user
from app.db.models.dto import UserDto

from .base import EventTypedMiddleware


class GarbageMiddleware(EventTypedMiddleware):
    __event_types__ = [MiddlewareEventType.MESSAGE]

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        user: Optional[UserDto] = data.get(USER_KEY)

        if user is None:
            return

        if user.telegram_id != event.bot.id and event.text != f"/{Command.START.value.command}":
            await event.delete()
            self.logger.debug(f"{format_log_user(user)} Message deleted")

        return await handler(event, data)
