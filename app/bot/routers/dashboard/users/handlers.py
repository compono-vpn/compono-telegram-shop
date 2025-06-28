import logging

from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode, StartMode, SubManager
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button

from app.bot.models import AppContainer
from app.bot.routers.dashboard.user.handlers import start_user_window
from app.bot.states import DashboardUsers
from app.core.constants import APP_CONTAINER_KEY, USER_KEY
from app.core.formatters import format_log_user
from app.db.models import UserDto

logger = logging.getLogger(__name__)


async def on_user_search(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]

    if not user.is_privileged:
        return

    if message.forward_from and not message.forward_from.is_bot:
        target_telegram_id = message.forward_from.id
    elif message.text and message.text.isdigit():
        target_telegram_id = int(message.text)
    else:
        return

    container: AppContainer = dialog_manager.middleware_data[APP_CONTAINER_KEY]
    target_user = await container.services.user.get(telegram_id=target_telegram_id)

    if target_user is None:
        # TODO: Notify not found user in db
        return

    logger.info(f"{format_log_user(user)} Searched for {format_log_user(target_user)}")
    await start_user_window(dialog_manager, target_user.telegram_id)


async def on_user_selected(
    callback: CallbackQuery,
    widget: Button,
    sub_manager: SubManager,
) -> None:
    await start_user_window(sub_manager, int(sub_manager.item_id))


async def on_unblock_all(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    container: AppContainer = dialog_manager.middleware_data[APP_CONTAINER_KEY]
    blocked_users = await container.services.user.get_blocked_users()

    for blocked_user in blocked_users:
        await container.services.user.set_block(user=blocked_user, blocked=False)

    # TODO: Notify
    logger.warning(f"{format_log_user(user)} Unblocked all users")
    await dialog_manager.start(DashboardUsers.BLACKLIST, mode=StartMode.RESET_STACK)
