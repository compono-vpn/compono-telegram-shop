from typing import Any, Optional

from sqlalchemy import func, select

from src.core.enums import GatewayChannel, PaymentGatewayType
from src.infrastructure.database.models.sql import PaymentGateway

from .base import BaseRepository


class PaymentGatewayRepository(BaseRepository):
    async def create(self, gateway: PaymentGateway) -> PaymentGateway:
        return await self.create_instance(gateway)

    async def get(self, gateway_id: int) -> Optional[PaymentGateway]:
        return await self._get_one(PaymentGateway, PaymentGateway.id == gateway_id)

    async def get_by_type(
        self,
        gateway_type: PaymentGatewayType,
        channel: Optional[GatewayChannel] = None,
    ) -> Optional[PaymentGateway]:
        conditions = [PaymentGateway.type == gateway_type]
        if channel is not None:
            conditions.append(PaymentGateway.channel.in_([channel, GatewayChannel.ALL]))
        return await self._get_one(PaymentGateway, *conditions)

    async def exists_by_type(self, gateway_type: PaymentGatewayType) -> bool:
        result = await self.session.execute(
            select(PaymentGateway.id).where(PaymentGateway.type == gateway_type).limit(1)
        )
        return result.scalar() is not None

    async def get_all(self, sorted: bool = False) -> list[PaymentGateway]:
        if sorted:
            order_by = PaymentGateway.order_index.asc()
        else:
            order_by = PaymentGateway.id.asc()

        return await self._get_many(PaymentGateway, order_by=order_by)

    async def update(self, gateway_id: int, **data: Any) -> Optional[PaymentGateway]:
        return await self._update(PaymentGateway, PaymentGateway.id == gateway_id, **data)

    async def filter_active(
        self,
        is_active: bool,
        channel: Optional[GatewayChannel] = None,
    ) -> list[PaymentGateway]:
        conditions = [PaymentGateway.is_active == is_active]
        if channel is not None:
            conditions.append(PaymentGateway.channel.in_([channel, GatewayChannel.ALL]))
        return await self._get_many(
            PaymentGateway,
            *conditions,
            order_by=PaymentGateway.order_index.asc(),
        )

    async def list_by_type_active(
        self, gateway_type: PaymentGatewayType
    ) -> list[PaymentGateway]:
        return await self._get_many(
            PaymentGateway,
            PaymentGateway.type == gateway_type,
            PaymentGateway.is_active == True,
            order_by=PaymentGateway.order_index.asc(),
        )

    async def get_max_index(self) -> Optional[int]:
        return await self.session.scalar(select(func.max(PaymentGateway.order_index)))
