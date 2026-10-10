from dishka import AsyncContainer
from loguru import logger
from redis.asyncio import Redis

from src.core.config import AppConfig
from src.infrastructure.kafka.base_consumer import SupervisedKafkaConsumer
from src.infrastructure.taskiq.tasks.notifications import schedule_not_connected_reminder
from src.infrastructure.taskiq.tasks.setup_followups import schedule_setup_followups
from src.services.subscription import SubscriptionService


class TrialReminderConsumer(SupervisedKafkaConsumer):
    """Consumes subscription.created events and schedules a 2h not-connected
    reminder when is_trial=true. Runs alongside UserNotificationConsumer.
    """

    consumer_name = "trial_reminder"

    def __init__(self, config: AppConfig, container: AsyncContainer) -> None:
        super().__init__(config, container)
        self._topic = config.kafka_subscription_created_topic
        self._group_id = f"{config.kafka_group_id}-trial-reminder"

    @property
    def topic(self) -> str:
        return self._topic

    @property
    def group_id(self) -> str:
        return self._group_id

    async def _handle_message(self, payload: dict) -> None:
        if not payload.get("is_trial"):
            return

        telegram_id = payload.get("telegram_id")
        if not telegram_id:
            logger.warning("Trial event missing telegram_id, skipping")
            return

        async with self._container() as request_container:
            subscription_service = await request_container.get(SubscriptionService)
            redis_client = await request_container.get(Redis)
            config = await request_container.get(AppConfig)

            subscription = await subscription_service.get_current(int(telegram_id))
            if not subscription:
                logger.warning(
                    f"Trial reminder: no current subscription for telegram_id={telegram_id}"
                )
                return

            connect_url = SubscriptionService.build_connect_url(
                subscription.url, config.website_url
            )
            await schedule_not_connected_reminder(redis_client, int(telegram_id), connect_url)
            if subscription.id:
                await schedule_setup_followups(
                    redis_client, int(telegram_id), subscription.id, connect_url
                )
            logger.info(f"Scheduled trial reminder for telegram_id={telegram_id}")
