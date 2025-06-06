import logging
from abc import ABC
from typing import ClassVar, Final

from aiogram import BaseMiddleware, Router

from app.core.enums import MiddlewareEventType

DEFAULT_UPDATE_TYPES: Final[list[MiddlewareEventType]] = [
    MiddlewareEventType.MESSAGE,
    MiddlewareEventType.CALLBACK_QUERY,
]

logger = logging.getLogger(__name__)


class EventTypedMiddleware(BaseMiddleware, ABC):
    __event_types__: ClassVar[list[MiddlewareEventType]] = DEFAULT_UPDATE_TYPES

    def setup_inner(self, router: Router) -> None:
        for event_type in self.__event_types__:
            router.observers[event_type].middleware(self)

        logger.debug(
            f"{self.__class__.__name__} set as inner middleware for: "
            f"{', '.join(t.value for t in self.__event_types__)}"
        )

    def setup_outer(self, router: Router) -> None:
        for event_type in self.__event_types__:
            router.observers[event_type].outer_middleware(self)

        logger.debug(
            f"{self.__class__.__name__} set as outer middleware for: "
            f"{', '.join(t.value for t in self.__event_types__)}"
        )
