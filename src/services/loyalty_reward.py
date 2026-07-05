from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot
from fluentogram import TranslatorHub
from loguru import logger
from redis.asyncio import Redis

from src.core.config import AppConfig
from src.core.enums import SubscriptionStatus, UserRole
from src.core.utils.message_payload import MessagePayload
from src.core.utils.time import datetime_now
from src.infrastructure.redis import RedisRepository
from src.models.dto import UserDto
from src.services.notification import NotificationService
from src.services.remnawave import RemnawaveService
from src.services.subscription import SubscriptionService
from src.services.user import UserService

from .base import BaseService

LOYALTY_CAMPAIGN_ID = "early-users-2026-07"
LOYALTY_EXTRA_DAYS = 14
LOYALTY_PERSONAL_DISCOUNT = 30
LOYALTY_LOCK_SECONDS = 300


@dataclass
class LoyaltyRewardResult:
    scanned: int = 0
    eligible: int = 0
    granted: int = 0
    already_granted: int = 0
    pending_retry: int = 0
    skipped_no_subscription: int = 0
    skipped_trial: int = 0
    skipped_inactive: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def to_admin_message(self, *, dry_run: bool) -> str:
        mode = "DRY RUN" if dry_run else "CONFIRMED"
        lines = [
            f"Loyalty reward {mode}",
            f"scanned: {self.scanned}",
            f"eligible: {self.eligible}",
            f"granted: {self.granted}",
            f"already_granted: {self.already_granted}",
            f"pending_retry: {self.pending_retry}",
            f"skipped_no_subscription: {self.skipped_no_subscription}",
            f"skipped_trial: {self.skipped_trial}",
            f"skipped_inactive: {self.skipped_inactive}",
            f"failed: {self.failed}",
        ]
        if self.errors:
            lines.append("errors:")
            lines.extend(self.errors[:10])
        if dry_run:
            lines.append("")
            lines.append("Run /grant_loyalty_reward confirm to apply.")
        return "\n".join(lines)


class LoyaltyRewardService(BaseService):
    def __init__(
        self,
        config: AppConfig,
        bot: Bot,
        redis_client: Redis,
        redis_repository: RedisRepository,
        translator_hub: TranslatorHub,
        #
        user_service: UserService,
        subscription_service: SubscriptionService,
        remnawave_service: RemnawaveService,
        notification_service: NotificationService,
    ) -> None:
        super().__init__(config, bot, redis_client, redis_repository, translator_hub)
        self.user_service = user_service
        self.subscription_service = subscription_service
        self.remnawave_service = remnawave_service
        self.notification_service = notification_service

    async def preview(self, *, include_trials: bool = False) -> LoyaltyRewardResult:
        return await self._run(dry_run=True, include_trials=include_trials)

    async def grant(self, *, include_trials: bool = False) -> LoyaltyRewardResult:
        return await self._run(dry_run=False, include_trials=include_trials)

    async def _run(self, *, dry_run: bool, include_trials: bool) -> LoyaltyRewardResult:
        result = LoyaltyRewardResult()
        users = await self._list_candidate_users()

        for user in users:
            result.scanned += 1
            state = await self._get_state(user.telegram_id)
            if state == "granted":
                result.already_granted += 1
                continue
            if state:
                result.pending_retry += 1

            subscription = await self.subscription_service.get_current(user.telegram_id)
            if not subscription:
                result.skipped_no_subscription += 1
                continue
            if subscription.get_status != SubscriptionStatus.ACTIVE:
                result.skipped_inactive += 1
                continue
            if subscription.is_trial and not include_trials:
                result.skipped_trial += 1
                continue

            result.eligible += 1
            if dry_run:
                continue

            if not await self._acquire_lock(user.telegram_id):
                result.pending_retry += 1
                continue

            try:
                await self._grant_user(user, state)
                result.granted += 1
            except Exception as exc:
                result.failed += 1
                result.errors.append(f"{user.telegram_id}: {exc}")
                logger.opt(exception=True).error(
                    f"Failed to grant loyalty reward to '{user.telegram_id}'"
                )
            finally:
                await self._release_lock(user.telegram_id)

        return result

    async def _list_candidate_users(self) -> list[UserDto]:
        seen: set[int] = set()
        users: list[UserDto] = []
        for role in (UserRole.USER, UserRole.ADMIN, UserRole.DEV):
            for user in await self.user_service.get_by_role(role):
                if user.telegram_id in seen:
                    continue
                seen.add(user.telegram_id)
                users.append(user)
        return users

    async def _grant_user(self, user: UserDto, state: Optional[str]) -> None:
        subscription = await self.subscription_service.get_current(user.telegram_id)
        if not subscription:
            raise ValueError("active subscription disappeared")

        if state is None:
            base_expire_at = max(subscription.expire_at, datetime_now())
            target_expire_at = base_expire_at + timedelta(days=LOYALTY_EXTRA_DAYS)
            state = f"extend_to:{target_expire_at.isoformat()}"
            await self._set_state(user.telegram_id, state)

        if state.startswith("extend_to:"):
            target_expire_at = datetime.fromisoformat(state.removeprefix("extend_to:"))
            if subscription.expire_at < target_expire_at:
                subscription.expire_at = target_expire_at
                updated_subscription = await self.subscription_service.update(subscription)
                if updated_subscription:
                    subscription = updated_subscription
            await self._set_state(user.telegram_id, "subscription_extended")
        elif state != "subscription_extended":
            raise ValueError(f"unsupported loyalty reward state '{state}'")

        if (user.personal_discount or 0) < LOYALTY_PERSONAL_DISCOUNT:
            user.personal_discount = LOYALTY_PERSONAL_DISCOUNT
            updated_user = await self.user_service.update(user)
            if updated_user:
                user = updated_user

        await self.remnawave_service.updated_user(
            user=user,
            uuid=subscription.user_remna_id,
            subscription=subscription,
        )
        await self.notification_service.notify_user(
            user=user,
            payload=MessagePayload.not_deleted(
                i18n_key="ntf-event-user-loyalty-reward",
                i18n_kwargs={
                    "days": LOYALTY_EXTRA_DAYS,
                    "discount": LOYALTY_PERSONAL_DISCOUNT,
                },
            ),
        )
        await self._set_state(user.telegram_id, "granted")

    async def _get_state(self, telegram_id: int) -> Optional[str]:
        raw = await self.redis_client.get(self._state_key(telegram_id))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            return raw.decode()
        return str(raw)

    async def _set_state(self, telegram_id: int, state: str) -> None:
        await self.redis_client.set(self._state_key(telegram_id), state)

    async def _acquire_lock(self, telegram_id: int) -> bool:
        return bool(
            await self.redis_client.set(
                self._lock_key(telegram_id),
                "1",
                ex=LOYALTY_LOCK_SECONDS,
                nx=True,
            )
        )

    async def _release_lock(self, telegram_id: int) -> None:
        await self.redis_client.delete(self._lock_key(telegram_id))

    @staticmethod
    def _state_key(telegram_id: int) -> str:
        return f"loyalty_reward:{LOYALTY_CAMPAIGN_ID}:{telegram_id}"

    @staticmethod
    def _lock_key(telegram_id: int) -> str:
        return f"loyalty_reward:{LOYALTY_CAMPAIGN_ID}:{telegram_id}:lock"
