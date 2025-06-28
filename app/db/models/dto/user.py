from datetime import datetime

from app.core.enums import UserRole

from .base import TrackableModel


class UserSchema(TrackableModel):
    telegram_id: int

    name: str
    role: UserRole = UserRole.USER
    language: str

    personal_discount: float = 0
    purchase_discount: float = 0

    is_blocked: bool = False
    is_bot_blocked: bool = False
    is_trial_used: bool = False


class UserDto(UserSchema):
    id: int

    created_at: datetime
    updated_at: datetime

    @property
    def is_dev(self) -> bool:
        return self.role == UserRole.DEV

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

    @property
    def is_privileged(self) -> bool:
        return self.is_admin or self.is_dev

    @property
    def age_days(self) -> int:
        return (datetime.now(self.created_at.tzinfo) - self.created_at).days
