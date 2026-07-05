from __future__ import annotations

import json
from typing import Any

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from loguru import logger
from redis.asyncio import Redis

from src.core.config import AppConfig
from src.core.constants import TIME_5M
from src.core.storage.key_builder import build_key
from src.models.dto import UserDto

ALLOWED_STATUSES = {
    ChatMemberStatus.CREATOR,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.MEMBER,
}

SOURCE = "compono_channel"


class ChannelIncentiveService:
    def __init__(self, config: AppConfig, bot: Bot, redis_client: Redis) -> None:
        self.config = config
        self.bot = bot
        self.redis = redis_client

    @property
    def enabled(self) -> bool:
        return (
            self.config.channel_incentive_enabled
            and self.discount_percent > 0
            and bool(self.chat_id)
            and bool(self.channel_url)
        )

    @property
    def discount_percent(self) -> int:
        return max(0, min(50, self.config.channel_incentive_discount_percent))

    @property
    def chat_id(self) -> str | None:
        if self.config.channel_incentive_address:
            return self.config.channel_incentive_address
        return self.config.bot.channel_chat_id

    @property
    def channel_url(self) -> str | None:
        if self.config.channel_incentive_url:
            return self.config.channel_incentive_url
        return self.config.bot.channel_url

    async def is_subscribed(self, telegram_id: int, *, use_cache: bool = True) -> bool:
        chat_id = self.chat_id
        if not self.enabled or chat_id is None:
            return False

        cache_key = build_key("cache", "channel_incentive_member", chat_id, telegram_id)
        cached = await self.redis.get(cache_key) if use_cache else None
        if cached is not None:
            try:
                data = json.loads(cached.decode())
                status = ChatMemberStatus(data.get("status", "left"))
                is_member = data.get("is_member")
                return self._is_allowed(status, is_member)
            except Exception:
                logger.debug("Invalid channel incentive member cache payload, refreshing")

        try:
            member = await self.bot.get_chat_member(chat_id=chat_id, user_id=telegram_id)
        except Exception as exc:
            logger.warning(
                "Failed to check channel incentive membership for user '{}': {}",
                telegram_id,
                exc,
            )
            return False

        is_member = getattr(member, "is_member", None)
        await self.redis.setex(
            cache_key,
            TIME_5M,
            json.dumps({"status": member.status.value, "is_member": is_member}),
        )
        return self._is_allowed(member.status, is_member)

    async def discount_context(
        self,
        user: UserDto,
        *,
        use_cache: bool = True,
    ) -> dict[str, Any] | None:
        if not await self.is_subscribed(user.telegram_id, use_cache=use_cache):
            return None
        return {
            "source": SOURCE,
            "percent": self.discount_percent,
            "channel": self.chat_id,
        }

    async def should_prompt(self, user: UserDto) -> bool:
        if not self.enabled:
            return False
        if await self.is_subscribed(user.telegram_id):
            return False

        cooldown = max(0, self.config.channel_incentive_prompt_cooldown_seconds)
        if cooldown == 0:
            return True

        key = build_key("channel_incentive", "prompt", user.telegram_id)
        acquired = await self.redis.setnx(key, "1")
        if acquired:
            await self.redis.expire(key, cooldown)
        return bool(acquired)

    @staticmethod
    def _is_allowed(status: ChatMemberStatus, is_member: bool | None = None) -> bool:
        if status in ALLOWED_STATUSES:
            return True
        if status == ChatMemberStatus.RESTRICTED:
            return bool(is_member)
        return False
