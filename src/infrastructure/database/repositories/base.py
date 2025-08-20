from typing import Any, Optional, Type, TypeVar, Union, cast

from sqlalchemy import ColumnExpressionArgument, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from src.infrastructure.database.models.sql import Base

T = TypeVar("T", bound=Base)
ModelType = Type[T]

ConditionType = ColumnExpressionArgument[Any]
OrderByArgument = Union[ColumnExpressionArgument[Any], InstrumentedAttribute[Any]]


class BaseRepository:
    session: AsyncSession

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_instance(self, instance: T) -> T:
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def merge_instance(self, instance: T) -> T:
        return await self.session.merge(instance)

    async def delete_instance(self, instance: T) -> None:
        await self.session.delete(instance)

    async def _get_one(
        self,
        model: ModelType[T],
        *conditions: ConditionType,
    ) -> Optional[T]:
        return cast(Optional[T], await self.session.scalar(select(model).where(*conditions)))

    async def _get_many(
        self,
        model: ModelType[T],
        *conditions: ConditionType,
        order_by: Optional[OrderByArgument] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> list[T]:
        query = select(model).where(*conditions)

        if order_by is not None:
            query = query.order_by(*order_by)
        if limit is not None:
            query = query.limit(limit)
        if offset is not None:
            query = query.offset(offset)

        return list((await self.session.scalars(query)).unique().all())

    async def _update(
        self,
        model: ModelType[T],
        *conditions: ConditionType,
        load_result: bool = True,
        **kwargs: Any,
    ) -> Optional[T]:
        if not kwargs:
            if not load_result:
                return None
            return cast(Optional[T], await self._get(model, *conditions))

        query = update(model).where(*conditions).values(**kwargs)

        if load_result:
            query = query.returning(model)

        result = await self.session.execute(query)
        return result.scalar_one_or_none() if load_result else None

    async def _delete(
        self,
        model: ModelType[T],
        *conditions: ConditionType,
    ) -> int:
        result = await self.session.execute(delete(model).where(*conditions))
        return result.rowcount
