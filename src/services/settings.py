from typing import Any, Optional

from loguru import logger
from pydantic import SecretStr
from redis.asyncio import Redis

from src.core.config import AppConfig
from src.core.constants import TIME_10M
from src.core.enums import AccessMode, Currency, SystemNotificationType, UserNotificationType
from src.core.storage.key_builder import build_key
from src.core.utils.types import AnyNotification
from src.infrastructure.billing import BillingClient
from src.infrastructure.billing.converters import billing_settings_to_dto
from src.infrastructure.redis import RedisRepository
from src.infrastructure.redis.cache import redis_cache
from src.models.dto import ReferralSettingsDto, SettingsDto

from .base_billing import BaseBillingService


class SettingsService(BaseBillingService):
    billing: BillingClient

    def __init__(
        self,
        config: AppConfig,
        redis_client: Redis,
        redis_repository: RedisRepository,
        #
        billing: BillingClient,
    ) -> None:
        super().__init__(config, redis_client, redis_repository)
        self.billing = billing
        self._settings_memo: Optional[SettingsDto] = None

    @redis_cache(prefix="get_settings", ttl=TIME_10M)
    async def _fetch_settings(self) -> SettingsDto:
        billing_settings = await self.billing.get_settings()
        logger.debug("Retrieved settings from billing API")
        return billing_settings_to_dto(billing_settings)

    async def get(self) -> SettingsDto:
        if self._settings_memo is not None:
            return self._settings_memo
        self._settings_memo = await self._fetch_settings()
        return self._settings_memo

    async def update(self, settings: SettingsDto) -> SettingsDto:
        changed_data = settings.prepare_changed_data()

        if not changed_data:
            logger.warning("Settings update called, but no fields were actually changed")
            return settings

        # Convert SecretStr values to plain strings for JSON serialization
        serializable = {}
        for k, v in changed_data.items():
            if isinstance(v, SecretStr):
                serializable[k] = v.get_secret_value()
            else:
                serializable[k] = v

        billing_settings = await self.billing.update_settings(serializable)
        await self._clear_cache()
        logger.info("Settings updated via billing API")
        return billing_settings_to_dto(billing_settings)

    #

    async def is_rules_required(self) -> bool:
        settings = await self.get()
        return settings.rules_required

    async def is_channel_required(self) -> bool:
        settings = await self.get()
        return settings.channel_required

    #

    async def get_access_mode(self) -> AccessMode:
        settings = await self.get()
        mode = settings.access_mode
        logger.debug(f"Retrieved access mode '{mode}'")
        return mode

    async def set_access_mode(self, mode: AccessMode) -> None:
        settings = await self.get()
        settings.access_mode = mode
        await self.update(settings)
        logger.debug(f"Set access mode '{mode}'")

    #

    async def get_default_currency(self) -> Currency:
        settings = await self.get()
        currency = settings.default_currency
        logger.debug(f"Retrieved default currency '{currency}'")
        return currency

    async def set_default_currency(self, currency: Currency) -> None:
        settings = await self.get()
        settings.default_currency = currency
        await self.update(settings)
        logger.debug(f"Set default currency '{currency}'")

    #

    async def toggle_notification(self, notification_type: AnyNotification) -> bool:
        settings = await self.get()
        field_name = notification_type.value.lower()

        if isinstance(notification_type, UserNotificationType):
            current_value = getattr(settings.user_notifications, field_name, False)
            setattr(settings.user_notifications, field_name, not current_value)
            new_value = not current_value
        elif isinstance(notification_type, SystemNotificationType):
            current_value = getattr(settings.system_notifications, field_name, False)
            setattr(settings.system_notifications, field_name, not current_value)
            new_value = not current_value
        else:
            raise ValueError(f"Unknown notification type: '{notification_type}'")

        await self.update(settings)
        logger.debug(f"Toggled notification '{field_name}' -> '{new_value}'")
        return new_value

    async def is_notification_enabled(self, ntf_type: AnyNotification) -> bool:
        settings = await self.get()

        if isinstance(ntf_type, UserNotificationType):
            return settings.user_notifications.is_enabled(ntf_type)
        elif isinstance(ntf_type, SystemNotificationType):
            return settings.system_notifications.is_enabled(ntf_type)
        else:
            logger.critical(f"Unknown notification type: '{ntf_type}'")
            return False

    async def list_user_notifications(self) -> list[dict[str, Any]]:
        settings = await self.get()
        return [
            {
                "type": field.upper(),
                "enabled": value,
            }
            for field, value in settings.user_notifications.model_dump().items()
        ]

    async def list_system_notifications(self) -> list[dict[str, Any]]:
        settings = await self.get()
        return [
            {
                "type": field.upper(),
                "enabled": value,
            }
            for field, value in settings.system_notifications.model_dump().items()
        ]

    #

    async def get_referral_settings(self) -> ReferralSettingsDto:
        settings = await self.get()
        return settings.referral

    async def is_referral_enable(self) -> bool:
        settings = await self.get()
        return settings.referral.enable

    #

    async def _clear_cache(self) -> None:
        self._settings_memo = None
        settings_cache_key: str = build_key("cache", "get_settings")
        logger.debug(f"Cache '{settings_cache_key}' cleared")
        await self.redis_client.delete(settings_cache_key)
