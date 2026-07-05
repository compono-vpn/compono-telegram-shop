from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.enums import ChatMemberStatus

from src.models.dto import UserDto
from src.services.channel_incentive import ChannelIncentiveService


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.expirations: dict[str, int] = {}

    async def get(self, key: str) -> bytes | None:
        return self.values.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value.encode()
        self.expirations[key] = ttl

    async def setnx(self, key: str, value: str) -> bool:
        if key in self.values:
            return False
        self.values[key] = value.encode()
        return True

    async def expire(self, key: str, ttl: int) -> None:
        self.expirations[key] = ttl


def _config(**overrides):
    config = SimpleNamespace(
        channel_incentive_enabled=True,
        channel_incentive_address="@componovpn",
        channel_incentive_url="https://t.me/componovpn",
        channel_incentive_discount_percent=5,
        channel_incentive_prompt_cooldown_seconds=86400,
        bot=SimpleNamespace(channel_chat_id=None, channel_url=None),
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def _user() -> UserDto:
    return UserDto(telegram_id=123, name="Test")


@pytest.mark.asyncio
async def test_discount_context_for_subscribed_member():
    bot = AsyncMock()
    bot.get_chat_member.return_value = SimpleNamespace(status=ChatMemberStatus.MEMBER)
    service = ChannelIncentiveService(_config(), bot, FakeRedis())

    result = await service.discount_context(_user())

    assert result == {
        "source": "compono_channel",
        "percent": 5,
        "channel": "@componovpn",
    }


@pytest.mark.asyncio
async def test_discount_context_absent_for_left_member():
    bot = AsyncMock()
    bot.get_chat_member.return_value = SimpleNamespace(status=ChatMemberStatus.LEFT)
    service = ChannelIncentiveService(_config(), bot, FakeRedis())

    assert await service.discount_context(_user()) is None


@pytest.mark.asyncio
async def test_membership_failure_does_not_grant_discount():
    bot = AsyncMock()
    bot.get_chat_member.side_effect = RuntimeError("telegram unavailable")
    service = ChannelIncentiveService(_config(), bot, FakeRedis())

    assert await service.discount_context(_user()) is None


@pytest.mark.asyncio
async def test_prompt_is_rate_limited():
    bot = AsyncMock()
    bot.get_chat_member.return_value = SimpleNamespace(status=ChatMemberStatus.LEFT)
    redis = FakeRedis()
    service = ChannelIncentiveService(_config(), bot, redis)
    user = _user()

    assert await service.should_prompt(user) is True
    assert await service.should_prompt(user) is False
