from typing import Any, Optional

from app.core.enums import PromocodeType
from app.db import SQLSessionContext
from app.db.models.dto import PromocodeDto, PromocodeSchema
from app.db.models.sql import Promocode

from .base import CrudService


class PromocodeService(CrudService):
    async def create(self, promocode_data: PromocodeSchema) -> PromocodeDto:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            db_promocode = Promocode(**promocode_data.model_dump())
            await uow.commit(db_promocode)
            return db_promocode.dto()

    async def get(self, promocode_id: int) -> Optional[PromocodeDto]:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            db_promocode = await repository.promocodes.get(promocode_id=promocode_id)
            return db_promocode.dto() if db_promocode else None

    async def get_by_code(self, code: str) -> Optional[PromocodeDto]:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            db_promocode = await repository.promocodes.get_by_code(code=code)
            return db_promocode.dto() if db_promocode else None

    async def update(self, promocode: PromocodeDto, **data: Any) -> Optional[PromocodeDto]:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            for key, value in data.items():
                setattr(promocode, key, value)
            db_promocode = await repository.promocodes.update(
                promocode_id=promocode.id, **promocode.model_state
            )
            return db_promocode.dto() if db_promocode else None

    async def delete(self, promocode_id: int) -> bool:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            return await repository.promocodes.delete(promocode_id=promocode_id)

    async def count(self) -> int:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            return await repository.promocodes.count()

    async def filter_by_type(self, promocode_type: PromocodeType) -> list[PromocodeDto]:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            promocodes = await repository.promocodes.filter_by_type(promocode_type)
            return [promocode.dto() for promocode in promocodes]

    async def filter_active(self, is_active: bool = True) -> list[PromocodeDto]:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            promocodes = await repository.promocodes.filter_active(is_active)
            return [promocode.dto() for promocode in promocodes]

    async def filter_multi_use(self, is_multi_use: bool = True) -> list[PromocodeDto]:
        async with SQLSessionContext(self.session_pool) as (repository, uow):
            promocodes = await repository.promocodes.filter_multi_use(is_multi_use)
            return [promocode.dto() for promocode in promocodes]
