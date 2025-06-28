from redis.asyncio import Redis

from app.core.constants import MAINTENANCE_KEY, MAINTENANCE_WAITLIST_KEY
from app.core.enums import MaintenanceMode

from .base import BaseService


class MaintenanceService(BaseService):
    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        super().__init__()

    async def get_mode(self) -> MaintenanceMode:
        value = await self.redis.get(MAINTENANCE_KEY)

        if value is None:
            return MaintenanceMode.OFF
        if isinstance(value, bytes):
            value = value.decode()

        return MaintenanceMode(value)

    async def get_available_modes(self) -> list[MaintenanceMode]:
        current = await self.get_mode()
        return [mode for mode in MaintenanceMode if mode != current]

    async def set_mode(self, mode: MaintenanceMode) -> None:
        await self.redis.set(MAINTENANCE_KEY, mode.value)

    async def is_active(self) -> bool:
        return await self.get_mode() != MaintenanceMode.OFF

    async def is_purchase_mode(self) -> bool:
        return await self.get_mode() == MaintenanceMode.PURCHASE

    async def is_global_mode(self) -> bool:
        return await self.get_mode() == MaintenanceMode.GLOBAL

    async def register_waiting_user(self, telegram_id: int) -> None:
        await self.redis.sadd(MAINTENANCE_WAITLIST_KEY, telegram_id)

    async def should_notify_user(self, telegram_id: int) -> bool:
        return not await self.redis.sismember(MAINTENANCE_WAITLIST_KEY, telegram_id)

    async def get_waiting_users(self) -> list[int]:
        members = await self.redis.smembers(MAINTENANCE_WAITLIST_KEY)
        return [int(m.decode()) if isinstance(m, bytes) else int(m) for m in members]

    async def clear_waiting_users(self) -> None:
        await self.redis.delete(MAINTENANCE_WAITLIST_KEY)
        self.logger.debug("Cleared all users from maintenance waiting list")
