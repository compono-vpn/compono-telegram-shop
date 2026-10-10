from dishka import AsyncContainer
from loguru import logger

from src.core.config import AppConfig
from src.infrastructure.billing import BillingClient
from src.infrastructure.kafka.base_consumer import SupervisedKafkaConsumer
from src.infrastructure.taskiq.tasks.expiry_notifications import notify_subscription_expired
from src.services.notification import NotificationService
from src.services.settings import SettingsService
from src.services.subscription import SubscriptionService
from src.services.user import UserService


class SubscriptionExpiredConsumer(SupervisedKafkaConsumer):
    """Turns billing's subscription.expired events into one 'expired' Telegram notice."""

    consumer_name = "subscription_expired"

    def __init__(self, config: AppConfig, container: AsyncContainer) -> None:
        super().__init__(config, container)
        self._topic = config.kafka_subscription_expired_topic
        self._group_id = f"{config.kafka_group_id}-expiry-notice"

    @property
    def topic(self) -> str:
        return self._topic

    @property
    def group_id(self) -> str:
        return self._group_id

    async def _handle_message(self, payload: dict) -> None:
        async with self._container() as request_container:
            sent = await notify_subscription_expired(
                payload=payload,
                billing=await request_container.get(BillingClient),
                user_service=await request_container.get(UserService),
                subscription_service=await request_container.get(SubscriptionService),
                notification_service=await request_container.get(NotificationService),
                settings_service=await request_container.get(SettingsService),
            )
        logger.info(
            f"Expired event for user {payload.get('telegram_id')} "
            f"subscription {payload.get('subscription_id')}: notice sent={sent}"
        )
