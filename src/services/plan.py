from typing import Optional

from aiogram import Bot
from fluentogram import TranslatorHub
from redis.asyncio import Redis

from src.core.config import AppConfig
from src.core.enums import PlanAvailability, PlanType
from src.infrastructure.database import UnitOfWork
from src.infrastructure.database.models.dto import PlanDto, UserDto
from src.infrastructure.database.models.sql import Plan, PlanDuration, PlanPrice
from src.infrastructure.redis import RedisRepository

from .base import BaseService


class PlanService(BaseService):
    def __init__(
        self,
        uow: UnitOfWork,
        config: AppConfig,
        bot: Bot,
        redis_client: Redis,
        redis_repository: RedisRepository,
        translator_hub: TranslatorHub,
    ) -> None:
        super().__init__(config, bot, redis_client, redis_repository, translator_hub)
        self.uow = uow

    async def create(self, plan: PlanDto) -> PlanDto:
        plan_dict = plan.model_dump(exclude={"durations"})
        db_plan = Plan(**plan_dict)

        for duration_data in plan.durations:
            db_duration = PlanDuration(
                days=duration_data.days,
                plan=db_plan,
            )
            db_plan.durations.append(db_duration)

            for price_data in duration_data.prices:
                db_price = PlanPrice(
                    currency=price_data.currency,
                    price=price_data.price,
                    plan_duration=db_duration,
                )
                db_duration.prices.append(db_price)

        await self.uow.repository.create_instance(db_plan)
        return db_plan.dto()

    async def get(self, plan_id: int) -> Optional[PlanDto]:
        plan = await self.uow.repository.plans.get(plan_id=plan_id)
        return plan.dto() if plan else None

    async def get_by_name(self, name: str) -> Optional[PlanDto]:
        plan = await self.uow.repository.plans.get_by_name(name=name)
        return plan.dto() if plan else None

    async def get_all(self) -> list[PlanDto]:
        plans = await self.uow.repository.plans.get_all()
        return [plan.dto() for plan in plans]

    async def update(self, plan: PlanDto) -> Optional[PlanDto]:
        plan_instance = Plan(
            id=plan.id,
            name=plan.name,
            type=plan.type,
            is_active=plan.is_active,
            traffic_limit=plan.traffic_limit,
            device_limit=plan.device_limit,
            availability=plan.availability,
            allowed_user_ids=plan.allowed_user_ids,
        )

        plan_instance.durations = []
        for duration_dto in plan.durations:
            duration_instance = PlanDuration(
                id=duration_dto.id,
                days=duration_dto.days,
            )
            duration_instance.prices = []
            for price_dto in duration_dto.prices:
                price_instance = PlanPrice(
                    id=price_dto.id,
                    currency=price_dto.currency,
                    price=price_dto.price,
                )
                duration_instance.prices.append(price_instance)
            plan_instance.durations.append(duration_instance)

        db_plan = await self.uow.repository.merge_instance(plan_instance)
        return db_plan.dto() if db_plan else None

    async def delete(self, plan_id: int) -> bool:
        return await self.uow.repository.plans.delete(plan_id=plan_id)

    async def count(self) -> int:
        return await self.uow.repository.plans.count()

    async def filter_by_type(self, plan_type: PlanType) -> list[PlanDto]:
        plans = await self.uow.repository.plans.filter_by_type(plan_type)
        return [plan.dto() for plan in plans]

    async def filter_by_availability(self, available_for: PlanAvailability) -> list[PlanDto]:
        plans = await self.uow.repository.plans.filter_by_availability(available_for)
        return [plan.dto() for plan in plans]

    async def filter_active(self, is_active: bool = True) -> list[PlanDto]:
        plans = await self.uow.repository.plans.filter_active(is_active)
        return [plan.dto() for plan in plans]

    async def get_available_plans(self, user: UserDto) -> list[PlanDto]:
        plans: list[PlanDto] = await self.filter_active()
        # is_new_user = user.subscription_status is None
        # is_existing_user = user.subscription_status is not None
        # is_invited_user = user.is_invited

        filtered_plans = [
            plan
            for plan in plans
            if (
                plan.availability == PlanAvailability.ALL
                # or (plan.availability == PlanAvailability.NEW and is_new_user)
                # or (plan.availability == PlanAvailability.EXISTING and is_existing_user)
                # or (plan.availability == PlanAvailability.INVITED and is_invited_user)
                or (
                    plan.availability == PlanAvailability.ALLOWED
                    and hasattr(plan, "allowed_user_ids")
                    and user.telegram_id in plan.allowed_user_ids
                )
            )
        ]

        return filtered_plans
