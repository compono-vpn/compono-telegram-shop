from typing import Optional

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.core.enums import PromocodeType
from src.infrastructure.database.models.dto import PromocodeDto

from .base import Base
from .timestamp import TimestampMixin


class Promocode(Base, TimestampMixin):
    __tablename__ = "promocodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    code: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    type: Mapped[PromocodeType] = mapped_column(Enum(PromocodeType), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_multi_use: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    lifetime: Mapped[Optional[int]] = mapped_column(Integer, default=None, nullable=True)
    duration: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    traffic: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # TODO: Implement storing subscription for activation
    discount_percent: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    activated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.telegram_id"),
        nullable=True,
    )

    def dto(self) -> PromocodeDto:
        return PromocodeDto.model_validate(self)
