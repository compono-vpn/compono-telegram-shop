from typing import Any, Optional
from uuid import UUID

from sqlalchemy import cast, String, update

from src.infrastructure.database.models.sql.web_order import WebOrder

from .base import BaseRepository


class WebOrderRepository(BaseRepository):
    async def create(self, web_order: WebOrder) -> WebOrder:
        return await self.create_instance(web_order)

    async def get_by_payment_id(self, payment_id: UUID) -> Optional[WebOrder]:
        return await self._get_one(WebOrder, WebOrder.payment_id == payment_id)

    async def get_by_payment_id_prefix(self, prefix: str) -> Optional[WebOrder]:
        return await self._get_one(
            WebOrder,
            cast(WebOrder.payment_id, String).like(f"{prefix}%"),
        )

    async def exists_by_email(self, email: str) -> bool:
        """Check if a non-canceled order already exists for this email."""
        count = await self._count(
            WebOrder, WebOrder.email == email, WebOrder.status != "canceled"
        )
        return count > 0

    async def exists_claimed_by_telegram_id(self, telegram_id: int) -> bool:
        """Check if this telegram user already claimed any web order."""
        count = await self._count(
            WebOrder,
            WebOrder.claimed_by_telegram_id == telegram_id,
            WebOrder.status != "canceled",
        )
        return count > 0

    async def update_by_payment_id(self, payment_id: UUID, **data: Any) -> Optional[WebOrder]:
        return await self._update(WebOrder, WebOrder.payment_id == payment_id, **data)

    async def count_by_promocode_id(self, promocode_id: int) -> int:
        """Count non-canceled web orders that used this promocode."""
        return await self._count(
            WebOrder,
            WebOrder.promocode_id == promocode_id,
            WebOrder.status != "canceled",
        )

    async def transition_status(
        self, payment_id: UUID, from_status: str, to_status: str, **extra: Any
    ) -> Optional[WebOrder]:
        """Atomically update status only if current status matches from_status."""
        stmt = (
            update(WebOrder)
            .where(WebOrder.payment_id == payment_id, WebOrder.status == from_status)
            .values(status=to_status, **extra)
            .returning(WebOrder)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
