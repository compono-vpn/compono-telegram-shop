from typing import Any, Optional

from app.core.enums import PlanAvailability, PlanType
from app.db import SQLSessionContext
from app.db.models.dto import PlanDto, PlanSchema
from app.db.models.sql import Plan, PlanDuration, PlanPrice

from .base import CrudService


class PlanService(CrudService):
    async def create(self, plan_data: PlanSchema) -> PlanDto:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            plan_dict = plan_data.model_dump(exclude={"durations"})
            db_plan = Plan(**plan_dict)

            for duration_data in plan_data.durations:
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

            await uow.commit(db_plan)
            await uow.session.refresh(db_plan)
            return db_plan.dto()

    async def get(self, plan_id: int) -> Optional[PlanDto]:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            db_plan = await repository.plans.get(plan_id=plan_id)
            return db_plan.dto() if db_plan else None

    async def get_by_name(self, name: str) -> Optional[PlanDto]:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            db_plan = await repository.plans.get_by_name(name=name)
            return db_plan.dto() if db_plan else None

    async def update(self, plan: PlanDto, **data: Any) -> Optional[PlanDto]:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            for key, value in data.items():
                setattr(plan, key, value)
            db_plan = await repository.plans.update(plan_id=plan.id, **plan.model_state)
            return db_plan.dto() if db_plan else None

    async def delete(self, plan_id: int) -> bool:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            return await repository.plans.delete(plan_id=plan_id)

    async def count(self) -> int:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            return await repository.plans.count()

    async def filter_by_type(self, plan_type: PlanType) -> list[PlanDto]:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            plans = await repository.plans.filter_by_type(plan_type)
            return [plan.dto() for plan in plans]

    async def filter_by_availability(self, available_for: PlanAvailability) -> list[PlanDto]:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            plans = await repository.plans.filter_by_availability(available_for)
            return [plan.dto() for plan in plans]

    async def filter_active(self, is_active: bool = True) -> list[PlanDto]:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            plans = await repository.plans.filter_active(is_active)
            return [plan.dto() for plan in plans]
