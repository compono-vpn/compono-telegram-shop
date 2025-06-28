from typing import Any, Optional, cast

from sqlalchemy import select
from sqlalchemy.sql.functions import count

from app.core.enums import UserRole
from app.db.models.sql import User

from .base import BaseRepository


class UserRepository(BaseRepository):
    async def get(self, telegram_id: int) -> Optional[User]:
        return await self._get(User, User.telegram_id == telegram_id)

    async def update(self, telegram_id: int, **data: Any) -> Optional[User]:
        return await self._update(
            model=User,
            conditions=[User.telegram_id == telegram_id],
            load_result=True,
            **data,
        )

    async def delete(self, telegram_id: int) -> bool:
        return await self._delete(User, User.telegram_id == telegram_id)

    async def count(self) -> int:
        return cast(int, await self.session.scalar(select(count(User.id))))

    async def filter_by_role(self, role: UserRole) -> list[User]:
        return await self._get_many(User, User.role == role)

    async def filter_by_blocked(self, blocked: bool = True) -> list[User]:
        return await self._get_many(User, User.is_blocked == blocked)
