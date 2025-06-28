import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import AppConfig


class CrudService:
    session_pool: async_sessionmaker[AsyncSession]
    config: AppConfig
    # TODO: Implement caching of database data using Redis

    def __init__(
        self,
        session_pool: async_sessionmaker[AsyncSession],
        config: AppConfig,
    ) -> None:
        self.session_pool = session_pool
        self.config = config
        self.logger = logging.getLogger(f"{self.__class__.__module__}")
        self.logger.debug(f"{self.__class__.__name__} initialized")
