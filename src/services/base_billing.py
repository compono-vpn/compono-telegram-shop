from abc import ABC

from redis.asyncio import Redis

from src.core.config import AppConfig
from src.infrastructure.redis import RedisRepository


class BaseBillingService(ABC):
    """Base class for billing/data services that do NOT require Bot or TranslatorHub.

    Services extending this class can later be extracted into a standalone billing
    microservice because they have no dependency on Telegram bot infrastructure.
    """

    config: AppConfig
    redis_client: Redis
    redis_repository: RedisRepository

    def __init__(
        self,
        config: AppConfig,
        redis_client: Redis,
        redis_repository: RedisRepository,
    ) -> None:
        self.config = config
        self.redis_client = redis_client
        self.redis_repository = redis_repository
