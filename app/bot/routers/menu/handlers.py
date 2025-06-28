import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, ExceptionTypeFilter
from aiogram.types import ErrorEvent, Message
from aiogram_dialog import DialogManager, ShowMode, StartMode
from aiogram_dialog.api.exceptions import UnknownState

from app.bot.middlewares.i18n import I18nFormatter
from app.bot.states import MainMenu
from app.core.formatters import format_log_user
from app.db.models import UserDto

logger = logging.getLogger(__name__)
router = Router()


@router.message(CommandStart())
async def on_start_command(
    message: Message,
    user: UserDto,
    dialog_manager: DialogManager,
) -> None:
    logger.info(f"{format_log_user(user)} Started dialog")

    await dialog_manager.start(
        state=MainMenu.MAIN,
        mode=StartMode.RESET_STACK,
        show_mode=ShowMode.DELETE_AND_SEND,
    )


@router.error(ExceptionTypeFilter(UnknownState), F.update.message.as_("message"))
async def on_unknown_state(
    event: ErrorEvent,
    message: Message,
    dialog_manager: DialogManager,
    i18n_formatter: I18nFormatter,
    user: UserDto,
) -> None:
    logger.warning(f"{format_log_user(user)} Restarting dialog")

    await message.answer(i18n_formatter("ntf-error-unknown-state"))  # TODO: notification service
    await on_start_command(message=message, user=user, dialog_manager=dialog_manager)


@router.message(Command("test"))
async def on_test_command(message: Message, user: UserDto) -> None:
    logger.info(f"{format_log_user(user)} Test command executed")

    raise UnknownState("test_state")
