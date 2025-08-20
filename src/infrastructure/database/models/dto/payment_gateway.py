from typing import Optional

from pydantic import Field

from src.core.enums import Currency, PaymentGatewayType

from .base import TrackableModel


class PaymentGatewayDto(TrackableModel):
    id: Optional[int] = Field(default=None, frozen=True)

    type: PaymentGatewayType
    currency: Currency
    is_active: bool

    shop_id: Optional[str]
    api_token: Optional[str]
