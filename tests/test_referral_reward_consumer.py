from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.kafka.referral_reward_consumer import ReferralRewardConsumer


def _make_consumer(referral_service) -> ReferralRewardConsumer:
    request_container = MagicMock()

    async def get(cls):
        if cls.__name__ == "ReferralService":
            return referral_service
        raise KeyError(cls)

    request_container.get = AsyncMock(side_effect=get)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=request_container)
    cm.__aexit__ = AsyncMock(return_value=None)

    config = MagicMock()
    config.kafka_brokers = "localhost:9092"
    config.kafka_group_id = "compono-shop"
    config.kafka_referral_reward_topic = "prod.compono-billing.referral.reward.v1"
    return ReferralRewardConsumer(config, MagicMock(return_value=cm))


def test_subscribes_to_billing_referral_reward_topic():
    consumer = _make_consumer(AsyncMock())

    assert consumer.topic == "prod.compono-billing.referral.reward.v1"
    assert consumer.group_id == "compono-shop-referral-reward"


@pytest.mark.asyncio
async def test_issues_pending_rewards_for_the_referrer():
    referral_service = AsyncMock()
    consumer = _make_consumer(referral_service)

    await consumer._handle_message(
        {"telegram_id": 560771220, "points": 14, "reason": "referral_level_1"}
    )

    referral_service.issue_pending_rewards.assert_awaited_once_with(560771220)


@pytest.mark.asyncio
async def test_skips_event_without_telegram_id():
    referral_service = AsyncMock()
    consumer = _make_consumer(referral_service)

    await consumer._handle_message({"points": 14})

    referral_service.issue_pending_rewards.assert_not_awaited()
