import logging

from aiogram import Bot, Dispatcher
from aiogram.types import WebhookInfo

from app.core.config import AppConfig

logger = logging.getLogger(__name__)


async def webhook_startup(bot: Bot, dispatcher: Dispatcher, config: AppConfig) -> None:
    success = await bot.set_webhook(
        url=config.bot.webhook_url.get_secret_value(),
        allowed_updates=dispatcher.resolve_used_update_types(),
        drop_pending_updates=config.bot.drop_pending_updates,
        secret_token=config.bot.secret_token.get_secret_value(),
    )

    if success:
        logger.info("Bot webhook set successfully")
        logger.debug(f"Webhook url: '{config.bot.safe_webhook_url}'")

        webhook: WebhookInfo = await bot.get_webhook_info()
        if webhook.last_error_message:
            logger.error(f"Webhook last error: {webhook.last_error_message}")
    else:
        logger.error("Failed to set bot webhook")


async def webhook_shutdown(bot: Bot, config: AppConfig) -> None:
    if not config.bot.reset_webhook:
        return

    if await bot.delete_webhook():
        logger.info("Bot webhook deleted successfully")
    else:
        logger.error("Failed to delete bot webhook")
