from typing import Any, Awaitable, Callable, MutableMapping, Optional, Union

from aiogram.dispatcher.flags import get_flag
from aiogram.types import CallbackQuery, Message
from cachetools import TTLCache

from app.core.constants import THROTTLING_KEY, USER_KEY
from app.core.enums import MiddlewareEventType
from app.core.formatters import format_log_user
from app.db.models.dto import UserDto

from .base import EventTypedMiddleware

DEFAULT_KEY = "default"
DEFAULT_TTL = 0.5


class ThrottlingMiddleware(EventTypedMiddleware):
    __event_types__ = [MiddlewareEventType.MESSAGE, MiddlewareEventType.CALLBACK_QUERY]

    def __init__(
        self,
        default_key: str = DEFAULT_KEY,
        default_ttl: float = DEFAULT_TTL,
        ttl_map: Optional[dict[str, float]] = None,
    ) -> None:
        super().__init__()
        ttl_map = ttl_map or {}

        if default_key not in ttl_map:
            ttl_map[default_key] = default_ttl

        self.default_key = default_key
        self.caches: dict[str, MutableMapping[int, None]] = {}

        for name, ttl in ttl_map.items():
            self.caches[name] = TTLCache(maxsize=10_000, ttl=ttl)

    async def __call__(
        self,
        handler: Callable[[Union[Message, CallbackQuery], dict[str, Any]], Awaitable[Any]],
        event: Union[Message, CallbackQuery],
        data: dict[str, Any],
    ) -> Any:
        user: Optional[UserDto] = data.get(USER_KEY)

        if user is None:
            return

        key = get_flag(handler=data, name=THROTTLING_KEY, default=self.default_key)
        cache = self.caches.get(key, self.caches[DEFAULT_KEY])

        if user.telegram_id in cache:
            self.logger.warning(f"{format_log_user(user)} Throttled")
            return

        cache[user.telegram_id] = None
        return await handler(event, data)
