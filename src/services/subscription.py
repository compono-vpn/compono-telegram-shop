from datetime import datetime, timedelta
from typing import Optional, TypeVar, Union
from urllib.parse import urlparse, urlunparse

from aiogram import Bot
from fluentogram import TranslatorHub
from loguru import logger
from redis.asyncio import Redis
from remnapy.enums.users import TrafficLimitStrategy

from src.core.config import AppConfig
from src.core.constants import TIME_1M, TIME_5M, TIME_10M, TIMEZONE
from src.core.enums import SubscriptionStatus
from src.core.storage.key_builder import build_key
from src.core.utils.time import datetime_now
from src.infrastructure.billing import BillingClient, billing_subscription_to_dto
from src.infrastructure.database.models.dto import (
    PlanDto,
    PlanSnapshotDto,
    RemnaSubscriptionDto,
    SubscriptionDto,
    UserDto,
)
from src.infrastructure.redis import RedisRepository
from src.infrastructure.redis.cache import redis_cache

from .base import BaseService

T = TypeVar("T", SubscriptionDto, RemnaSubscriptionDto)


class SubscriptionService(BaseService):
    billing: BillingClient

    def __init__(
        self,
        config: AppConfig,
        bot: Bot,
        redis_client: Redis,
        redis_repository: RedisRepository,
        translator_hub: TranslatorHub,
        #
        billing: BillingClient,
    ) -> None:
        super().__init__(config, bot, redis_client, redis_repository, translator_hub)
        self.billing = billing

    def _rewrite_sub_url(self, subscription: Optional[SubscriptionDto]) -> Optional[SubscriptionDto]:
        if not subscription:
            return subscription
        domain = self.config.remnawave.sub_public_domain
        if not domain:
            return subscription
        parsed = urlparse(subscription.url)
        subscription.url = urlunparse(parsed._replace(netloc=domain))
        return subscription

    @staticmethod
    def build_connect_url(subscription_url: str, public_domain: str = "") -> str:
        parsed = urlparse(subscription_url)
        token = parsed.path.rstrip("/").split("/")[-1]
        netloc = public_domain or parsed.netloc
        return f"{parsed.scheme}://{netloc}/connect/{token}"

    @redis_cache(prefix="get_current_subscription", ttl=TIME_1M)
    async def get_current(self, telegram_id: int) -> Optional[SubscriptionDto]:
        billing_sub = await self.billing.get_current_subscription(telegram_id)
        if not billing_sub:
            logger.debug(f"No active subscription for user '{telegram_id}'")
            return None
        dto = billing_subscription_to_dto(billing_sub)
        return self._rewrite_sub_url(dto)

    async def get_all_by_user(self, telegram_id: int) -> list[SubscriptionDto]:
        billing_subs = await self.billing.list_subscriptions_by_user(telegram_id)
        logger.debug(f"Retrieved '{len(billing_subs)}' subscriptions for user '{telegram_id}'")
        return [billing_subscription_to_dto(s) for s in billing_subs]

    @redis_cache(prefix="has_used_trial", ttl=TIME_10M)
    async def has_used_trial(self, user_telegram_id: int) -> bool:
        return await self.billing.has_used_trial(user_telegram_id)

    async def clear_subscription_cache(self, subscription_id: int, user_telegram_id: int) -> None:
        list_cache_keys_to_invalidate = [
            build_key("cache", "get_subscription", subscription_id),
            build_key("cache", "get_current_subscription", user_telegram_id),
            build_key("cache", "has_used_trial", user_telegram_id),
        ]
        await self.redis_client.delete(*list_cache_keys_to_invalidate)

    @staticmethod
    def subscriptions_match(
        bot_subscription: Optional[SubscriptionDto],
        remna_subscription: Optional[RemnaSubscriptionDto],
    ) -> bool:
        if not bot_subscription or not remna_subscription:
            return False
        return (
            bot_subscription.user_remna_id == remna_subscription.uuid
            and bot_subscription.status == remna_subscription.status
            and bot_subscription.url == remna_subscription.url
            and bot_subscription.traffic_limit == remna_subscription.traffic_limit
            and bot_subscription.device_limit == remna_subscription.device_limit
            and bot_subscription.expire_at == remna_subscription.expire_at
            and bot_subscription.external_squad == remna_subscription.external_squad
            and bot_subscription.traffic_limit_strategy == remna_subscription.traffic_limit_strategy
            and bot_subscription.tag == remna_subscription.tag
            and sorted(bot_subscription.internal_squads)
            == sorted(remna_subscription.internal_squads)
        )

    @staticmethod
    def plan_match(plan_a: PlanSnapshotDto, plan_b: PlanDto) -> bool:
        if not plan_a or not plan_b:
            return False
        return (
            plan_a.id == plan_b.id
            and plan_a.tag == plan_b.tag
            and plan_a.type == plan_b.type
            and plan_a.traffic_limit == plan_b.traffic_limit
            and plan_a.device_limit == plan_b.device_limit
            and plan_a.traffic_limit_strategy == plan_b.traffic_limit_strategy
            and sorted(plan_a.internal_squads) == sorted(plan_b.internal_squads)
            and plan_a.external_squad == plan_b.external_squad
        )

    @staticmethod
    def find_matching_plan(
        plan_snapshot: PlanSnapshotDto, plans: list[PlanDto]
    ) -> Optional[PlanDto]:
        return next(
            (plan for plan in plans if SubscriptionService.plan_match(plan_snapshot, plan)), None
        )

    @staticmethod
    def apply_sync(target: T, source: Union[SubscriptionDto, RemnaSubscriptionDto]) -> T:
        target_fields = set(type(target).model_fields)
        source_fields = set(type(source).model_fields)
        field_map = {"user_remna_id": "uuid"}
        for target_field, source_field in field_map.items():
            if target_field in target_fields and hasattr(source, source_field):
                old_value = getattr(target, target_field)
                new_value = getattr(source, source_field)
                if old_value != new_value:
                    setattr(target, target_field, new_value)
        common_fields = target_fields & source_fields
        for field in common_fields:
            old_value = getattr(target, field)
            new_value = getattr(source, field)
            if old_value != new_value:
                setattr(target, field, new_value)
        return target

    @staticmethod
    def get_traffic_reset_delta(strategy: TrafficLimitStrategy) -> Optional[timedelta]:
        now = datetime_now()
        if strategy == TrafficLimitStrategy.NO_RESET:
            return None
        if strategy == TrafficLimitStrategy.DAY:
            next_day = now.date() + timedelta(days=1)
            reset_at = datetime.combine(next_day, datetime.min.time(), tzinfo=TIMEZONE)
            return reset_at - now
        if strategy == TrafficLimitStrategy.WEEK:
            weekday = now.weekday()
            days_until = (7 - weekday) % 7 or 7
            date_target = now.date() + timedelta(days=days_until)
            reset_at = datetime(
                date_target.year, date_target.month, date_target.day, 0, 5, 0, tzinfo=TIMEZONE
            )
            return reset_at - now
        if strategy == TrafficLimitStrategy.MONTH:
            year = now.year
            month = now.month + 1
            if month == 13:
                year += 1
                month = 1
            reset_at = datetime(year, month, 1, 0, 10, 0, tzinfo=TIMEZONE)
            return reset_at - now
        raise ValueError("Unsupported strategy")
