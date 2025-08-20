from sqlalchemy import Boolean, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.core.enums import Currency, PaymentGatewayType
from src.infrastructure.database.models.dto import PaymentGatewayDto

from .base import Base


class PaymentGateway(Base):
    __tablename__ = "payment_gateways"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    type: Mapped[PaymentGatewayType] = mapped_column(
        Enum(PaymentGatewayType), nullable=False, unique=True
    )
    currency: Mapped[Currency] = mapped_column(Enum(Currency), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    shop_id: Mapped[str] = mapped_column(String, default=None, nullable=True)
    api_token: Mapped[str] = mapped_column(String, default=None, nullable=True)

    def dto(self) -> PaymentGatewayDto:
        return PaymentGatewayDto.model_validate(self)
