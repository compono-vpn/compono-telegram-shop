from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.kafka.pricing_outcome_consumer import PricingOutcomeConsumer


def _make_container(experiment_service):
    request_container = MagicMock()

    async def get(cls):
        if cls.__name__ == "ExperimentService":
            return experiment_service
        raise KeyError(cls)

    request_container.get = AsyncMock(side_effect=get)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=request_container)
    cm.__aexit__ = AsyncMock(return_value=None)

    return MagicMock(return_value=cm)


def _make_consumer(event: str = "payment_completed") -> PricingOutcomeConsumer:
    config = MagicMock()
    config.kafka_brokers = "localhost:9092"
    config.kafka_group_id = "test-group"
    return PricingOutcomeConsumer(
        config=config,
        container=_make_container(MagicMock()),
        topic="test.topic",
        group_suffix="pricing-outcome",
        event=event,
    )


@pytest.mark.asyncio
async def test_skips_payloads_without_experiment_attribution():
    experiment_service = MagicMock()
    container = _make_container(experiment_service)
    config = MagicMock()
    config.kafka_brokers = "localhost:9092"
    config.kafka_group_id = "test-group"
    consumer = PricingOutcomeConsumer(
        config=config,
        container=container,
        topic="test.topic",
        group_suffix="pricing-outcome",
        event="payment_completed",
    )

    await consumer._handle_message({"telegram_id": 12345})

    experiment_service.record_attributed_conversion.assert_not_called()


@pytest.mark.asyncio
async def test_tracks_attributed_payment_outcome():
    experiment_service = MagicMock()
    container = _make_container(experiment_service)
    config = MagicMock()
    config.kafka_brokers = "localhost:9092"
    config.kafka_group_id = "test-group"
    consumer = PricingOutcomeConsumer(
        config=config,
        container=container,
        topic="test.topic",
        group_suffix="pricing-outcome",
        event="payment_completed",
    )

    await consumer._handle_message(
        {
            "telegram_id": 12345,
            "experiment_attribution": {
                "feature_key": "intro_price",
                "variant_key": "intro_99",
                "config_revision": "rev-1",
            },
        }
    )

    experiment_service.record_attributed_conversion.assert_called_once_with(
        "intro_price",
        "intro_99",
        12345,
        "payment_completed",
    )


@pytest.mark.asyncio
async def test_tracks_subscription_created_outcome_with_original_assignment():
    experiment_service = MagicMock()
    container = _make_container(experiment_service)
    config = MagicMock()
    config.kafka_brokers = "localhost:9092"
    config.kafka_group_id = "test-group"
    consumer = PricingOutcomeConsumer(
        config=config,
        container=container,
        topic="test.topic",
        group_suffix="pricing-outcome",
        event="subscription_created",
    )

    await consumer._handle_message(
        {
            "telegram_id": 67890,
            "experiment_attribution": {
                "feature_key": "start_tier_price",
                "variant_key": "price_99",
            },
        }
    )

    experiment_service.record_attributed_conversion.assert_called_once_with(
        "start_tier_price",
        "price_99",
        67890,
        "subscription_created",
    )
