from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from fluentogram import TranslatorRunner
from loguru import logger
from redis.asyncio import Redis

from src.core.config import AppConfig
from src.core.constants import DEDICATED_IP_PREFIX
from src.core.enums import DedicatedIpCountry
from src.core.metrics import DEDICATED_IP_CHOSEN_TOTAL
from src.core.storage.keys import DedicatedIpChoiceKey
from src.core.utils.formatters import format_user_log as log
from src.infrastructure.billing import BillingClient
from src.models.dto import UserDto
from src.services.dedicated_ip import (
    DEDUP_KEY,
    KIND,
    get_choice,
    is_active_ultra_billing_subscription,
    send_ip_task,
)
from src.services.dedicated_ip import provision_command as _command

router = Router(name=__name__)

_LOCK_TTL = 60


def provision_command(telegram_id: int, country: DedicatedIpCountry) -> str:
    return _command("add", telegram_id, country)


async def _post_card(
    bot: Bot,
    config: AppConfig,
    user: UserDto,
    subscription_id: int,
    country: DedicatedIpCountry,
) -> None:
    await send_ip_task(
        bot,
        config,
        title="Ультра: подключить выделенный IP",
        summary="Клиент выбрал страну. Подключите IP и напишите клиенту, какой сервер выбрать.",
        telegram_id=user.telegram_id,
        username=user.username,
        subscription_id=subscription_id,
        command=provision_command(user.telegram_id, country),
        country=country,
    )


@inject
@router.callback_query(F.data.startswith(DEDICATED_IP_PREFIX))
async def on_dedicated_ip_country(
    callback: CallbackQuery,
    user: UserDto,
    i18n: FromDishka[TranslatorRunner],
    billing: FromDishka[BillingClient],
    redis_client: FromDishka[Redis],
    config: FromDishka[AppConfig],
) -> None:
    try:
        country = DedicatedIpCountry((callback.data or "").removeprefix(DEDICATED_IP_PREFIX))
    except ValueError:
        logger.warning(f"{log(user)} Unknown dedicated IP callback '{callback.data}'")
        await callback.answer()
        return

    try:
        subscription = await billing.get_current_subscription(user.telegram_id)
        chosen = await get_choice(billing, user.telegram_id)
    except Exception:
        logger.opt(exception=True).warning(f"{log(user)} Could not read the dedicated IP state")
        await callback.answer()
        return

    if not is_active_ultra_billing_subscription(subscription):
        await callback.answer(text=i18n.get("msg-dedicated-ip-not-ultra"), show_alert=True)
        return

    if chosen is not None:
        await callback.answer(text=i18n.get("msg-dedicated-ip-already", country=chosen.value))
        if isinstance(callback.message, Message):
            await callback.message.edit_reply_markup(reply_markup=None)
        return

    lock_key = DedicatedIpChoiceKey(telegram_id=user.telegram_id).pack()
    if not await redis_client.set(lock_key, "1", nx=True, ex=_LOCK_TTL):
        await callback.answer()
        return

    try:
        await billing.claim_user_reminder(user.telegram_id, KIND, DEDUP_KEY)
        stored = await billing.answer_user_reminder(
            user.telegram_id, KIND, DEDUP_KEY, country.value
        )
    except Exception:
        logger.opt(exception=True).warning(f"{log(user)} Could not store the dedicated IP country")
        await redis_client.delete(lock_key)
        await callback.answer()
        return

    if not stored:
        logger.warning(f"{log(user)} Dedicated IP answer was not stored")
        await redis_client.delete(lock_key)
        await callback.answer()
        return

    DEDICATED_IP_CHOSEN_TOTAL.labels(country=country.value).inc()
    logger.info(f"{log(user)} Chose the dedicated IP country: {country.value}")

    await _post_card(callback.bot, config, user, subscription.ID, country)

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            text=i18n.get("ntf-dedicated-ip-accepted"), reply_markup=None
        )

    await callback.answer()
