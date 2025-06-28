import logging
from typing import Union

from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager, StartMode, SubManager
from aiogram_dialog.widgets.kbd import Button, Select

from app.bot.models import AppContainer
from app.bot.states import DashboardUser
from app.core.constants import APP_CONTAINER_KEY, USER_KEY
from app.core.enums import UserRole
from app.core.formatters import format_log_user
from app.db.models import UserDto

logger = logging.getLogger(__name__)


async def start_user_window(
    manager: Union[DialogManager, SubManager],
    target_telegram_id: int,
) -> None:
    await manager.start(
        state=DashboardUser.MAIN,
        data={"target_telegram_id": target_telegram_id},
        mode=StartMode.RESET_STACK,
    )


async def on_block_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    container: AppContainer = dialog_manager.middleware_data[APP_CONTAINER_KEY]
    target_telegram_id = dialog_manager.start_data.get("target_telegram_id")
    target_user = await container.services.user.get(telegram_id=target_telegram_id)

    if target_user.telegram_id == container.config.bot.dev_id:
        logger.warning(f"{format_log_user(user)} Tried to block {format_log_user(target_user)}")
        await start_user_window(dialog_manager, target_telegram_id)
        # TODO: BAN amogus?
        # TODO: Notify
        return

    await container.services.user.set_block(user=target_user, blocked=not target_user.is_blocked)
    logger.info(f"{format_log_user(user)} Blocked {format_log_user(user)}")
    # TODO: Notify


async def on_role_selected(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_role: str,
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    container: AppContainer = dialog_manager.middleware_data[APP_CONTAINER_KEY]
    target_telegram_id = dialog_manager.start_data.get("target_telegram_id")
    target_user = await container.services.user.get(telegram_id=target_telegram_id)

    if target_user.telegram_id == container.config.bot.dev_id:
        logger.warning(
            f"{format_log_user(user)} Trying to switch role for {format_log_user(target_user)}"
        )
        await start_user_window(dialog_manager, target_telegram_id)
        # TODO: BAN amogus?
        # TODO: Notify
        return

    await container.services.user.set_role(user=target_user, role=UserRole(selected_role))
    logger.info(f"{format_log_user(user)} Switched role for {format_log_user(target_user)}")
    # TODO: Notify
