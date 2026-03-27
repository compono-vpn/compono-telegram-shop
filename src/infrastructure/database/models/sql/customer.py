from typing import Optional
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, Integer, String
from sqlalchemy import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseSql
from .timestamp import TimestampMixin


class Customer(BaseSql, TimestampMixin):
    __tablename__ = "customers"
    __table_args__ = (
        CheckConstraint(
            "email IS NOT NULL OR telegram_id IS NOT NULL",
            name="ck_customers_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[Optional[str]] = mapped_column(String, nullable=True, unique=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, unique=True)
    remna_user_uuid: Mapped[Optional[UUID]] = mapped_column(PG_UUID, nullable=True, unique=True)
    remna_username: Mapped[Optional[str]] = mapped_column(String, nullable=True, unique=True)
    subscription_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
