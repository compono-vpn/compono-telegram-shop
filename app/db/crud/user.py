from typing import Any, Optional

from app.core.enums import UserRole
from app.db import SQLSessionContext
from app.db.models.dto import UserDto, UserSchema
from app.db.models.sql import User

from .base import CrudService


class UserService(CrudService):
    async def create(self, user_data: UserSchema) -> UserDto:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            db_user = User(**user_data.model_dump())
            await uow.commit(db_user)
        return db_user.dto()

    async def get(self, telegram_id: int) -> Optional[UserDto]:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            db_user = await repository.users.get(telegram_id=telegram_id)
            return db_user.dto() if db_user else None

    async def update(self, user: UserDto, **data: Any) -> Optional[UserDto]:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            for key, value in data.items():
                setattr(user, key, value)
            db_user = await repository.users.update(
                telegram_id=user.telegram_id,
                **user.model_state,
            )
            return db_user.dto() if db_user else None

    async def count(self) -> int:
        async with SQLSessionContext(session_pool=self.session_pool) as (repository, uow):
            return await repository.users.count()

    async def get_devs(self) -> list[UserDto]:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            devs = await repository.users.filter_by_role(UserRole.DEV)
            return [dev.dto() for dev in devs]

    async def get_admins(self) -> list[UserDto]:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            admins = await repository.users.filter_by_role(UserRole.ADMIN)
            return [admin.dto() for admin in admins]

    async def get_blocked_users(self) -> list[UserDto]:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            users = await repository.users.filter_by_blocked()
            return [user.dto() for user in users]

    async def set_block(self, user: UserDto, blocked: bool) -> None:
        user.is_blocked = blocked
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            await repository.users.update(
                telegram_id=user.telegram_id,
                **user.model_state,
            )

    async def set_bot_blocked(self, user: UserDto, blocked: bool) -> None:
        user.is_bot_blocked = blocked
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            await repository.users.update(
                telegram_id=user.telegram_id,
                **user.model_state,
            )

    async def set_role(self, user: UserDto, role: UserRole) -> None:
        user.role = role
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            await repository.users.update(
                telegram_id=user.telegram_id,
                **user.model_state,
            )
