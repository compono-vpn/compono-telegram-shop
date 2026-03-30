from sqlalchemy import select

from src.infrastructure.database.models.sql.sent_notification import SentNotification

from .base import BaseRepository


class SentNotificationRepository(BaseRepository):
    async def exists(self, telegram_id: int, notification_key: str) -> bool:
        stmt = select(SentNotification.id).where(
            SentNotification.telegram_id == telegram_id,
            SentNotification.notification_key == notification_key,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def mark_sent(self, telegram_id: int, notification_key: str) -> None:
        instance = SentNotification(
            telegram_id=telegram_id,
            notification_key=notification_key,
        )
        self.session.add(instance)
        await self.session.flush()
