from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, JSON, Numeric, String
from sqlalchemy import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseSql
from .timestamp import NOW_FUNC


class WebOrder(BaseSql):
    __tablename__ = "web_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String, nullable=False)
    payment_id: Mapped[UUID] = mapped_column(PG_UUID, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="pending")
    amount: Mapped[Decimal] = mapped_column(Numeric(precision=10, scale=2), nullable=False)
    plan_duration_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    subscription_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    plan_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    plan_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    gateway_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_trial: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    claimed_by_telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=NOW_FUNC,
        nullable=False,
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
