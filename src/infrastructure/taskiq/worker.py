from dishka.integrations.aiogram import setup_dishka as setup_aiogram_dishka
from dishka.integrations.taskiq import setup_dishka as setup_taskiq_dishka
from taskiq import TaskiqEvents, TaskiqState
from taskiq_redis import RedisStreamBroker

from src.bot.dispatcher import create_bg_manager_factory, create_dispatcher, setup_dispatcher
from src.core.config import AppConfig
from src.core.logger import setup_logger
from src.infrastructure.di import create_container
from src.infrastructure.kafka.consumer import UserNotificationConsumer
from src.infrastructure.kafka.trial_reminder_consumer import TrialReminderConsumer

from .broker import broker

_notification_consumer: UserNotificationConsumer | None = None
_trial_reminder_consumer: TrialReminderConsumer | None = None


def worker() -> RedisStreamBroker:
    setup_logger()

    config = AppConfig.get()
    dispatcher = create_dispatcher(config=config)
    bg_manager_factory = create_bg_manager_factory(dispatcher=dispatcher)
    setup_dispatcher(dispatcher)
    container = create_container(config=config, bg_manager_factory=bg_manager_factory)

    setup_taskiq_dishka(container=container, broker=broker)
    setup_aiogram_dishka(container=container, router=dispatcher, auto_inject=True)

    @broker.on_event(TaskiqEvents.WORKER_STARTUP)
    async def on_startup(state: TaskiqState) -> None:
        global _notification_consumer, _trial_reminder_consumer  # noqa: PLW0603
        _notification_consumer = UserNotificationConsumer(config, container)
        await _notification_consumer.start()
        _trial_reminder_consumer = TrialReminderConsumer(config, container)
        await _trial_reminder_consumer.start()

    @broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
    async def on_shutdown(state: TaskiqState) -> None:
        if _notification_consumer:
            await _notification_consumer.stop()
        if _trial_reminder_consumer:
            await _trial_reminder_consumer.stop()

    return broker
