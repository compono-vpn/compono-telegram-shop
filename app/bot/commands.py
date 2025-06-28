import logging

from aiogram import Bot
from aiogram.types import BotCommandScopeAllPrivateChats

from app.core.config import AppConfig
from app.core.enums import Command

logger = logging.getLogger(__name__)


async def commands_setup(bot: Bot, config: AppConfig) -> None:
    if not config.bot.setup_commands:
        return

    commands = [Command.START.value]
    if await bot.set_my_commands(commands=commands, scope=BotCommandScopeAllPrivateChats()):
        logger.info("Bot commands successfully set")
    else:
        logger.error("Failed to set bot commands")


async def commands_delete(bot: Bot, config: AppConfig) -> None:
    if not config.bot.setup_commands:
        return

    if await bot.delete_my_commands(scope=BotCommandScopeAllPrivateChats()):
        logger.info("Bot commands successfully deleted")
    else:
        logger.error("Failed to delete bot commands")
