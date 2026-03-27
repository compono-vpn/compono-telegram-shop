from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.infrastructure.database.models.sql.customer import Customer

from .base import BaseRepository


class CustomerRepository(BaseRepository):
    async def create(self, customer: Customer) -> Customer:
        return await self.create_instance(customer)

    async def get_by_id(self, customer_id: int) -> Optional[Customer]:
        return await self._get_one(Customer, Customer.id == customer_id)

    async def get_by_email(self, email: str) -> Optional[Customer]:
        return await self._get_one(Customer, Customer.email == email)

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[Customer]:
        return await self._get_one(Customer, Customer.telegram_id == telegram_id)

    async def get_by_remna_user_uuid(self, uuid: UUID) -> Optional[Customer]:
        return await self._get_one(Customer, Customer.remna_user_uuid == uuid)

    async def update(self, customer_id: int, **data: Any) -> Optional[Customer]:
        return await self._update(Customer, Customer.id == customer_id, **data)

    async def get_or_create_by_email(self, email: str) -> tuple[Customer, bool]:
        """Find customer by email or create a new one. Returns (customer, created)."""
        existing = await self.get_by_email(email)
        if existing:
            return existing, False

        try:
            customer = await self.create(Customer(email=email))
            return customer, True
        except IntegrityError:
            await self.session.rollback()
            existing = await self.get_by_email(email)
            assert existing is not None
            return existing, False

    async def get_or_create_by_telegram_id(self, telegram_id: int) -> tuple[Customer, bool]:
        """Find customer by telegram_id or create a new one. Returns (customer, created)."""
        existing = await self.get_by_telegram_id(telegram_id)
        if existing:
            return existing, False

        try:
            customer = await self.create(Customer(telegram_id=telegram_id))
            return customer, True
        except IntegrityError:
            await self.session.rollback()
            existing = await self.get_by_telegram_id(telegram_id)
            assert existing is not None
            return existing, False
