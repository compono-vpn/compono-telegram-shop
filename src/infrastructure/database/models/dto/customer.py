from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import Field

from .base import TrackableDto


class CustomerDto(TrackableDto):
    id: Optional[int] = Field(default=None, frozen=True)
    email: Optional[str] = None
    telegram_id: Optional[int] = None
    remna_user_uuid: Optional[UUID] = None
    remna_username: Optional[str] = None
    subscription_url: Optional[str] = None
    created_at: Optional[datetime] = Field(default=None, frozen=True)
    updated_at: Optional[datetime] = Field(default=None, frozen=True)
