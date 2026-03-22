"""Handlers for billing events — send Telegram messages."""

from aiogram import Bot
from fluentogram import TranslatorHub
from loguru import logger


class BillingEventHandlers:
    """Maps billing events to Telegram bot actions."""

    def __init__(self, bot: Bot, translator_hub: TranslatorHub, dev_id: int):
        self._bot = bot
        self._hub = translator_hub
        self._dev_id = dev_id

    async def on_payment_completed(self, payload: dict):
        """Handle payment.completed -> notify admin + user."""
        telegram_id = payload.get("telegram_id")
        plan_name = payload.get("plan_name", "")
        amount = payload.get("amount", "")
        currency = payload.get("currency", "")
        purchase_type = payload.get("purchase_type", "NEW")

        text = f"Payment: {purchase_type} | {plan_name} | {amount} {currency} | user: {telegram_id}"
        try:
            await self._bot.send_message(self._dev_id, text)
        except Exception as e:
            logger.error(f"Failed to send payment notification to dev: {e}")

    async def on_subscription_created(self, payload: dict):
        """Handle subscription.created -> notify user with connect instructions."""
        telegram_id = payload.get("telegram_id")
        is_trial = payload.get("is_trial", False)
        plan_name = payload.get("plan_name", "")

        try:
            label = "Trial" if is_trial else "Subscription"
            text = f"{label} activated: {plan_name}"
            await self._bot.send_message(telegram_id, text)
        except Exception as e:
            logger.error(f"Failed to send subscription notification to {telegram_id}: {e}")

    async def on_subscription_expired(self, payload: dict):
        """Handle subscription.expired -> notify user."""
        telegram_id = payload.get("telegram_id")
        try:
            await self._bot.send_message(telegram_id, "Your subscription has expired.")
        except Exception as e:
            logger.error(f"Failed to send expiry notification to {telegram_id}: {e}")

    async def on_subscription_limited(self, payload: dict):
        """Handle subscription.limited -> notify user."""
        telegram_id = payload.get("telegram_id")
        limit_type = payload.get("limit_type", "")
        try:
            await self._bot.send_message(telegram_id, f"Subscription limited: {limit_type}")
        except Exception as e:
            logger.error(f"Failed to send limit notification to {telegram_id}: {e}")

    async def on_referral_reward(self, payload: dict):
        """Handle referral.reward -> notify user."""
        telegram_id = payload.get("telegram_id")
        points = payload.get("points", 0)
        try:
            await self._bot.send_message(telegram_id, f"Referral reward: +{points}")
        except Exception as e:
            logger.error(f"Failed to send referral notification to {telegram_id}: {e}")
