import hashlib

from aiogram.methods import SetWebhook
from aiogram.types import WebhookInfo
from loguru import logger

from src.core.storage_keys import WebhookLockKey
from src.core.utils import mjson

from .base import BaseService


class WebhookService(BaseService):
    async def setup(self) -> None:
        safe_webhook_url = self.config.bot.safe_webhook_url(domain=self.config.domain)

        webhook = SetWebhook(
            url=self.config.bot.webhook_url(domain=self.config.domain).get_secret_value(),
            # allowed_updates=dispatcher.resolve_used_update_types(),
            drop_pending_updates=self.config.bot.drop_pending_updates,
            secret_token=self.config.bot.secret_token.get_secret_value(),
        )

        webhook_data = webhook.model_dump(exclude_unset=True)
        webhook_hash: str = hashlib.sha256(mjson.bytes_encode(webhook_data)).hexdigest()

        if await self._is_set(bot_id=self.bot.id, webhook_hash=webhook_hash):
            logger.info("Bot webhook setup skipped, already configured")
            logger.debug(f"Current webhook URL: '{safe_webhook_url}'")
            return

        if not await self.bot(webhook):
            raise RuntimeError(f"Failed to set bot webhook on URL '{safe_webhook_url}'")

        await self._clear(bot_id=self.bot.id)
        await self._set(bot_id=self.bot.id, webhook_hash=webhook_hash)

        logger.success("Bot webhook set successfully")
        logger.debug(f"Webhook URL: '{safe_webhook_url}'")

        webhook_info: WebhookInfo = await self.bot.get_webhook_info()
        if webhook_info.last_error_message:
            logger.warning(f"Webhook has a last error message: {webhook_info.last_error_message}")
            # TODO: Send notify

    async def delete(self) -> None:
        if not self.config.bot.reset_webhook:
            logger.debug("Bot webhook reset is disabled")
            return

        if await self.bot.delete_webhook():
            logger.info("Bot webhook deleted successfully")
            await self._clear(bot_id=self.bot.id)
        else:
            logger.error("Failed to delete bot webhook")

    async def _is_set(self, bot_id: int, webhook_hash: str) -> bool:
        key: WebhookLockKey = WebhookLockKey(bot_id=bot_id, webhook_hash=webhook_hash)
        return await self.redis_repository.exists(key=key)

    async def _set(self, bot_id: int, webhook_hash: str) -> None:
        key: WebhookLockKey = WebhookLockKey(bot_id=bot_id, webhook_hash=webhook_hash)
        await self.redis_repository.set(key=key, value=None)

    async def _clear(self, bot_id: int) -> None:
        key: WebhookLockKey = WebhookLockKey(bot_id=bot_id, webhook_hash="*")
        keys: list[bytes] = await self.redis_repository.client.keys(key.pack())

        if not keys:
            return

        await self.redis_repository.client.delete(*keys)
