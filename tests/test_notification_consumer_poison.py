from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fluentogram.exceptions import FormatError
from prometheus_client import REGISTRY

from src.infrastructure.kafka.consumer import UserNotificationConsumer


def _consumer() -> UserNotificationConsumer:
    config = MagicMock()
    config.kafka_brokers = "localhost:9092"
    config.kafka_notify_topic = "prod.compono.notify.user.v1"
    config.kafka_group_id = f"test-{uuid4()}"
    return UserNotificationConsumer(config, MagicMock())


async def test_format_error_is_discarded_so_next_message_can_advance() -> None:
    consumer = _consumer()
    consumer._handle_system_notify = AsyncMock(  # type: ignore[method-assign]
        side_effect=FormatError(ValueError("missing Fluent variable"), "broken-key")
    )

    before = (
        REGISTRY.get_sample_value(
            "kafka_consumer_discarded_messages_total",
            {"consumer": "notification", "reason": "format_error"},
        )
        or 0
    )

    await consumer._handle_message(
        {
            "telegram_id": 123,
            "type": "system",
            "i18n_key": "ntf-event-subscription-change",
        }
    )

    after = REGISTRY.get_sample_value(
        "kafka_consumer_discarded_messages_total",
        {"consumer": "notification", "reason": "format_error"},
    )
    assert after == before + 1


async def test_transient_redirect_error_still_propagates_for_retry() -> None:
    consumer = _consumer()
    consumer._handle_redirect = AsyncMock(  # type: ignore[method-assign]
        side_effect=RuntimeError("Telegram unavailable")
    )

    with pytest.raises(RuntimeError, match="Telegram unavailable"):
        await consumer._handle_message(
            {
                "telegram_id": 123,
                "type": "redirect",
                "redirect_to": "subscription_success",
            }
        )
