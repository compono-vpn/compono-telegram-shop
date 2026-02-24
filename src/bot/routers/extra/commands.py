from aiogram import Router
from aiogram.filters import Command as FilterCommand
from aiogram.types import Message
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from fluentogram import TranslatorRunner
from loguru import logger

from src.bot.keyboards import get_contact_support_keyboard
from src.core.config.app import AppConfig
from src.core.enums import Command
from src.core.utils.formatters import format_user_log as log
from src.core.utils.message_payload import MessagePayload
from src.infrastructure.database.models.dto import UserDto
from src.services.notification import NotificationService
from src.services.remnawave import RemnawaveService
from src.services.subscription import SubscriptionService
from src.services.user import UserService

router = Router(name=__name__)


@inject
@router.message(FilterCommand(Command.PAYSUPPORT.value.command))
async def on_paysupport_command(
    message: Message,
    user: UserDto,
    config: AppConfig,
    i18n: FromDishka[TranslatorRunner],
    notification_service: FromDishka[NotificationService],
) -> None:
    logger.info(f"{log(user)} Call 'paysupport' command")

    text = i18n.get("contact-support-paysupport")
    support_username = config.bot.support_username.get_secret_value()

    await notification_service.notify_user(
        user=user,
        payload=MessagePayload.not_deleted(
            i18n_key="ntf-command-paysupport",
            reply_markup=get_contact_support_keyboard(support_username, text),
        ),
    )


@inject
@router.message(FilterCommand(Command.HELP.value.command))
async def on_help_command(
    message: Message,
    user: UserDto,
    config: AppConfig,
    i18n: FromDishka[TranslatorRunner],
    notification_service: FromDishka[NotificationService],
) -> None:
    logger.info(f"{log(user)} Call 'help' command")

    text = i18n.get("contact-support-help")
    support_username = config.bot.support_username.get_secret_value()

    await notification_service.notify_user(
        user=user,
        payload=MessagePayload.not_deleted(
            i18n_key="ntf-command-help",
            reply_markup=get_contact_support_keyboard(support_username, text),
        ),
    )


@inject
@router.message(FilterCommand("delete"))
async def on_delete_command(
    message: Message,
    user: UserDto,
    user_service: FromDishka[UserService],
    subscription_service: FromDishka[SubscriptionService],
    remnawave_service: FromDishka[RemnawaveService],
) -> None:
    if not user.is_privileged:
        return

    args = message.text.split(maxsplit=1) if message.text else []
    if len(args) < 2 or not args[1].strip().lstrip("-").isdigit():
        await message.reply("Usage: /delete <telegram_id>")
        return

    target_telegram_id = int(args[1].strip())

    if target_telegram_id == user.telegram_id:
        await message.reply("Cannot delete yourself")
        return

    target_user = await user_service.get(telegram_id=target_telegram_id)
    if not target_user:
        await message.reply(f"User {target_telegram_id} not found")
        return

    # Delete from Remnawave (VPN panel)
    try:
        await remnawave_service.delete_user(target_user)
    except Exception as e:
        logger.warning(f"{log(user)} Failed to delete user from panel: {e}")

    # Clear subscription caches before cascade delete
    subscription = await subscription_service.get_current(target_telegram_id)
    if subscription and subscription.id:
        await subscription_service.clear_subscription_cache(subscription.id, target_telegram_id)

    # Delete from bot DB (subscriptions cascade-delete via FK)
    await user_service.delete(target_user)

    await message.reply(f"Deleted user {target_telegram_id} ({target_user.name})")
    logger.info(f"{log(user)} Deleted user '{target_telegram_id}' via /delete command")
