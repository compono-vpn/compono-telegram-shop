from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from fluentogram import TranslatorRunner
from loguru import logger

from src.bot.keyboards import get_buy_keyboard, get_setup_reminder_keyboard
from src.core.config import AppConfig
from src.core.constants import SETUP_CHECKIN_PREFIX
from src.core.enums import SetupCheckinAnswer
from src.core.metrics import SETUP_CHECKIN_ANSWERS_TOTAL
from src.core.utils.formatters import format_user_log as log
from src.core.utils.formatters import i18n_postprocess_text
from src.infrastructure.billing import BillingClient
from src.infrastructure.taskiq.tasks.setup_followups import (
    CHECKIN_DEDUP_KEY,
    KIND_SETUP_CHECKIN,
    support_url,
)
from src.models.dto import UserDto
from src.services.subscription import SubscriptionService

router = Router(name=__name__)


def _translate(markup: InlineKeyboardMarkup, i18n: TranslatorRunner) -> InlineKeyboardMarkup:
    for row in markup.inline_keyboard:
        for button in row:
            button.text = i18n.get(button.text)
    return markup


def parse_checkin_answer(data: str) -> SetupCheckinAnswer | None:
    try:
        return SetupCheckinAnswer(data.removeprefix(SETUP_CHECKIN_PREFIX))
    except ValueError:
        return None


@inject
@router.callback_query(F.data.startswith(SETUP_CHECKIN_PREFIX))
async def on_setup_checkin_answer(
    callback: CallbackQuery,
    user: UserDto,
    i18n: FromDishka[TranslatorRunner],
    billing: FromDishka[BillingClient],
    config: FromDishka[AppConfig],
) -> None:
    answer = parse_checkin_answer(callback.data or "")
    if answer is None:
        logger.warning(f"{log(user)} Unknown setup check-in callback '{callback.data}'")
        await callback.answer()
        return

    try:
        stored = await billing.answer_user_reminder(
            user.telegram_id, KIND_SETUP_CHECKIN, CHECKIN_DEDUP_KEY, answer.value
        )
    except Exception:
        logger.exception(f"{log(user)} Could not store the setup check-in answer")
        await callback.answer()
        return

    if not stored:
        logger.warning(f"{log(user)} Setup check-in answer without a sent check-in")
        await callback.answer()
        return

    SETUP_CHECKIN_ANSWERS_TOTAL.labels(answer=answer.value).inc()
    logger.info(f"{log(user)} Answered the setup check-in: {answer.value}")

    if answer is SetupCheckinAnswer.CONNECTED:
        text_key = "ntf-setup-checkin-connected"
        markup = get_buy_keyboard()
    else:
        text_key = "ntf-setup-checkin-not-connected"
        subscription = user.current_subscription
        connect_url = (
            SubscriptionService.build_connect_url(subscription.url, config.website_url)
            if subscription
            else config.website_url
        )
        markup = get_setup_reminder_keyboard(connect_url, support_url(config))

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            text=i18n_postprocess_text(i18n.get(text_key)),
            reply_markup=_translate(markup, i18n),
            disable_web_page_preview=True,
        )
    await callback.answer()
