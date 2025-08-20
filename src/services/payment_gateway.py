from typing import Optional

from aiogram import Bot
from fluentogram import TranslatorHub
from redis.asyncio import Redis

from src.core.config import AppConfig
from src.core.enums import Currency, PaymentGatewayType
from src.core.storage_keys import DefaultCurrencyKey
from src.infrastructure.database import UnitOfWork
from src.infrastructure.database.models.dto import PaymentGatewayDto
from src.infrastructure.redis import RedisRepository

from .base import BaseService


class PaymentGatewayService(BaseService):
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

    async def get(self, gateway_id: int) -> Optional[PaymentGatewayDto]:
        gateway = await self.uow.repository.gateways.get(gateway_id=gateway_id)
        return gateway.dto() if gateway else None

    async def get_by_type(self, gateway_type: PaymentGatewayType) -> Optional[PaymentGatewayDto]:
        gateway = await self.uow.repository.gateways.get_by_type(gateway_type=gateway_type)
        return gateway.dto() if gateway else None

    async def get_all(self) -> list[PaymentGatewayDto]:
        gateways = await self.uow.repository.gateways.get_all()
        return [gateway.dto() for gateway in gateways]

    async def update(self, gateway: PaymentGatewayDto) -> Optional[PaymentGatewayDto]:
        db_gateway = await self.uow.repository.gateways.get(gateway_id=gateway.id)

        if not db_gateway:
            return None

        db_gateway = await self.uow.repository.gateways.update(gateway.id, **gateway.model_state)

        return db_gateway.dto() if db_gateway else None

    async def filter_active(self, is_active: bool = True) -> list[PaymentGatewayDto]:
        gateways = await self.uow.repository.gateways.filter_active(is_active)
        return [gateway.dto() for gateway in gateways]

    async def get_default_currency(self) -> Currency:
        key = DefaultCurrencyKey()
        return await self.redis_repository.get(
            key=key,
            validator=Currency,
            default=Currency.RUB,
        )

    async def set_default_currency(self, currency: Currency) -> None:
        key = DefaultCurrencyKey()
        await self.redis_repository.set(key=key, value=currency.value)
