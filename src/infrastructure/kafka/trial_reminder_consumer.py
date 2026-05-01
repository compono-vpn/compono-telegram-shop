import asyncio
import json

from aiokafka import AIOKafkaConsumer
from dishka import AsyncContainer
from loguru import logger
from redis.asyncio import Redis

from src.core.config import AppConfig
from src.infrastructure.taskiq.tasks.notifications import schedule_not_connected_reminder
from src.services.subscription import SubscriptionService


class TrialReminderConsumer:
    """Consumes subscription.created events and schedules a 2h not-connected
    reminder when is_trial=true. Runs alongside UserNotificationConsumer.
    """

    def __init__(self, config: AppConfig, container: AsyncContainer) -> None:
        self._brokers = config.kafka_brokers
        self._group_id = f"{config.kafka_group_id}-trial-reminder"
        self._topic = config.kafka_subscription_created_topic
        self._container = container
        self._consumer: AIOKafkaConsumer | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if not self._brokers:
            logger.warning("Kafka brokers not configured, skipping trial reminder consumer")
            return

        self._consumer = AIOKafkaConsumer(
            self._topic,
            bootstrap_servers=self._brokers,
            group_id=self._group_id,
            auto_offset_reset="latest",
            enable_auto_commit=True,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        )
        await self._consumer.start()
        logger.info(f"Trial reminder consumer started, topic={self._topic}")
        self._task = asyncio.create_task(self._consume_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._consumer:
            await self._consumer.stop()
            logger.info("Trial reminder consumer stopped")

    async def _consume_loop(self) -> None:
        try:
            async for msg in self._consumer:
                try:
                    await self._handle_message(msg.value)
                except Exception:
                    logger.exception("Failed to handle subscription.created event")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Trial reminder consumer loop crashed, will not restart")

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
                subscription.url, config.remnawave.sub_public_domain
            )
            await schedule_not_connected_reminder(redis_client, int(telegram_id), connect_url)
            logger.info(f"Scheduled trial reminder for telegram_id={telegram_id}")
