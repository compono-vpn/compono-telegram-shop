import asyncio
import json

from aiokafka import AIOKafkaConsumer
from dishka import AsyncContainer
from loguru import logger

from src.core.config import AppConfig
from src.core.metrics import KAFKA_CONSUMER_RESTARTS_TOTAL, KAFKA_CONSUMER_UP

INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 60.0
BACKOFF_MULTIPLIER = 2.0


class SupervisedKafkaConsumer:
    """Base class for Kafka consumers with at-least-once delivery and crash
    supervision.

    Offsets are committed manually, only after `_handle_message` returns
    successfully, so a crash mid-processing redelivers the message instead of
    silently dropping it. If the consume loop crashes, the supervisor logs it,
    flips the `kafka_consumer_up` gauge to 0, increments
    `kafka_consumer_restarts_total`, and restarts the loop (recreating the
    underlying AIOKafkaConsumer) with exponential backoff instead of leaving
    the consumer dead for the rest of the pod's lifetime.
    """

    consumer_name: str = "unnamed"

    def __init__(self, config: AppConfig, container: AsyncContainer) -> None:
        self._brokers = config.kafka_brokers
        self._container = container
        self._consumer: AIOKafkaConsumer | None = None
        self._supervisor_task: asyncio.Task | None = None
        self._stopping = False

        self._initial_backoff = INITIAL_BACKOFF_SECONDS
        self._max_backoff = MAX_BACKOFF_SECONDS
        self._backoff_multiplier = BACKOFF_MULTIPLIER

    @property
    def topic(self) -> str:
        raise NotImplementedError

    @property
    def group_id(self) -> str:
        raise NotImplementedError

    async def _handle_message(self, payload: dict) -> None:
        raise NotImplementedError

    async def start(self) -> None:
        if not self._brokers:
            logger.warning(f"Kafka brokers not configured, skipping {self.consumer_name} consumer")
            return

        self._stopping = False
        self._supervisor_task = asyncio.create_task(self._supervise())

    async def stop(self) -> None:
        self._stopping = True
        if self._supervisor_task:
            self._supervisor_task.cancel()
            try:
                await self._supervisor_task
            except asyncio.CancelledError:
                pass
            self._supervisor_task = None
        await self._stop_consumer()
        KAFKA_CONSUMER_UP.labels(consumer=self.consumer_name).set(0)
        logger.info(f"{self.consumer_name} consumer stopped")

    async def _stop_consumer(self) -> None:
        if self._consumer:
            await self._consumer.stop()
            self._consumer = None

    async def _supervise(self) -> None:
        backoff = self._initial_backoff
        while not self._stopping:
            try:
                await self._run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                KAFKA_CONSUMER_UP.labels(consumer=self.consumer_name).set(0)
                KAFKA_CONSUMER_RESTARTS_TOTAL.labels(consumer=self.consumer_name).inc()
                logger.exception(
                    f"{self.consumer_name} consumer crashed, restarting in {backoff:.1f}s"
                )
                await self._stop_consumer()
                await asyncio.sleep(backoff)
                backoff = min(backoff * self._backoff_multiplier, self._max_backoff)
            else:
                backoff = self._initial_backoff
                if self._stopping:
                    break

    async def _run_once(self) -> None:
        self._consumer = AIOKafkaConsumer(
            self.topic,
            bootstrap_servers=self._brokers,
            group_id=self.group_id,
            auto_offset_reset="latest",
            enable_auto_commit=False,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        )
        await self._consumer.start()
        logger.info(f"{self.consumer_name} consumer started, topic={self.topic}")
        KAFKA_CONSUMER_UP.labels(consumer=self.consumer_name).set(1)
        try:
            async for msg in self._consumer:
                await self._handle_message(msg.value)
                await self._consumer.commit()
        finally:
            await self._stop_consumer()
