from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, ErrorEvent
from aiogram_dialog import BgManagerFactory, ShowMode, StartMode
from dishka import FromDishka
from loguru import logger

from src.bot.states import MainMenu
from src.core.utils.formatters import format_user_log as log
from src.core.utils.message_payload import MessagePayload
from src.models.dto import UserDto
from src.services.notification import NotificationService


async def _answer_callback(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
    except TelegramAPIError as exc:
        logger.debug(f"Could not answer stale callback: {exc}")


async def _drop_stale_keyboard(bot: Bot, callback: CallbackQuery) -> None:
    message = callback.message
    if message is None:
        return
    try:
        await bot.edit_message_reply_markup(
            chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=None,
        )
    except TelegramAPIError as exc:
        logger.debug(f"Could not remove stale keyboard: {exc}")


async def _restart_main_menu(
    bot: Bot,
    bg_manager_factory: BgManagerFactory,
    user: UserDto,
) -> bool:
    try:
        bg_manager = bg_manager_factory.bg(
            bot=bot,
            user_id=user.telegram_id,
            chat_id=user.telegram_id,
        )
        await bg_manager.start(
            state=MainMenu.MAIN,
            mode=StartMode.RESET_STACK,
            show_mode=ShowMode.DELETE_AND_SEND,
        )
    except Exception:
        logger.exception(f"{log(user)} Failed to restart the main menu")
        return False
    return True


async def on_lost_context(
    event: ErrorEvent,
    user: UserDto,
    bot: Bot,
    bg_manager_factory: FromDishka[BgManagerFactory],
    notification_service: FromDishka[NotificationService],
) -> None:
    logger.warning(f"{log(user)} Lost context: {event.exception}")

    callback = event.update.callback_query
    if callback is not None:
        await _answer_callback(callback)
        await _drop_stale_keyboard(bot, callback)

    recovered = await _restart_main_menu(bot, bg_manager_factory, user)
    await notification_service.notify_user(
        user=user,
        payload=MessagePayload(
            i18n_key="ntf-menu-refreshed" if recovered else "ntf-error-lost-context"
        ),
    )
