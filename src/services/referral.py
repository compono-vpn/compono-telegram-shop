from io import BytesIO
from typing import Any, List, Optional, cast

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
from src.infrastructure.billing.client import BillingClientError
from src.infrastructure.database.models.dto import (
    ReferralDto,
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

        try:
            await self.billing.link_referral(code, user.telegram_id)
        except BillingClientError as e:
            logger.warning(f"Referral link failed: {e}")
            return

        logger.info(f"Referral linked: {referrer.telegram_id} -> {user.telegram_id}")

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

    async def _get_valid_referrer(self, code: str, user_id: int) -> Optional[UserDto]:
        referrer = await self.user_service.get_by_referral_code(code)
        if not referrer or referrer.telegram_id == user_id:
            logger.warning(f"Invalid referral code '{code}' or self-referral by '{user_id}'")
            return None
        return referrer
