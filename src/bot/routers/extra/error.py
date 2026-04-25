from aiogram.types import ErrorEvent
from aiogram_dialog import DialogManager, StartMode
from loguru import logger

from src.bot.states import MainMenu
from src.core.utils.formatters import format_user_log as log
from src.models.dto import UserDto

# Registered in main router (src/bot/dispatcher.py)


async def on_lost_context(
    event: ErrorEvent,
    user: UserDto,
    dialog_manager: DialogManager,
) -> None:
    logger.warning(f"{log(user)} Lost context, restarting main menu: {event.exception}")
    await dialog_manager.start(MainMenu.MAIN, mode=StartMode.RESET_STACK)
