import asyncio
import json

from aiokafka import AIOKafkaConsumer
from dishka import AsyncContainer
from loguru import logger

from src.core.config import AppConfig
from src.core.enums import SystemNotificationType
from src.core.utils.message_payload import MessagePayload
from src.bot.keyboards import get_user_keyboard
from src.services.notification import NotificationService


class UserNotificationConsumer:
    """Consumes generic user notification events from Kafka and delivers via Telegram.

    Any service can publish to {env}.compono.notify.user.v1 with:
    {
        "telegram_id": int,
        "type": "system",
        "ntf_type": "SUBSCRIPTION",
        "i18n_key": "ntf-event-subscription-new",
        "i18n_kwargs": { ... },
        "reply_markup_user_id": int | null
    }
    """

    def __init__(self, config: AppConfig, container: AsyncContainer) -> None:
        self._brokers = config.kafka_brokers
        self._group_id = config.kafka_group_id
        self._topic = config.kafka_notify_topic
        self._container = container
        self._consumer: AIOKafkaConsumer | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if not self._brokers:
            logger.warning("Kafka brokers not configured, skipping notification consumer")
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
        logger.info(f"Notification consumer started, topic={self._topic}")
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
            logger.info("Notification consumer stopped")

    async def _consume_loop(self) -> None:
        try:
            async for msg in self._consumer:
                try:
                    await self._handle_message(msg.value)
                except Exception:
                    logger.exception("Failed to handle notification event")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Notification consumer loop crashed, will not restart")

    async def _handle_message(self, payload: dict) -> None:
        telegram_id = payload.get("telegram_id")
        if not telegram_id:
            logger.warning("Notification event missing telegram_id, skipping")
            return

        msg_type = payload.get("type", "system")
        ntf_type_str = payload.get("ntf_type", "")
        i18n_key = payload.get("i18n_key", "")

        if not i18n_key:
            logger.warning("Notification event missing i18n_key, skipping")
            return

        try:
            ntf_type = SystemNotificationType(ntf_type_str)
        except ValueError:
            logger.warning(f"Unknown ntf_type '{ntf_type_str}', skipping")
            return

        i18n_kwargs = payload.get("i18n_kwargs", {})

        reply_markup = None
        reply_markup_user_id = payload.get("reply_markup_user_id")
        if reply_markup_user_id:
            reply_markup = get_user_keyboard(int(reply_markup_user_id))

        if msg_type != "system":
            logger.warning(f"Unknown notification type '{msg_type}', skipping")
            return

        async with self._container() as request_container:
            notification_service = await request_container.get(NotificationService)
            await notification_service.system_notify(
                ntf_type=ntf_type,
                payload=MessagePayload.not_deleted(
                    i18n_key=i18n_key,
                    i18n_kwargs=i18n_kwargs,
                    reply_markup=reply_markup,
                ),
            )

        logger.info(f"Delivered notification '{i18n_key}' for user {telegram_id}")
