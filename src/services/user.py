from typing import Optional, Union

from aiogram import Bot
from aiogram.types import Message
from aiogram.types import User as AiogramUser
from fluentogram import TranslatorHub
from loguru import logger
from pydantic import TypeAdapter
from redis.asyncio import Redis

from src.core.config import AppConfig
from src.core.constants import (
    RECENT_ACTIVITY_MAX_COUNT,
    REMNASHOP_PREFIX,
    TIME_5M,
    TIME_10M,
)
from src.core.enums import Locale, UserRole
from src.core.storage.key_builder import StorageKey, build_key
from src.core.storage.keys import RecentActivityUsersKey
from src.core.utils import json_utils
from src.core.utils.formatters import format_user_name
from src.core.utils.generators import generate_referral_code
from src.core.utils.types import RemnaUserDto
from src.infrastructure.billing import BillingClient
from src.infrastructure.billing.client import BillingClientError
from src.infrastructure.billing.converters import billing_user_to_dto
from src.models.dto import UserDto
from src.models.dto.user import BaseUserDto
from src.infrastructure.redis import RedisRepository, redis_cache
from src.infrastructure.redis.cache import prepare_for_cache

from .base import BaseService

_USER_DTO_ADAPTER: TypeAdapter[Optional[UserDto]] = TypeAdapter(Optional[UserDto])


