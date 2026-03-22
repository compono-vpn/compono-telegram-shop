"""Consumes billing events from Redis Streams and dispatches to bot handlers."""

import asyncio
import json
from typing import Callable, Awaitable

from loguru import logger
from redis.asyncio import Redis

from src.core.config.app import AppConfig

STREAM_KEY = "billing:events"
GROUP_NAME = "compono-bot"
CONSUMER_NAME = "bot-consumer-1"


class BillingEventConsumer:
    """Reads billing events from Redis Streams and dispatches to handlers."""

    def __init__(self, redis: Redis, config: AppConfig):
        self._redis = redis
        self._config = config
        self._handlers: dict[str, Callable[..., Awaitable]] = {}
        self._running = False

    def register(self, event_type: str, handler: Callable[..., Awaitable]):
        """Register a handler for an event type."""
        self._handlers[event_type] = handler

    async def start(self):
        """Start consuming events. Run as asyncio task."""
        self._running = True

        # Create consumer group if not exists
        try:
            await self._redis.xgroup_create(STREAM_KEY, GROUP_NAME, id="0", mkstream=True)
        except Exception:
            pass  # Group already exists

        logger.info("Billing event consumer started")

        while self._running:
            try:
                messages = await self._redis.xreadgroup(
                    GROUP_NAME,
                    CONSUMER_NAME,
                    {STREAM_KEY: ">"},
                    count=10,
                    block=5000,
                )

                for stream, entries in messages:
                    for msg_id, data in entries:
                        await self._process_message(msg_id, data)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error reading billing events: {e}")
                await asyncio.sleep(1)

    async def stop(self):
        self._running = False

    async def _process_message(self, msg_id: bytes, data: dict):
        try:
            event_type = data.get(b"type", data.get("type", ""))
            if isinstance(event_type, bytes):
                event_type = event_type.decode()

            payload_raw = data.get(b"payload", data.get("payload", "{}"))
            if isinstance(payload_raw, bytes):
                payload_raw = payload_raw.decode()

            payload = json.loads(payload_raw)

            handler = self._handlers.get(event_type)
            if handler:
                logger.debug(f"Handling billing event: {event_type}")
                await handler(payload)
            else:
                logger.warning(f"No handler for billing event: {event_type}")

            # Acknowledge message
            await self._redis.xack(STREAM_KEY, GROUP_NAME, msg_id)

        except Exception as e:
            logger.error(f"Error processing billing event {msg_id}: {e}")
