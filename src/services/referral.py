from io import BytesIO
from typing import Any, Optional, cast

from aiogram import Bot
from aiogram.types import BufferedInputFile, Message, TelegramObject
from fluentogram import TranslatorHub
from loguru import logger
from PIL import Image
from qrcode import ERROR_CORRECT_H, QRCode  # type: ignore[attr-defined]
from redis.asyncio import Redis

from src.core.config import AppConfig
from src.core.constants import ASSETS_DIR, REFERRAL_PREFIX, T_ME
from src.core.enums import (
    MessageEffect,
    ReferralLevel,
    ReferralRewardType,
    UserNotificationType,
)
from src.core.utils.message_payload import MessagePayload
from src.infrastructure.billing import BillingClient
from src.infrastructure.billing.converters import (
    billing_referral_reward_to_dto,
    billing_referral_to_dto,
)
from src.infrastructure.database.models.dto import (
    ReferralDto,
    ReferralRewardDto,
    TransactionDto,
    UserDto,
)
from src.infrastructure.redis import RedisRepository
from src.services.notification import NotificationService
from src.services.settings import SettingsService
from src.services.user import UserService

from .base import BaseService


class ReferralService(BaseService):
    billing: BillingClient
    user_service: UserService
    settings_service: SettingsService
    _bot_username: Optional[str]

    def __init__(
        self,
        config: AppConfig,
        bot: Bot,
        redis_client: Redis,
        redis_repository: RedisRepository,
        translator_hub: TranslatorHub,
        #
        billing: BillingClient,
        user_service: UserService,
        settings_service: SettingsService,
        notification_service: NotificationService,
    ) -> None:
        super().__init__(config, bot, redis_client, redis_repository, translator_hub)
        self.billing = billing
        self.user_service = user_service
        self.settings_service = settings_service
        self.notification_service = notification_service
        self._bot_username: Optional[str] = None

    async def create_referral(
        self, referrer: UserDto, referred: UserDto, level: ReferralLevel,
    ) -> ReferralDto:
        billing_ref = await self.billing.create_referral(
            referrer_telegram_id=referrer.telegram_id,
            referred_telegram_id=referred.telegram_id,
            level=level.value,
        )
        logger.info(f"Referral created: {referrer.telegram_id} -> {referred.telegram_id}")
        return billing_referral_to_dto(billing_ref)

    async def get_referral_by_referred(self, telegram_id: int) -> Optional[ReferralDto]:
        billing_ref = await self.billing.get_referral_by_referred(telegram_id)
        return billing_referral_to_dto(billing_ref) if billing_ref else None

    async def get_referrals_by_referrer(self, telegram_id: int) -> list[ReferralDto]:
        billing_refs = await self.billing.get_referrals_by_referrer(telegram_id)
        return [billing_referral_to_dto(r) for r in billing_refs]

    async def create_reward(
        self, referral_id: int, user_telegram_id: int,
        type: ReferralRewardType, amount: int,
    ) -> ReferralRewardDto:
        billing_reward = await self.billing.create_referral_reward(
            referral_id=referral_id,
            user_telegram_id=user_telegram_id,
            type=type.value,
            amount=amount,
        )
        logger.info(f"ReferralReward created for user '{user_telegram_id}'")
        return billing_referral_reward_to_dto(billing_reward)

    async def get_rewards_by_referral(self, referral_id: int) -> list[ReferralRewardDto]:
        billing_rewards = await self.billing.get_rewards_by_referral(referral_id)
        return [billing_referral_reward_to_dto(r) for r in billing_rewards]

    async def mark_reward_as_issued(self, reward_id: int) -> None:
        await self.billing.update_referral_reward(reward_id, is_issued=True)
        logger.info(f"Marked reward '{reward_id}' as issued")

    async def assign_referral_rewards(self, transaction: TransactionDto) -> None:
        from src.infrastructure.taskiq.tasks.referrals import give_referrer_reward_task  # noqa: PLC0415
        from src.core.enums import PurchaseType, ReferralAccrualStrategy, ReferralRewardStrategy  # noqa: PLC0415
        from decimal import Decimal  # noqa: PLC0415

        settings = await self.settings_service.get_referral_settings()
        if (
            settings.accrual_strategy == ReferralAccrualStrategy.ON_FIRST_PAYMENT
            and transaction.purchase_type != PurchaseType.NEW
        ):
            return
        user = transaction.user
        if not user:
            raise ValueError(f"Transaction '{transaction.id}' has no user")
        referral, parent = await self._get_referral_chain(user.telegram_id)
        if not referral:
            return
        reward_type = settings.reward.type
        reward_chain = {ReferralLevel.FIRST: referral.referrer}
        if parent:
            reward_chain[ReferralLevel.SECOND] = parent.referrer
        for level, referrer in reward_chain.items():
            if level > settings.level:
                continue
            config_value = settings.reward.config.get(level)
            if config_value is None:
                continue
            if settings.reward.strategy == ReferralRewardStrategy.AMOUNT:
                reward_amount = config_value
            elif settings.reward.strategy == ReferralRewardStrategy.PERCENT:
                pct = Decimal(config_value) / Decimal(100)
                if reward_type == ReferralRewardType.POINTS:
                    reward_amount = max(1, int(transaction.pricing.final_amount * pct))
                elif reward_type == ReferralRewardType.EXTRA_DAYS:
                    if transaction.plan and transaction.plan.duration:
                        reward_amount = max(1, int(Decimal(transaction.plan.duration) * pct))
                    else:
                        continue
                else:
                    continue
            else:
                continue
            if not reward_amount or reward_amount <= 0:
                continue
            reward = await self.create_reward(
                referral_id=referral.id, user_telegram_id=referrer.telegram_id,
                type=reward_type, amount=reward_amount,
            )
            await give_referrer_reward_task.kiq(
                user_telegram_id=referrer.telegram_id, reward=reward, referred_name=user.name,
            )

    async def get_referral_count(self, telegram_id: int) -> int:
        info = await self.billing.get_referral_stats(telegram_id)
        return info.get("referral_count", 0)

    async def get_reward_count(self, telegram_id: int) -> int:
        info = await self.billing.get_referral_stats(telegram_id)
        return info.get("reward_count", 0)

    async def get_total_rewards_amount(
        self,
        telegram_id: int,
        reward_type: ReferralRewardType,
    ) -> int:
        info = await self.billing.get_referral_stats(telegram_id)
        return info.get("total_rewards_amount", 0)

    #

    async def handle_referral(self, user: UserDto, code: Optional[str]) -> None:
        if not code:
            return

        code = code[len(REFERRAL_PREFIX):] if code.startswith(REFERRAL_PREFIX) else code

        referrer = await self._get_valid_referrer(code, user.telegram_id)
        if not referrer:
            return

        existing, parent = await self._get_referral_chain(user.telegram_id)
        if existing:
            logger.warning(f"Referral skipped: user '{user.telegram_id}' already referred")
            return

        level = self._define_referral_level(parent.level if parent else None)
        await self.create_referral(referrer, user, level)
        logger.info(f"Referral linked: {referrer.telegram_id} -> {user.telegram_id}, level {level.name}")

        if await self.settings_service.is_referral_enable():
            await self.notification_service.notify_user(
                user=referrer,
                ntf_type=UserNotificationType.REFERRAL_ATTACHED,
                payload=MessagePayload.not_deleted(
                    i18n_key="ntf-event-user-referral-attached",
                    i18n_kwargs={"name": user.name},
                    message_effect=MessageEffect.CONFETTI,
                ),
            )

    async def get_ref_link(self, referral_code: str) -> str:
        return f"{await self._get_bot_redirect_url()}?start={REFERRAL_PREFIX}{referral_code}"

    def get_ref_qr(self, url: str) -> BufferedInputFile:
        qr: Any = QRCode(
            version=1,
            error_correction=ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)

        qr_img_raw = qr.make_image(fill_color="black", back_color="white")
        qr_img: Image.Image
        if hasattr(qr_img_raw, "get_image"):
            qr_img = cast(Image.Image, qr_img_raw.get_image())
        else:
            qr_img = cast(Image.Image, qr_img_raw)
        qr_img = qr_img.convert("RGB")

        logo_path = ASSETS_DIR / "logo.png"
        if logo_path.exists():
            logo = Image.open(logo_path).convert("RGBA")
            qr_width, qr_height = qr_img.size
            logo_size = int(qr_width * 0.2)
            logo = logo.resize((logo_size, logo_size), resample=Image.Resampling.LANCZOS)
            pos = ((qr_width - logo_size) // 2, (qr_height - logo_size) // 2)
            qr_img.paste(logo, pos, mask=logo)

        buffer = BytesIO()
        qr_img.save(buffer, format="PNG")
        buffer.seek(0)
        return BufferedInputFile(file=buffer.getvalue(), filename="ref_qr.png")

    async def get_referrer_by_event(
        self,
        event: TelegramObject,
        user_telegram_id: int,
    ) -> Optional[UserDto]:
        if not isinstance(event, Message) or not event.text:
            return None
        code = self._parse_referral_code(event.text)
        if not code:
            return None
        return await self._get_valid_referrer(code, user_telegram_id)

    async def get_ref_code_by_event(self, event: TelegramObject) -> Optional[str]:
        if not isinstance(event, Message) or not event.text:
            return None
        return self._parse_referral_code(event.text)

    async def is_referral_event(self, event: TelegramObject, user_telegram_id: int) -> bool:
        if not isinstance(event, Message) or not event.text:
            return False
        code = self._parse_referral_code(event.text)
        if not code:
            return False
        return bool(await self._get_valid_referrer(code, user_telegram_id))

    async def _get_bot_redirect_url(self) -> str:
        if self._bot_username is None:
            self._bot_username = (await self.bot.get_me()).username
        return f"{T_ME}{self._bot_username}"

    def _parse_referral_code(self, text: str) -> Optional[str]:
        parts = text.split()
        if len(parts) <= 1:
            return None
        code = parts[1]
        if not code.startswith(REFERRAL_PREFIX):
            return None
        return code[len(REFERRAL_PREFIX):]

    def _define_referral_level(self, parent_level: Optional[ReferralLevel]) -> ReferralLevel:
        if parent_level is None:
            return ReferralLevel.FIRST
        next_level_value = parent_level.value + 1
        max_level_value = max(item.value for item in ReferralLevel)
        if next_level_value > max_level_value:
            return ReferralLevel(parent_level.value)
        return ReferralLevel(next_level_value)

    async def _get_referral_chain(
        self, user_id: int,
    ) -> tuple[Optional[ReferralDto], Optional[ReferralDto]]:
        referral = await self.get_referral_by_referred(user_id)
        parent = None
        if referral:
            parent = await self.get_referral_by_referred(referral.referrer.telegram_id)
        return referral, parent

    async def _get_valid_referrer(self, code: str, user_id: int) -> Optional[UserDto]:
        referrer = await self.user_service.get_by_referral_code(code)
        if not referrer or referrer.telegram_id == user_id:
            logger.warning(f"Invalid referral code '{code}' or self-referral by '{user_id}'")
            return None
        return referrer
