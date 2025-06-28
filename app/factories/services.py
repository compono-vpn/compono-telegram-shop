from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.models import ServicesContainer
from app.bot.services import MaintenanceService
from app.core.config import AppConfig
from app.db.crud import PlanService, PromocodeService, UserService


def create_services(
    session_pool: async_sessionmaker[AsyncSession],
    redis: Redis,
    config: AppConfig,
) -> ServicesContainer:
    crud_service_kwargs: dict[str, Any] = {
        "session_pool": session_pool,
        "config": config,
    }

    user_service = UserService(**crud_service_kwargs)
    plan_service = PlanService(**crud_service_kwargs)
    promocode_service = PromocodeService(**crud_service_kwargs)

    maintenance_service = MaintenanceService(redis)

    return ServicesContainer(
        maintenance=maintenance_service,
        user=user_service,
        plan=plan_service,
        promocode=promocode_service,
    )
