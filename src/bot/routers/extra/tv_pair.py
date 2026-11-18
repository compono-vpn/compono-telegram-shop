"""Buttons of the TV pairing confirmation (COM-202).

``tvp:<CODE>`` claims the code for the user who tapped it (compono-api decides whether
their subscription may be used); ``tvx`` drops the question. The full code is never
logged.
"""

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from fluentogram import TranslatorRunner
from loguru import logger

from src.bot.middlewares.error import is_stale_callback_error
from src.bot.routers.extra.checkout_entry import open_checkout
from src.bot.states import Subscription
from src.core.constants import TV_PAIR_CANCEL, TV_PAIR_CONFIRM_PREFIX
from src.core.enums import PurchaseType
from src.core.metrics import TV_PAIR_TOTAL
from src.core.utils.formatters import format_user_log as log
from src.infrastructure.api import ApiClient, TvPairClaim
from src.models.dto import UserDto
from src.services.tv_pair import code_from_callback, display_code, log_code, retry_keyboard

router = Router(name=__name__)


async def _edit(callback: CallbackQuery, text: str, reply_markup=None) -> None:  # noqa: ANN001
    if not isinstance(callback.message, Message):
        return
    try:
        await callback.message.edit_text(text=text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        # A repeated tap with the same outcome (tapping «Подключить» again while still
        # without a subscription, or a double tap) leaves the message unchanged, and
        # Telegram refuses the edit. The message already says the right thing.
        if "message is not modified" not in str(e).lower():
            raise


async def _answer(callback: CallbackQuery, user: UserDto, alert: str | None = None) -> None:
    """Answer the tap. The claim can outlast the time Telegram keeps a callback query
    answerable (compono-api waits up to 15 s for billing, the bot up to 30 s for the API),
    and then Telegram refuses the answer as "query is too old". A late answer must not stop
    the handler (the plan list still has to open), and a late alert must still reach the
    user, as a chat message (QA round 4).
    """
    try:
        if alert is None:
            await callback.answer()
        else:
            await callback.answer(text=alert, show_alert=True)
    except TelegramBadRequest as e:
        if not is_stale_callback_error(e):
            raise
        logger.warning(f"{log(user)} TV pairing: tap answered too late for Telegram")
        if alert is None:
            return
        if isinstance(callback.message, Message):
            await callback.message.answer(text=alert)
        elif callback.bot is not None:
            await callback.bot.send_message(chat_id=user.telegram_id, text=alert)


async def _send_no_subscription(
    callback: CallbackQuery, user: UserDto, code: str, i18n: TranslatorRunner
) -> None:
    text = i18n.get("msg-tv-pair-no-subscription", code=display_code(code))
    markup = retry_keyboard(code, i18n.get("btn-tv-pair-retry"))
    if isinstance(callback.message, Message):
        await callback.message.answer(text=text, reply_markup=markup)
        return
    if callback.bot is not None:
        await callback.bot.send_message(chat_id=user.telegram_id, text=text, reply_markup=markup)


@inject
@router.callback_query(F.data.startswith(TV_PAIR_CONFIRM_PREFIX))
async def on_tv_pair_confirm(
    callback: CallbackQuery,
    user: UserDto,
    dialog_manager: DialogManager,
    i18n: FromDishka[TranslatorRunner],
    api_client: FromDishka[ApiClient],
) -> None:
    code = code_from_callback(callback.data)
    if code is None:
        logger.warning(f"{log(user)} Malformed TV pairing button")
        await _answer(callback, user)
        return

    result = await api_client.claim_tv_pair(code, user.telegram_id)
    TV_PAIR_TOTAL.labels(result=result.value).inc()
    logger.info(f"{log(user)} TV pairing claim code={log_code(code)} result={result.value}")

    if result is TvPairClaim.ATTACHED:
        await _edit(callback, i18n.get("msg-tv-pair-attached"))
        await _answer(callback, user)
        return
    if result is TvPairClaim.NO_SUBSCRIPTION:
        # The code stays valid until it expires: send the explanation with a retry button
        # as a NEW message, then open the plan list so the user can buy and tap again.
        # It must not be an edit of the tapped message: the plan list opens with
        # DELETE_AND_SEND, and aiogram-dialog deletes the message the callback came from,
        # which would take the explanation and the retry button with it (QA round 1).
        await _send_no_subscription(callback, user, code, i18n)
        await _answer(callback, user)
        await open_checkout(
            dialog_manager, state=Subscription.PLANS, purchase_type=PurchaseType.NEW
        )
        return
    if result is TvPairClaim.NOT_FOUND:
        await _edit(callback, i18n.get("msg-tv-pair-expired"))
        await _answer(callback, user)
        return
    if result is TvPairClaim.ALREADY_CLAIMED:
        await _edit(callback, i18n.get("msg-tv-pair-used"))
        await _answer(callback, user)
        return
    if result is TvPairClaim.RATE_LIMITED:
        await _answer(callback, user, i18n.get("msg-tv-pair-rate-limited"))
        return
    # Network error, 5xx, 401...: keep the buttons so the user can try again.
    await _answer(callback, user, i18n.get("msg-tv-pair-failed"))


@inject
@router.callback_query(F.data == TV_PAIR_CANCEL)
async def on_tv_pair_cancel(
    callback: CallbackQuery,
    user: UserDto,
    i18n: FromDishka[TranslatorRunner],
) -> None:
    TV_PAIR_TOTAL.labels(result="cancelled").inc()
    logger.info(f"{log(user)} Cancelled a TV pairing question")
    await _edit(callback, i18n.get("msg-tv-pair-cancelled"))
    await callback.answer()
