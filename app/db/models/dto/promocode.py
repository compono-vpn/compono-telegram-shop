from datetime import datetime, timedelta
from typing import Optional

from app.core.enums import PromocodeType

from .base import TrackableModel


class PromocodeSchema(TrackableModel):
    code: str
    type: PromocodeType

    is_active: bool
    is_multi_use: bool

    lifetime: Optional[int] = None
    duration: Optional[int] = None
    traffic: Optional[int] = None
    discount_percent: Optional[int] = None

    activated_by: Optional[int] = None


class PromocodeDto(PromocodeSchema):
    id: int

    created_at: datetime
    updated_at: datetime

    @property
    def is_redeemed(self) -> bool:
        return self.activated_by is not None

    @property
    def is_unlimited(self) -> bool:
        return self.lifetime is None

    @property
    def expires_at(self) -> Optional[datetime]:
        if self.lifetime is not None:
            return self.created_at + timedelta(days=self.lifetime)
        return None

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(tz=self.created_at.tzinfo) > self.expires_at

    @property
    def time_left(self) -> Optional[timedelta]:
        if self.expires_at is None:
            return None
        delta = self.expires_at - datetime.now(tz=self.created_at.tzinfo)
        return delta if delta.total_seconds() > 0 else timedelta(seconds=0)
