from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import Integer, String, Text
from sqlalchemy import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseSql
from .timestamp import NOW_FUNC


class WebhookLog(BaseSql):
    __tablename__ = "webhook_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gateway_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    payment_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID, nullable=True)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        server_default=NOW_FUNC,
        nullable=False,
    )
