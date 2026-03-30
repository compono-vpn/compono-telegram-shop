from datetime import datetime

from sqlalchemy import BigInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseSql
from .timestamp import NOW_FUNC


class SentNotification(BaseSql):
    __tablename__ = "sent_notifications"
    __table_args__ = (
        UniqueConstraint("telegram_id", "notification_key", name="uq_sent_notification"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    notification_key: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=NOW_FUNC, nullable=False)
