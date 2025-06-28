from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from app.core.enums import Currency, PlanAvailability, PlanType

from .base import TrackableModel


class PlanSchema(TrackableModel):
    name: str
    type: PlanType
    is_active: bool
    traffic_limit: Optional[int] = None
    device_limit: Optional[int] = None
    durations: list["PlanDurationSchema"]
    availability: PlanAvailability
    allowed_user_ids: Optional[list[int]] = None


class PlanDto(PlanSchema):
    id: int
    created_at: datetime
    updated_at: datetime

    @property
    def is_unlimited_traffic(self) -> bool:
        return self.traffic_limit is None or self.traffic_limit == 0

    @property
    def is_unlimited_devices(self) -> bool:
        return self.device_limit is None or self.device_limit == 0


class PlanDurationSchema(TrackableModel):
    days: int
    prices: list["PlanPriceSchema"]


class PlanDurationDto(PlanDurationSchema):
    id: int

    @property
    def total_duration(self) -> timedelta:
        return timedelta(days=self.days)

    def get_price_per_day(self, currency: Currency) -> Optional[Decimal]:
        if self.days <= 0:
            return None

        for price in self.prices:
            if price.currency == currency:
                return price.price / Decimal(self.days)
        return None


class PlanPriceSchema(TrackableModel):
    currency: Currency
    price: Decimal


class PlanPriceDto(PlanPriceSchema):
    id: int
