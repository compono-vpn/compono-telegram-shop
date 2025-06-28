from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import Currency, PlanAvailability, PlanType
from app.db.models.dto import PlanDto, PlanDurationDto, PlanPriceDto

from .base import Base
from .timestamp import TimestampMixin


class Plan(Base, TimestampMixin):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    type: Mapped[PlanType] = mapped_column(Enum(PlanType), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    traffic_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    device_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    availability: Mapped[PlanAvailability] = mapped_column(
        Enum(PlanAvailability),
        default=PlanAvailability.ALL,
        nullable=False,
    )
    allowed_user_ids: Mapped[Optional[list[int]]] = mapped_column(
        ARRAY(BigInteger),
        default=None,
        nullable=True,
    )

    durations: Mapped[list["PlanDuration"]] = relationship(
        "PlanDuration",
        back_populates="plan",
        cascade="all, delete-orphan",
        lazy="joined",
    )

    def dto(self) -> PlanDto:
        return PlanDto.model_validate(self)


class PlanDuration(Base):
    __tablename__ = "plan_durations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)

    prices: Mapped[list["PlanPrice"]] = relationship(
        "PlanPrice",
        back_populates="plan_duration",
        cascade="all, delete-orphan",
        lazy="joined",
    )

    plan: Mapped["Plan"] = relationship("Plan", back_populates="durations")

    def dto(self) -> PlanDurationDto:
        return PlanDurationDto.model_validate(self)


class PlanPrice(Base):
    __tablename__ = "plan_prices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plan_duration_id: Mapped[int] = mapped_column(
        ForeignKey("plan_durations.id", ondelete="CASCADE"), nullable=False
    )
    currency: Mapped[Currency] = mapped_column(Enum(Currency), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    plan_duration: Mapped["PlanDuration"] = relationship("PlanDuration", back_populates="prices")

    def dto(self) -> PlanPriceDto:
        return PlanPriceDto.model_validate(self)
