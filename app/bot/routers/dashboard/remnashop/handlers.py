import logging

from aiogram.types import CallbackQuery
from aiogram_dialog import SubManager
from aiogram_dialog.widgets.kbd import Button

from app.bot.models.containers import AppContainer
from app.core.constants import APP_CONTAINER_KEY, USER_KEY
from app.core.enums import UserRole
from app.core.formatters import format_log_user
from app.db.models.dto.user import UserDto

logger = logging.getLogger(__name__)


async def on_user_role_removed(
    callback: CallbackQuery,
    widget: Button,
    sub_manager: SubManager,
):
    await sub_manager.load_data()
    user: UserDto = sub_manager.middleware_data[USER_KEY]
    container: AppContainer = sub_manager.middleware_data[APP_CONTAINER_KEY]
    target_user = await container.services.user.get(telegram_id=int(sub_manager.item_id))

    if target_user.telegram_id == container.config.bot.dev_id:
        logger.warning(
            f"{format_log_user(user)} Attempted to remove role for {format_log_user(target_user)}"
        )

        # TODO: BAN amogus?
        # TODO: Notify
        return

    await container.services.user.set_role(user=target_user, role=UserRole.USER)
    logger.info(f"{format_log_user(user)} Removed role for {format_log_user(target_user)}")
    # TODO: Notify
