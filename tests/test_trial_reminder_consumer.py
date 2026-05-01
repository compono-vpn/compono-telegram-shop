"""Tests for TrialReminderConsumer._handle_message.

Covers the dispatch logic: which payloads trigger schedule_not_connected_reminder
and which are skipped. Kafka I/O is not exercised — that's just AIOKafkaConsumer.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_subscription

from src.infrastructure.kafka.trial_reminder_consumer import TrialReminderConsumer


def _make_container(subscription_dto, redis_client, sub_public_domain: str = "panel.example.com"):
    """Build a MagicMock container whose `container()` returns an async ctx mgr
    yielding a request_container with .get() resolving the three injected types."""
    subscription_service = MagicMock()
    subscription_service.get_current = AsyncMock(return_value=subscription_dto)

    config = MagicMock()
    config.remnawave.sub_public_domain = sub_public_domain

    request_container = MagicMock()

    async def get(cls):
        # Resolve by class name to avoid importing the real types here.
        match cls.__name__:
            case "SubscriptionService":
                return subscription_service
            case "Redis":
                return redis_client
            case "AppConfig":
                return config
            case _:
                raise KeyError(cls)

    request_container.get = AsyncMock(side_effect=get)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=request_container)
    cm.__aexit__ = AsyncMock(return_value=None)

    container = MagicMock(return_value=cm)
    return container, subscription_service


def _make_consumer(container) -> TrialReminderConsumer:
    config = MagicMock()
    config.kafka_brokers = "localhost:9092"
    config.kafka_group_id = "test-group"
    config.kafka_subscription_created_topic = "test.topic"
    return TrialReminderConsumer(config=config, container=container)


class TestHandleMessage:
    async def test_skips_when_is_trial_false(self):
        redis_client = AsyncMock()
        container, sub_service = _make_container(make_subscription(), redis_client)
        consumer = _make_consumer(container)

        with patch(
            "src.infrastructure.kafka.trial_reminder_consumer.schedule_not_connected_reminder",
            new=AsyncMock(),
        ) as mocked:
            await consumer._handle_message({"telegram_id": 12345, "is_trial": False})
            mocked.assert_not_awaited()
        sub_service.get_current.assert_not_awaited()

    async def test_skips_when_is_trial_missing(self):
        redis_client = AsyncMock()
        container, sub_service = _make_container(make_subscription(), redis_client)
        consumer = _make_consumer(container)

        with patch(
            "src.infrastructure.kafka.trial_reminder_consumer.schedule_not_connected_reminder",
            new=AsyncMock(),
        ) as mocked:
            await consumer._handle_message({"telegram_id": 12345})
            mocked.assert_not_awaited()

    async def test_skips_when_telegram_id_missing(self):
        redis_client = AsyncMock()
        container, sub_service = _make_container(make_subscription(), redis_client)
        consumer = _make_consumer(container)

        with patch(
            "src.infrastructure.kafka.trial_reminder_consumer.schedule_not_connected_reminder",
            new=AsyncMock(),
        ) as mocked:
            await consumer._handle_message({"is_trial": True})
            mocked.assert_not_awaited()
        sub_service.get_current.assert_not_awaited()

    async def test_schedules_reminder_for_trial(self):
        redis_client = AsyncMock()
        sub = make_subscription()
        sub.url = "https://panel.example.com/sub/abc123"
        container, sub_service = _make_container(
            sub, redis_client, sub_public_domain="public.example.com"
        )
        consumer = _make_consumer(container)

        with patch(
            "src.infrastructure.kafka.trial_reminder_consumer.schedule_not_connected_reminder",
            new=AsyncMock(),
        ) as mocked:
            await consumer._handle_message({"telegram_id": 12345, "is_trial": True})

            mocked.assert_awaited_once()
            args, _ = mocked.call_args
            assert args[0] is redis_client
            assert args[1] == 12345
            # connect_url is built from the rewritten URL with public domain
            assert args[2] == "https://public.example.com/connect/abc123"

        sub_service.get_current.assert_awaited_once_with(12345)

    async def test_skips_when_no_current_subscription(self):
        redis_client = AsyncMock()
        container, sub_service = _make_container(None, redis_client)
        consumer = _make_consumer(container)

        with patch(
            "src.infrastructure.kafka.trial_reminder_consumer.schedule_not_connected_reminder",
            new=AsyncMock(),
        ) as mocked:
            await consumer._handle_message({"telegram_id": 12345, "is_trial": True})
            mocked.assert_not_awaited()
        sub_service.get_current.assert_awaited_once_with(12345)
