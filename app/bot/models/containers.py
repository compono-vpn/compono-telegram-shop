from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from remnawave_api import RemnawaveSDK
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.bot.middlewares import I18nMiddleware
    from app.bot.services import MaintenanceService
    from app.core.config import AppConfig
    from app.db.crud import (
        UserService,
        PromocodeService,
        PlanService,
    )

from dataclasses import dataclass


@dataclass
class ServicesContainer:
    maintenance: MaintenanceService
    user: UserService
    plan: PlanService
    promocode: PromocodeService


@dataclass
class AppContainer:
    config: AppConfig
    i18n: I18nMiddleware
    session_pool: async_sessionmaker[AsyncSession]
    redis: Redis
    remnawave: RemnawaveSDK
    services: ServicesContainer
