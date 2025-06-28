from typing import Any, Awaitable, Callable, Optional, Union

from aiogram.types import CallbackQuery, ErrorEvent, Message
from fluent.runtime import FluentLocalization

from app.core.constants import I18N_FORMATTER_KEY, USER_KEY
from app.core.enums import Locale, MiddlewareEventType
from app.core.formatters import format_log_user
from app.db.models import UserDto

from .base import EventTypedMiddleware

I18nFormatter = Callable[[str, Optional[dict[str, Any]]], str]


class I18nMiddleware(EventTypedMiddleware):
    __event_types__ = [
        MiddlewareEventType.MESSAGE,
        MiddlewareEventType.CALLBACK_QUERY,
        MiddlewareEventType.ERROR,
    ]

    def __init__(
        self,
        locales: dict[Locale, FluentLocalization],
        default_locale: Locale,
    ) -> None:
        super().__init__()
        self.locales = locales
        self.default_locale = default_locale
        self.logger.debug(f"Available locales: {list(locales.keys())}")

    async def __call__(
        self,
        handler: Callable[
            [Union[Message, CallbackQuery, ErrorEvent], dict[str, Any]],
            Awaitable[Any],
        ],
        event: Union[Message, CallbackQuery, ErrorEvent],
        data: dict[str, Any],
    ) -> Any:
        user: Optional[UserDto] = data.get(USER_KEY)
        data[I18N_FORMATTER_KEY] = self.get_formatter(user)
        return await handler(event, data)

    def get_locale(self, user: Optional[UserDto] = None) -> FluentLocalization:
        if user is None:
            self.logger.debug(f"User not provided. Using default locale: '{self.default_locale}'")
            return self.locales[self.default_locale]

        if user.language not in self.locales:
            self.logger.warning(
                f"Locale '{user.language}' not supported."
                f"Using default locale: '{self.default_locale}'"
            )
            return self.locales[self.default_locale]

        # self.logger.debug(f"{format_log_user(user)} Using locale: '{user.language}'")
        return self.locales[user.language]

    def get_formatter(self, user: Optional[UserDto] = None) -> I18nFormatter:
        return self.get_locale(user).format_value
