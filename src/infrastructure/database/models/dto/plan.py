from datetime import timedelta
from decimal import Decimal
from typing import Optional

from pydantic import Field

from src.core.enums import Currency, PlanAvailability, PlanType

from .base import TrackableModel


class PlanDto(TrackableModel):
    id: Optional[int] = Field(default=None, frozen=True)

    name: str
    type: PlanType
    is_active: bool

    traffic_limit: Optional[int] = None
    device_limit: Optional[int] = None

    availability: PlanAvailability
    allowed_user_ids: Optional[list[int]] = None

    durations: list["PlanDurationDto"]

    @property
    def is_unlimited_traffic(self) -> bool:
        return self.traffic_limit is None or self.traffic_limit == 0

    @property
    def is_unlimited_devices(self) -> bool:
        return self.device_limit is None or self.device_limit == 0

    def get_duration(self, days: int) -> Optional["PlanDurationDto"]:
        return next((d for d in self.durations if d.days == days), None)


class PlanDurationDto(TrackableModel):
    id: Optional[int] = Field(default=None, frozen=True)

    days: int
    prices: list["PlanPriceDto"]

    @property
    def total_duration(self) -> timedelta:
        return timedelta(days=self.days)

    def get_price(self, currency: Currency) -> Optional["PlanPriceDto"]:
        return next((p for p in self.prices if p.currency == currency), None)

    def get_price_per_day(self, currency: Currency) -> Optional[Decimal]:
        if self.days <= 0:
            return None

        for price in self.prices:
            if price.currency == currency:
                return price.price / Decimal(self.days)
        return None


class PlanPriceDto(TrackableModel):
    id: Optional[int] = Field(default=None, frozen=True)

    currency: Currency
    price: Decimal
