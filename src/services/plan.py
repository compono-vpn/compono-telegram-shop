from typing import Optional

from loguru import logger
from redis.asyncio import Redis

from src.core.config import AppConfig
from src.core.constants import TIME_10M
from src.core.enums import PlanAvailability
from src.core.storage.key_builder import build_key
from src.infrastructure.billing import BillingClient, billing_plan_to_dto
from src.infrastructure.database.models.dto import PlanDto, UserDto
from src.infrastructure.redis import RedisRepository
from src.infrastructure.redis.cache import redis_cache

from .base_billing import BaseBillingService


class PlanService(BaseBillingService):
    billing: BillingClient

    def __init__(
        self,
        config: AppConfig,
        redis_client: Redis,
        redis_repository: RedisRepository,
        #
        billing: BillingClient,
    ) -> None:
        super().__init__(config, redis_client, redis_repository)
        self.billing = billing

    async def create(self, plan: PlanDto) -> PlanDto:
        plan_data = _dto_to_billing_dict(plan)
        billing_plan = await self.billing.create_plan(plan_data)
        await self._clear_plan_cache()
        result = billing_plan_to_dto(billing_plan)
        logger.info(f"Created plan '{result.name}' with ID '{result.id}'")
        return result

    async def get(self, plan_id: int) -> Optional[PlanDto]:
        billing_plan = await self.billing.get_plan(plan_id)
        if billing_plan:
            logger.debug(f"Retrieved plan '{plan_id}'")
            return billing_plan_to_dto(billing_plan)
        logger.warning(f"Plan '{plan_id}' not found")
        return None

    async def get_by_name(self, plan_name: str) -> Optional[PlanDto]:
        billing_plan = await self.billing.get_plan_by_name(plan_name)
        if billing_plan:
            logger.debug(f"Retrieved plan by name '{plan_name}'")
            return billing_plan_to_dto(billing_plan)
        logger.warning(f"Plan with name '{plan_name}' not found")
        return None

    async def get_all(self) -> list[PlanDto]:
        billing_plans = await self.billing.list_plans()
        logger.debug(f"Retrieved '{len(billing_plans)}' plans")
        return [billing_plan_to_dto(p) for p in billing_plans]

    async def update(self, plan: PlanDto) -> Optional[PlanDto]:
        plan_data = _dto_to_billing_dict(plan)
        billing_plan = await self.billing.update_plan(plan_data)
        await self._clear_plan_cache()
        if billing_plan:
            result = billing_plan_to_dto(billing_plan)
            logger.info(f"Updated plan '{result.name}' (ID: '{result.id}')")
            return result
        logger.warning(f"Failed to update plan '{plan.name}' (ID: '{plan.id}')")
        return None

    async def delete(self, plan_id: int) -> bool:
        try:
            await self.billing.delete_plan(plan_id)
            await self._clear_plan_cache()
            logger.info(f"Plan '{plan_id}' deleted")
            return True
        except Exception:
            logger.opt(exception=True).warning(f"Failed to delete plan '{plan_id}'")
            return False

    async def count(self) -> int:
        plans = await self.billing.list_plans()
        return len(plans)

    #

    @redis_cache(prefix="get_trial_plan", ttl=TIME_10M)
    async def get_trial_plan(self) -> Optional[PlanDto]:
        billing_plan = await self.billing.get_trial_plan()
        if billing_plan:
            dto = billing_plan_to_dto(billing_plan)
            if dto.is_active:
                logger.debug(f"Available trial plan '{dto.name}'")
                return dto
            logger.warning(f"Trial plan '{dto.name}' found but is not active")
        logger.debug("No active trial plan found")
        return None

    async def get_available_plans(self, user: UserDto) -> list[PlanDto]:
        logger.debug(f"Fetching available plans for user '{user.telegram_id}'")
        billing_plans = await self.billing.get_available_plans(user.telegram_id)
        plans = [billing_plan_to_dto(p) for p in billing_plans]
        logger.info(f"Available plans: '{len(plans)}' for user '{user.telegram_id}'")
        return plans

    async def get_allowed_plans(self) -> list[PlanDto]:
        billing_plans = await self.billing.get_allowed_plans()
        plans = [billing_plan_to_dto(p) for p in billing_plans]
        logger.debug(f"Retrieved '{len(plans)}' allowed plans")
        return plans

    async def move_plan_up(self, plan_id: int) -> bool:
        try:
            await self.billing.move_plan_up(plan_id)
            await self._clear_plan_cache()
            logger.info(f"Plan '{plan_id}' reordered")
            return True
        except Exception:
            logger.opt(exception=True).warning(f"Failed to move plan '{plan_id}'")
            return False

    #

    async def _clear_plan_cache(self) -> None:
        trial_plan_key = build_key("cache", "get_trial_plan")
        await self.redis_client.delete(trial_plan_key)
        logger.debug("Trial plan cache invalidated")


def _dto_to_billing_dict(plan: PlanDto) -> dict:
    data = {
        "name": plan.name,
        "description": plan.description,
        "tag": plan.tag,
        "is_active": plan.is_active,
        "type": plan.type.value if hasattr(plan.type, "value") else str(plan.type),
        "availability": plan.availability.value if hasattr(plan.availability, "value") else str(plan.availability),
        "traffic_limit": plan.traffic_limit,
        "device_limit": plan.device_limit,
        "traffic_limit_strategy": plan.traffic_limit_strategy.value if hasattr(plan.traffic_limit_strategy, "value") else str(plan.traffic_limit_strategy),
        "allowed_user_ids": plan.allowed_user_ids,
        "internal_squads": [str(s) for s in plan.internal_squads],
        "external_squad": str(plan.external_squad) if plan.external_squad else None,
        "durations": [
            {
                "days": d.days,
                "prices": [
                    {
                        "currency": p.currency.value if hasattr(p.currency, "value") else str(p.currency),
                        "price": str(p.price),
                    }
                    for p in d.prices
                ],
            }
            for d in plan.durations
        ],
    }
    if plan.id:
        data["id"] = plan.id
    return data
