from sqlalchemy import BigInteger, Boolean, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import UserRole
from app.db.models.dto import UserDto

from .base import Base
from .timestamp import TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)

    name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.USER, nullable=False)
    language: Mapped[str] = mapped_column(String, nullable=False)

    personal_discount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    purchase_discount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_bot_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_trial_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def dto(self) -> UserDto:
        return UserDto.model_validate(self)
