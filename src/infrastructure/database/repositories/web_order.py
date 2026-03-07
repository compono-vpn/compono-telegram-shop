from typing import Any, Optional
from uuid import UUID

from src.infrastructure.database.models.sql.web_order import WebOrder

from .base import BaseRepository


class WebOrderRepository(BaseRepository):
    async def create(self, web_order: WebOrder) -> WebOrder:
        return await self.create_instance(web_order)

    async def get_by_payment_id(self, payment_id: UUID) -> Optional[WebOrder]:
        return await self._get_one(WebOrder, WebOrder.payment_id == payment_id)

    async def update_by_payment_id(self, payment_id: UUID, **data: Any) -> Optional[WebOrder]:
        return await self._update(WebOrder, WebOrder.payment_id == payment_id, **data)
