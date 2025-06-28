from typing import Any, Awaitable, Callable, Optional, Union

from aiogram.types import CallbackQuery, ErrorEvent, Message
from aiogram.types import User as AiogramUser

from app.bot.models import AppContainer
from app.core.constants import APP_CONTAINER_KEY, USER_KEY
from app.core.enums import MiddlewareEventType, UserRole
from app.core.formatters import format_log_user
from app.db.models.dto import UserDto, UserSchema

from .base import EventTypedMiddleware


class UserMiddleware(EventTypedMiddleware):
    __event_types__ = [
        MiddlewareEventType.MESSAGE,
        MiddlewareEventType.CALLBACK_QUERY,
        MiddlewareEventType.ERROR,
    ]

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Union[Union[Message, CallbackQuery, ErrorEvent], CallbackQuery, ErrorEvent],
        data: dict[str, Any],
    ) -> Any:
        aiogram_user: Optional[AiogramUser] = self._get_aiogram_user(event)

        if aiogram_user is None or aiogram_user.is_bot:
            return

        container: AppContainer = data[APP_CONTAINER_KEY]
        user_service = container.services.user
        user: Optional[UserDto] = await user_service.get(telegram_id=aiogram_user.id)

        if user is None:
            user_data = UserSchema(
                telegram_id=aiogram_user.id,
                name=aiogram_user.full_name,
                role=(
                    UserRole.DEV
                    if container.config.bot.dev_id == aiogram_user.id
                    else UserRole.USER
                ),
                language=(
                    aiogram_user.language_code
                    if aiogram_user.language_code in container.i18n.locales
                    else container.i18n.default_locale
                ),
            )
            user = await user_service.create(user_data)
            self.logger.info(f"{format_log_user(user)} Created new user")
            # TODO: Notify devs

        if user.is_bot_blocked:
            self.logger.info(f"{format_log_user(user)} Bot unblocked")
            await user_service.set_bot_blocked(user=user, blocked=False)

        data[USER_KEY] = user
        return await handler(event, data)
