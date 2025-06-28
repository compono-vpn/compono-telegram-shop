from typing import Any, Awaitable, Callable, Optional, Union

from aiogram.types import CallbackQuery, Message
from aiogram_dialog.utils import remove_intent_id

from app.bot.models import AppContainer
from app.core.constants import APP_CONTAINER_KEY, USER_KEY
from app.core.enums import MiddlewareEventType
from app.core.formatters import format_log_user
from app.db.models.dto import UserDto

from .base import EventTypedMiddleware


class MaintenanceMiddleware(EventTypedMiddleware):
    __event_types__ = [MiddlewareEventType.MESSAGE, MiddlewareEventType.CALLBACK_QUERY]

    async def __call__(
        self,
        handler: Callable[[Union[Message, CallbackQuery], dict[str, Any]], Awaitable[Any]],
        event: Union[Message, CallbackQuery],
        data: dict[str, Any],
    ) -> Any:
        user: Optional[UserDto] = data.get(USER_KEY)

        if user is None:
            return

        container: AppContainer = data[APP_CONTAINER_KEY]
        maintenance_service = container.services.maintenance

        if not await maintenance_service.is_active():
            return await handler(event, data)

        if user.is_privileged:
            self.logger.debug(f"{format_log_user(user)} Access allowed (privileged)")
            return await handler(event, data)

        if await maintenance_service.is_global_mode():
            self.logger.info(f"{format_log_user(user)} Access denied (global)")
            # TODO: Notify user about maintenance
            return

        if await maintenance_service.is_purchase_mode() and self._is_purchase_action(event):
            self.logger.warning(f"{format_log_user(user)} Access denied (purchase)")
            # TODO: Notify user about maintenance

            if await maintenance_service.should_notify_user(user.telegram_id):
                await maintenance_service.register_waiting_user(user.telegram_id)
                self.logger.debug(f"{format_log_user(user)} Added to waiting list")

            return

    def _is_purchase_action(self, event: Union[Message, CallbackQuery]) -> bool:
        if not isinstance(event, (CallbackQuery)) or event.data is None:
            return False

        callback_data = remove_intent_id(event.data)
        # TODO: Find purchase actions
