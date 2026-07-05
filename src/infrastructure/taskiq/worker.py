from dishka.integrations.aiogram import setup_dishka as setup_aiogram_dishka
from dishka.integrations.taskiq import setup_dishka as setup_taskiq_dishka
from taskiq import TaskiqEvents, TaskiqState
from taskiq_redis import RedisStreamBroker

from src.bot.dispatcher import create_bg_manager_factory, create_dispatcher, setup_dispatcher
from src.core.config import AppConfig
from src.core.constants import TASKIQ_WORKER_METRICS_PORT
from src.core.logger import setup_logger
from src.core.metrics import start_metrics_server
from src.infrastructure.di import create_container
from src.infrastructure.kafka.consumer import UserNotificationConsumer
from src.infrastructure.kafka.pricing_outcome_consumer import PricingOutcomeConsumer
from src.infrastructure.kafka.trial_reminder_consumer import TrialReminderConsumer

from .broker import broker

_kafka_consumers: list[object] = []


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
        global _kafka_consumers  # noqa: PLW0603
        start_metrics_server(TASKIQ_WORKER_METRICS_PORT)
        _kafka_consumers = [
            UserNotificationConsumer(config, container),
            TrialReminderConsumer(config, container),
            PricingOutcomeConsumer(
                config,
                container,
                topic=config.kafka_payment_completed_topic,
                group_suffix="pricing-outcome-payment-completed",
                event="payment_completed",
            ),
            PricingOutcomeConsumer(
                config,
                container,
                topic=config.kafka_payment_canceled_topic,
                group_suffix="pricing-outcome-payment-canceled",
                event="payment_canceled",
            ),
            PricingOutcomeConsumer(
                config,
                container,
                topic=config.kafka_subscription_created_topic,
                group_suffix="pricing-outcome-subscription-created",
                event="subscription_created",
            ),
        ]
        for consumer in _kafka_consumers:
            await consumer.start()

    @broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
    async def on_shutdown(state: TaskiqState) -> None:
        for consumer in reversed(_kafka_consumers):
            await consumer.stop()

    return broker
