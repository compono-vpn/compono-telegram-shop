"""Buttons of the TV pairing confirmation (COM-202).

``tvp:<CODE>`` claims the code for the user who tapped it (compono-api decides whether
their subscription may be used); ``tvx`` drops the question. The full code is never
logged.
"""

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from fluentogram import TranslatorRunner
from loguru import logger

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
    if isinstance(callback.message, Message):
        await callback.message.edit_text(text=text, reply_markup=reply_markup)


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
        await callback.answer()
        return

    result = await api_client.claim_tv_pair(code, user.telegram_id)
    TV_PAIR_TOTAL.labels(result=result.value).inc()
    logger.info(f"{log(user)} TV pairing claim code={log_code(code)} result={result.value}")

    if result is TvPairClaim.ATTACHED:
        await _edit(callback, i18n.get("msg-tv-pair-attached"))
        await callback.answer()
        return
    if result is TvPairClaim.NO_SUBSCRIPTION:
        # The code stays valid until it expires: keep a retry button on the question
        # and open the plan list so the user can buy, then tap again.
        await _edit(
            callback,
            i18n.get("msg-tv-pair-no-subscription", code=display_code(code)),
            reply_markup=retry_keyboard(code, i18n.get("btn-tv-pair-retry")),
        )
        await callback.answer()
        await open_checkout(
            dialog_manager, state=Subscription.PLANS, purchase_type=PurchaseType.NEW
        )
        return
    if result is TvPairClaim.NOT_FOUND:
        await _edit(callback, i18n.get("msg-tv-pair-expired"))
        await callback.answer()
        return
    if result is TvPairClaim.ALREADY_CLAIMED:
        await _edit(callback, i18n.get("msg-tv-pair-used"))
        await callback.answer()
        return
    if result is TvPairClaim.RATE_LIMITED:
        await callback.answer(text=i18n.get("msg-tv-pair-rate-limited"), show_alert=True)
        return
    # Network error, 5xx, 401...: keep the buttons so the user can try again.
    await callback.answer(text=i18n.get("msg-tv-pair-failed"), show_alert=True)


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
