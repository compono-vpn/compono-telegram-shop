from typing import Any, Optional
from uuid import UUID

from sqlalchemy import update

from src.core.enums import TransactionStatus
from src.infrastructure.database.models.sql import Transaction

from .base import BaseRepository


class TransactionRepository(BaseRepository):
    async def create(self, transaction: Transaction) -> Transaction:
        return await self.create_instance(transaction)

    async def get(self, payment_id: UUID) -> Optional[Transaction]:
        return await self._get_one(Transaction, Transaction.payment_id == payment_id)

    async def get_by_user(self, telegram_id: int) -> list[Transaction]:
        return await self._get_many(Transaction, Transaction.user_telegram_id == telegram_id)

    async def get_all(self) -> list[Transaction]:
        return await self._get_many(Transaction)

    async def get_by_status(self, status: TransactionStatus) -> list[Transaction]:
        return await self._get_many(Transaction, Transaction.status == status)

    async def update(self, payment_id: UUID, **data: Any) -> Optional[Transaction]:
        return await self._update(Transaction, Transaction.payment_id == payment_id, **data)

    async def transition_status(
        self,
        payment_id: UUID,
        from_status: TransactionStatus,
        to_status: TransactionStatus,
    ) -> Optional[Transaction]:
        """Atomically transition status only if current status matches from_status.
        Returns the updated transaction if the transition happened, None if it was
        already in a different state (prevents duplicate processing)."""
        stmt = (
            update(Transaction)
            .where(
                Transaction.payment_id == payment_id,
                Transaction.status == from_status,
            )
            .values(status=to_status)
            .returning(Transaction)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count(self) -> int:
        return await self._count(Transaction, Transaction.id)

    async def count_by_status(self, status: TransactionStatus) -> int:
        return await self._count(Transaction, Transaction.status == status)
