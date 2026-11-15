from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from fluentogram import TranslatorRunner
from loguru import logger
from redis.asyncio import Redis

from src.core.constants import SOURCE_SURVEY_PREFIX
from src.core.enums import SourceSurveyAnswer, SystemNotificationType
from src.core.metrics import SOURCE_SURVEY_ANSWERS_TOTAL
from src.core.storage.keys import SourceSurveyAnsweredKey
from src.core.utils.formatters import format_user_log as log
from src.core.utils.message_payload import MessagePayload
from src.infrastructure.billing import BillingClient
from src.models.dto import UserDto
from src.services.notification import NotificationService
from src.services.source_survey import DEDUP_KEY, KIND

router = Router(name=__name__)

_ANSWERED_TTL = 90 * 24 * 60 * 60


async def _notify_admins(
    notification_service: NotificationService,
    user: UserDto,
    answer: SourceSurveyAnswer,
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

    await _notify_admins(notification_service, user, answer)

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            text=i18n.get("msg-source-survey-thanks"), reply_markup=None
        )

    await callback.answer()
