import logging
from abc import ABC
from typing import ClassVar, Final, Optional, Union

from aiogram import BaseMiddleware, Router
from aiogram.types import CallbackQuery, ErrorEvent, Message
from aiogram.types import User as AiogramUser

from app.core.enums import MiddlewareEventType

DEFAULT_UPDATE_TYPES: Final[list[MiddlewareEventType]] = [
    MiddlewareEventType.MESSAGE,
    MiddlewareEventType.CALLBACK_QUERY,
]


class EventTypedMiddleware(BaseMiddleware, ABC):
    __event_types__: ClassVar[list[MiddlewareEventType]] = DEFAULT_UPDATE_TYPES

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"{self.__class__.__module__}")
        self.logger.debug(f"{self.__class__.__name__} initialized")

    def setup_inner(self, router: Router) -> None:
        for event_type in self.__event_types__:
            router.observers[event_type].middleware(self)

        self.logger.debug(
            f"{self.__class__.__name__} set as inner middleware for: "
            f"{', '.join(t.value for t in self.__event_types__)}"
        )

    def setup_outer(self, router: Router) -> None:
        for event_type in self.__event_types__:
            router.observers[event_type].outer_middleware(self)

        self.logger.debug(
            f"{self.__class__.__name__} set as outer middleware for: "
            f"{', '.join(t.value for t in self.__event_types__)}"
        )

    @staticmethod
    def _get_aiogram_user(
        event: Union[Message, CallbackQuery, ErrorEvent],
    ) -> Optional[AiogramUser]:
        if isinstance(event, Message) or isinstance(event, CallbackQuery):
            return event.from_user
        elif isinstance(event, ErrorEvent):
            if event.update.callback_query:
                return event.update.callback_query.from_user
            elif event.update.message:
                return event.update.message.from_user
        return None
