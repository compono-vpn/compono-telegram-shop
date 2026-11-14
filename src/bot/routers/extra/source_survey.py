import html
from typing import Any, Union

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from fluentogram import TranslatorRunner
from loguru import logger
from redis.asyncio import Redis

from src.core.constants import CONTAINER_KEY, SOURCE_SURVEY_PREFIX
from src.core.enums import SourceSurveyAnswer, SystemNotificationType
from src.core.metrics import SOURCE_SURVEY_ANSWERS_TOTAL
from src.core.storage.keys import SourceSurveyAnsweredKey, SourceSurveyAwaitingTextKey
from src.core.utils.formatters import format_user_log as log
from src.core.utils.message_payload import MessagePayload
from src.infrastructure.billing import BillingClient
from src.models.dto import UserDto
from src.services.notification import NotificationService
from src.services.source_survey import DEDUP_KEY, KIND, sanitize_free_text

router = Router(name=__name__)

_ANSWERED_TTL = 90 * 24 * 60 * 60
_AWAITING_TEXT_TTL = 30 * 60


class AwaitingSourceSurveyText(BaseFilter):
    async def __call__(self, message: Message, **data: Any) -> Union[bool, dict[str, Any]]:
        if not message.from_user:
            return False

        container = data[CONTAINER_KEY]
        redis_client: Redis = await container.get(Redis)
        key = SourceSurveyAwaitingTextKey(telegram_id=message.from_user.id).pack()
        if not await redis_client.get(key):
            return False

        if (message.text or "").startswith("/"):
            await redis_client.delete(key)
            return False

        return True


async def _notify_admins(
    notification_service: NotificationService,
    user: UserDto,
    answer: SourceSurveyAnswer,
    text: str,
) -> None:
    try:
        await notification_service.system_notify(
            ntf_type=SystemNotificationType.USER_REGISTERED,
            payload=MessagePayload.not_deleted(
                i18n_key="ntf-event-source-survey",
                i18n_kwargs={
                    "user_id": str(user.telegram_id),
                    "user_name": user.name,
                    "username": user.username or False,
                    "answer": answer.value,
                    "text": html.escape(text) if text else False,
                },
            ),
        )
    except Exception:
        logger.opt(exception=True).warning(f"{log(user)} Could not post the source survey event")


@inject
@router.callback_query(F.data.startswith(SOURCE_SURVEY_PREFIX))
async def on_source_survey_answer(
    callback: CallbackQuery,
    user: UserDto,
    i18n: FromDishka[TranslatorRunner],
    billing: FromDishka[BillingClient],
    redis_client: FromDishka[Redis],
    notification_service: FromDishka[NotificationService],
) -> None:
    try:
        answer = SourceSurveyAnswer((callback.data or "").removeprefix(SOURCE_SURVEY_PREFIX))
    except ValueError:
        logger.warning(f"{log(user)} Unknown source survey callback '{callback.data}'")
        await callback.answer()
        return

    answered_key = SourceSurveyAnsweredKey(telegram_id=user.telegram_id).pack()
    if not await redis_client.set(answered_key, "1", nx=True, ex=_ANSWERED_TTL):
        await callback.answer(text=i18n.get("msg-source-survey-already-answered"))
        return

    try:
        stored = await billing.answer_user_reminder(user.telegram_id, KIND, DEDUP_KEY, answer.value)
    except Exception:
        logger.opt(exception=True).warning(f"{log(user)} Could not store the source survey answer")
        await redis_client.delete(answered_key)
        await callback.answer()
        return

    if not stored:
        logger.warning(f"{log(user)} Source survey answer without a sent survey")
        await redis_client.delete(answered_key)
        await callback.answer()
        return

    SOURCE_SURVEY_ANSWERS_TOTAL.labels(answer=answer.value).inc()
    logger.info(f"{log(user)} Answered the source survey: {answer.value}")

    if answer is SourceSurveyAnswer.OTHER:
        awaiting_key = SourceSurveyAwaitingTextKey(telegram_id=user.telegram_id).pack()
        await redis_client.set(awaiting_key, "1", ex=_AWAITING_TEXT_TTL)
        text_key = "msg-source-survey-other-prompt"
    else:
        await _notify_admins(notification_service, user, answer, "")
        text_key = "msg-source-survey-thanks"

    if isinstance(callback.message, Message):
        await callback.message.edit_text(text=i18n.get(text_key), reply_markup=None)

    await callback.answer()


@inject
@router.message(AwaitingSourceSurveyText())
async def on_source_survey_other_text(
    message: Message,
    user: UserDto,
    i18n: FromDishka[TranslatorRunner],
    billing: FromDishka[BillingClient],
    notification_service: FromDishka[NotificationService],
    redis_client: FromDishka[Redis],
) -> None:
    if not message.text:
        return

    text = sanitize_free_text(message.text)

    try:
        await billing.answer_user_reminder(
            user.telegram_id, KIND, DEDUP_KEY, SourceSurveyAnswer.OTHER.value, text
        )
    except Exception:
        logger.opt(exception=True).warning(f"{log(user)} Could not store the source survey text")
        return

    await redis_client.delete(SourceSurveyAwaitingTextKey(telegram_id=user.telegram_id).pack())
    logger.info(f"{log(user)} Added free text to the source survey answer")

    if text:
        await _notify_admins(notification_service, user, SourceSurveyAnswer.OTHER, text)

    await message.answer(text=i18n.get("msg-source-survey-thanks"))