class UserService(BaseService):
    billing: BillingClient

    def __init__(
        self,
        config: AppConfig,
        bot: Bot,
        redis_client: Redis,
        redis_repository: RedisRepository,
        translator_hub: TranslatorHub,
        #
        billing: BillingClient,
    ) -> None:
        super().__init__(config, bot, redis_client, redis_repository, translator_hub)
        self.billing = billing

    async def create(self, aiogram_user: AiogramUser, source: Optional[str] = None) -> UserDto:
        role = UserRole.DEV if self.config.bot.dev_id == aiogram_user.id else UserRole.USER
        language = (
            aiogram_user.language_code
            if aiogram_user.language_code in self.config.locales
            else self.config.default_locale
        )
        referral_code = generate_referral_code(
            aiogram_user.id,
            secret=self.config.crypt_key.get_secret_value(),
        )

        billing_user = await self.billing.create_user({
            "telegram_id": aiogram_user.id,
            "username": aiogram_user.username,
            "referral_code": referral_code,
            "name": aiogram_user.full_name,
            "role": role.value,
            "language": language,
            "source": source,
        })

        await self.clear_user_cache(aiogram_user.id)
        logger.info(f"Created new user '{aiogram_user.id}'")
        return billing_user_to_dto(billing_user)

    async def create_from_panel(self, remna_user: RemnaUserDto) -> UserDto:
        referral_code = generate_referral_code(
            remna_user.telegram_id,
            secret=self.config.crypt_key.get_secret_value(),
        )

        billing_user = await self.billing.create_user({
            "telegram_id": remna_user.telegram_id,
            "referral_code": referral_code,
            "name": str(remna_user.telegram_id),
            "role": UserRole.USER.value,
            "language": self.config.default_locale,
        })

        await self.clear_user_cache(remna_user.telegram_id)
        logger.info(f"Created new user '{remna_user.telegram_id}' from panel")
        return billing_user_to_dto(billing_user)

    @redis_cache(prefix="get_user", ttl=TIME_5M)
    async def get(self, telegram_id: int) -> Optional[UserDto]:
        billing_user = await self.billing.get_user(telegram_id)
        if billing_user:
            logger.debug(f"Retrieved user '{telegram_id}'")
            return billing_user_to_dto(billing_user)
        logger.warning(f"User '{telegram_id}' not found")
        return None

    async def update(self, user: UserDto) -> Optional[UserDto]:
        changed = user.prepare_changed_data()
        if not changed:
            return user

        billing_user = await self.billing.update_user(user.telegram_id, changed)
        updated_dto = billing_user_to_dto(billing_user)
        await self._repopulate_user_cache(user.telegram_id, updated_dto)
        logger.info(f"Updated user '{user.telegram_id}'")
        return updated_dto

    async def compare_and_update(
        self,
        user: UserDto,
        aiogram_user: AiogramUser,
    ) -> Optional[UserDto]:
        new_username = aiogram_user.username
        if user.username != new_username:
            user.username = new_username

        new_name = format_user_name(aiogram_user.full_name)
        if user.name != new_name:
            user.name = new_name

        new_language = aiogram_user.language_code
        if user.language != new_language:
            if new_language in self.config.locales:
                user.language = Locale(new_language)
            else:
                user.language = self.config.default_locale

        if not user.prepare_changed_data():
            return None

        return await self.update(user)

    async def delete(self, user: UserDto) -> bool:
        try:
            await self.billing.delete_user(user.telegram_id)
            await self.clear_user_cache(user.telegram_id)
            await self._remove_from_recent_activity(user.telegram_id)
            logger.info(f"Deleted user '{user.telegram_id}'")
            return True
        except BillingClientError:
            logger.opt(exception=True).warning(f"Failed to delete user '{user.telegram_id}'")
            return False

    async def get_by_referral_code(self, referral_code: str) -> Optional[UserDto]:
        billing_user = await self.billing.get_user_by_referral_code(referral_code)
        if billing_user:
            return billing_user_to_dto(billing_user)
        return None

    @redis_cache(prefix="users_count", ttl=TIME_10M)
    async def count(self) -> int:
        count = await self.billing.count_users()
        logger.debug(f"Total users count: '{count}'")
        return count

    @redis_cache(prefix="get_by_role", ttl=TIME_10M)
    async def get_by_role(self, role: UserRole) -> list[UserDto]:
        billing_users = await self.billing.list_users_by_role(role.value)
        logger.debug(f"Retrieved '{len(billing_users)}' users with role '{role}'")
        return [billing_user_to_dto(u) for u in billing_users]

    @redis_cache(prefix="get_blocked_users", ttl=TIME_10M)
    async def get_blocked_users(self) -> list[UserDto]:
        # Billing doesn't have a "blocked" filter — use role filter as fallback
        # TODO: add GET /users?blocked=true endpoint to billing
        all_devs = await self.billing.list_users_by_role("DEV")
        all_admins = await self.billing.list_users_by_role("ADMIN")
        blocked = [billing_user_to_dto(u) for u in all_devs + all_admins if u.IsBlocked]
        return blocked

    @redis_cache(prefix="get_all", ttl=TIME_10M)
    async def get_all(self) -> list[UserDto]:
        # Returns users by role for dashboard. Full list not available via API.
        # Used only by importer — consider removing.
        return []

    async def get_recent_registered_users(self) -> list[UserDto]:
        # Not available via billing API — return recent activity instead
        return await self.get_recent_activity_users()

    async def get_by_partial_name(self, query: str) -> list[UserDto]:
        # Not available via billing API — search by telegram ID only
        if query.isdigit():
            user = await self.get(int(query))
            return [user] if user else []
        return []

    async def set_block(self, user: UserDto, blocked: bool) -> None:
        user.is_blocked = blocked
        await self.billing.update_user(user.telegram_id, {"is_blocked": blocked})
        await self.clear_user_cache(user.telegram_id)
        logger.info(f"Set block={blocked} for user '{user.telegram_id}'")

    async def set_bot_blocked(self, user: UserDto, blocked: bool) -> None:
        user.is_bot_blocked = blocked
        await self.billing.update_user(user.telegram_id, {"is_bot_blocked": blocked})
        await self.clear_user_cache(user.telegram_id)
        logger.info(f"Set bot_blocked={blocked} for user '{user.telegram_id}'")

    async def set_role(self, user: UserDto, role: UserRole) -> None:
        user.role = role
        await self.billing.update_user(user.telegram_id, {"role": role.value})
        await self.clear_user_cache(user.telegram_id)
        logger.info(f"Set role='{role.name}' for user '{user.telegram_id}'")

    #

    async def update_recent_activity(self, telegram_id: int) -> None:
        throttle_key = build_key("throttle", "recent_activity", telegram_id)
        if await self.redis_client.exists(throttle_key):
            return
        await self.redis_client.setex(throttle_key, TIME_5M, 1)
        await self._add_to_recent_activity(RecentActivityUsersKey(), telegram_id)

    async def get_recent_activity_users(self, excluded_ids: list[int] = []) -> list[UserDto]:
        telegram_ids = await self._get_recent_activity()
        users: list[UserDto] = []

        for telegram_id in telegram_ids:
            if telegram_id in excluded_ids:
                continue
            user = await self.get(telegram_id)
            if user:
                users.append(user)
            else:
                await self._remove_from_recent_activity(telegram_id)

        logger.debug(f"Retrieved '{len(users)}' recent active users")
        return users

    async def search_users(self, message: Message) -> list[UserDto]:
        found_users = []

        if message.forward_from and not message.forward_from.is_bot:
            target_telegram_id = message.forward_from.id
            single_user = await self.get(telegram_id=target_telegram_id)
            if single_user:
                found_users.append(single_user)

        elif message.text:
            search_query = message.text.strip()

            if search_query.isdigit():
                single_user = await self.get(telegram_id=int(search_query))
                if single_user:
                    found_users.append(single_user)

            elif search_query.startswith(REMNASHOP_PREFIX):
                try:
                    target_id = int(search_query.split("_", maxsplit=1)[1])
                    single_user = await self.get(telegram_id=target_id)
                    if single_user:
                        found_users.append(single_user)
                except (IndexError, ValueError):
                    pass

            # Partial name search — not supported via billing API yet.
            # Falls back to returning empty for text queries that aren't IDs.

        return found_users

    async def set_current_subscription(self, telegram_id: int, subscription_id: int) -> None:
        await self.billing.update_user(telegram_id, {"current_subscription_id": subscription_id})
        await self.clear_user_cache(telegram_id)
        logger.info(f"Set current_subscription='{subscription_id}' for user '{telegram_id}'")

    async def delete_current_subscription(self, telegram_id: int) -> None:
        await self.billing.update_user(telegram_id, {"current_subscription_id": None})
        await self.clear_user_cache(telegram_id)
        logger.info(f"Delete current subscription for user '{telegram_id}'")

    async def add_points(self, user: Union[BaseUserDto, UserDto], points: int) -> None:
        await self.billing.update_user(user.telegram_id, {"points": user.points + points})
        await self.clear_user_cache(user.telegram_id)
        logger.info(f"Add '{points}' points for user '{user.telegram_id}'")

    #

    async def clear_user_cache(self, telegram_id: int) -> None:
        user_cache_key: str = build_key("cache", "get_user", telegram_id)
        await self.redis_client.delete(user_cache_key)
        await self._clear_list_caches()
        logger.debug(f"User cache for '{telegram_id}' invalidated")

    async def _repopulate_user_cache(self, telegram_id: int, user_dto: UserDto) -> None:
        user_cache_key: str = build_key("cache", "get_user", telegram_id)
        safe_result = prepare_for_cache(_USER_DTO_ADAPTER.dump_python(user_dto))
        await self.redis_client.setex(user_cache_key, TIME_5M, json_utils.encode(safe_result))
        await self._clear_list_caches()
        logger.debug(f"User cache for '{telegram_id}' repopulated")

    async def _clear_list_caches(self) -> None:
        list_cache_keys_to_invalidate = [
            build_key("cache", "get_blocked_users"),
            build_key("cache", "count"),
        ]
        for role in UserRole:
            key = build_key("cache", "get_by_role", role=role)
            list_cache_keys_to_invalidate.append(key)
        await self.redis_client.delete(*list_cache_keys_to_invalidate)

    async def _add_to_recent_activity(self, key: StorageKey, telegram_id: int) -> None:
        await self.redis_repository.list_remove(key, value=telegram_id, count=0)
        await self.redis_repository.list_push(key, telegram_id)
        await self.redis_repository.list_trim(key, start=0, end=RECENT_ACTIVITY_MAX_COUNT - 1)

    async def _remove_from_recent_activity(self, telegram_id: int) -> None:
        await self.redis_repository.list_remove(
            key=RecentActivityUsersKey(), value=telegram_id, count=0,
        )

    async def _get_recent_activity(self) -> list[int]:
        telegram_ids_str = await self.redis_repository.list_range(
            key=RecentActivityUsersKey(), start=0, end=RECENT_ACTIVITY_MAX_COUNT - 1,
        )
        return [int(uid) for uid in telegram_ids_str]
