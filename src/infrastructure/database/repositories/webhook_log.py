from typing import Any, Optional

from src.infrastructure.database.models.sql import WebhookLog

from .base import BaseRepository


class WebhookLogRepository(BaseRepository):
    async def create(self, webhook_log: WebhookLog) -> WebhookLog:
        return await self.create_instance(webhook_log)

    async def update(self, log_id: int, **data: Any) -> Optional[WebhookLog]:
        return await self._update(WebhookLog, WebhookLog.id == log_id, **data)
