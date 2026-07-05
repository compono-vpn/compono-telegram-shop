import time
from typing import Any, Union
from uuid import UUID

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from fluentogram import TranslatorRunner
from loguru import logger
from redis.asyncio import Redis

from src.core.constants import CANCEL_SURVEY_PREFIX, CONTAINER_KEY
from src.core.enums import CancelSurveyReason
from src.core.metrics import CANCEL_SURVEY_ANSWERS_TOTAL
from src.core.storage.keys import CancelSurveyAnswerKey, CancelSurveyAwaitingTextKey
from src.core.utils.formatters import format_user_log as log
from src.core.utils.message_payload import MessagePayload
from src.infrastructure.billing import BillingClient
from src.models.dto import UserDto
from src.services.experiment import ExperimentFeature, ExperimentService
from src.services.notification import NotificationService

router = Router(name=__name__)

_ANSWER_TTL = 90 * 24 * 60 * 60
_AWAITING_TEXT_TTL = 30 * 60


def _resolve_survey_experiment_key() -> str:
    return ExperimentFeature.PAYMENT_RESCUE.value


_SURVEY_EXPERIMENT_KEY = _resolve_survey_experiment_key()


def _parse_cancel_survey_payload(payload: str) -> tuple[str, str] | None:
    payment_id, _, reason_value = payload.partition(":")
    if not payment_id or not reason_value:
        return None
    return payment_id, reason_value


class AwaitingCancelSurveyText(BaseFilter):
    async def __call__(self, message: Message, **data: Any) -> Union[bool, dict[str, str]]:
        if not message.from_user:
            return False

        container = data[CONTAINER_KEY]
        redis_client: Redis = await container.get(Redis)
        key = CancelSurveyAwaitingTextKey(telegram_id=message.from_user.id)
        raw_payment_id = await redis_client.get(key.pack())

        if not raw_payment_id:
            return False

        payment_id = (
            raw_payment_id.decode() if isinstance(raw_payment_id, bytes) else raw_payment_id
        )
        return {"cancel_survey_payment_id": payment_id}


async def _resolve_gateway(billing: BillingClient, payment_id: str) -> str:
    try:
        transaction = await billing.get_transaction(UUID(payment_id))
    except ValueError:
        return "UNKNOWN"
    return transaction.GatewayType if transaction else "UNKNOWN"


def _track_survey_event(
    *,
    experiment_service: ExperimentService,
    user: UserDto,
    event: str,
) -> None:
    try:
        experiment_service.record_conversion(
            _SURVEY_EXPERIMENT_KEY,
            user.telegram_id,
            event,
            created_at=user.created_at,
        )
    except TypeError:
        experiment_service.record_conversion(_SURVEY_EXPERIMENT_KEY, user.telegram_id, event)


def _track_rescue_clicked(
    *,
    experiment_service: ExperimentService,
    user: UserDto,
) -> None:
    _track_survey_event(
        experiment_service=experiment_service,
        user=user,
        event="rescue_clicked",
    )


@inject
@router.callback_query(F.data.startswith(CANCEL_SURVEY_PREFIX))
async def on_cancel_survey_answer(
    callback: CallbackQuery,
    user: UserDto,
    i18n: FromDishka[TranslatorRunner],
    billing: FromDishka[BillingClient],
    redis_client: FromDishka[Redis],
    experiment_service: FromDishka[ExperimentService],
) -> None:
    if not callback.data:
        await callback.answer()
        return

    payload = callback.data.removeprefix(CANCEL_SURVEY_PREFIX)
    payload_data = _parse_cancel_survey_payload(payload)
    if not payload_data:
        logger.warning(f"{log(user)} Malformed cancel-survey callback payload '{payload}'")
        await callback.answer()
        return

    payment_id, reason_value = payload_data
    try:
        reason = CancelSurveyReason(reason_value)
    except ValueError:
        logger.warning(f"{log(user)} Unknown cancel-survey reason '{reason_value}'")
        _track_rescue_clicked(experiment_service=experiment_service, user=user)
        await callback.answer()
        return

    try:
        payment_uuid = UUID(payment_id)
    except ValueError:
        logger.warning(f"{log(user)} Invalid cancel-survey payment id '{payment_id}'")
        _track_rescue_clicked(experiment_service=experiment_service, user=user)
        await callback.answer()
        return

    answer_key = CancelSurveyAnswerKey(payment_id=payment_uuid)

    if await redis_client.exists(answer_key.pack()):
        _track_rescue_clicked(experiment_service=experiment_service, user=user)
        await callback.answer(text=i18n.get("msg-cancel-survey-already-answered"))
        return

    _track_rescue_clicked(experiment_service=experiment_service, user=user)

    if reason == CancelSurveyReason.OTHER:
        awaiting_key = CancelSurveyAwaitingTextKey(telegram_id=user.telegram_id)
        await redis_client.set(awaiting_key.pack(), payment_id, ex=_AWAITING_TEXT_TTL)

        if isinstance(callback.message, Message):
            await callback.message.edit_text(
                text=i18n.get("msg-cancel-survey-other-prompt"),
                reply_markup=None,
            )

        await callback.answer()
        return

    gateway = await _resolve_gateway(billing, payment_id)

    await redis_client.hset(  # type: ignore[misc]
        answer_key.pack(),
        mapping={
            "telegram_id": user.telegram_id,
            "gateway": gateway,
            "reason": reason.value,
            "answered_at": time.time(),
        },
    )
    await redis_client.expire(answer_key.pack(), _ANSWER_TTL)
    CANCEL_SURVEY_ANSWERS_TOTAL.labels(reason=reason.value, gateway=gateway).inc()
    _track_survey_event(
        experiment_service=experiment_service,
        user=user,
        event="cancel_reason_selected",
    )
    logger.info(f"{log(user)} Answered cancel-reason survey '{payment_id}' with '{reason.value}'")

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            text=i18n.get("msg-cancel-survey-thanks"),
            reply_markup=None,
        )

    await callback.answer()


@inject
@router.message(AwaitingCancelSurveyText())
async def on_cancel_survey_other_text(
    message: Message,
    user: UserDto,
    cancel_survey_payment_id: str,
    i18n: FromDishka[TranslatorRunner],
    billing: FromDishka[BillingClient],
    notification_service: FromDishka[NotificationService],
    redis_client: FromDishka[Redis],
    experiment_service: FromDishka[ExperimentService],
) -> None:
    payment_id = cancel_survey_payment_id
    awaiting_key = CancelSurveyAwaitingTextKey(telegram_id=user.telegram_id)
    try:
        payment_uuid = UUID(payment_id)
    except ValueError:
        logger.warning(f"{log(user)} Invalid cancel-survey free-text payment id '{payment_id}'")
        await redis_client.delete(awaiting_key.pack())
        return

    answer_key = CancelSurveyAnswerKey(payment_id=payment_uuid)

    if await redis_client.exists(answer_key.pack()):
        await redis_client.delete(awaiting_key.pack())
        return

    other_text = (message.text or message.caption or "").strip()
    if not other_text:
        return

    gateway = await _resolve_gateway(billing, payment_id)

    await redis_client.hset(  # type: ignore[misc]
        answer_key.pack(),
        mapping={
            "telegram_id": user.telegram_id,
            "gateway": gateway,
            "reason": CancelSurveyReason.OTHER.value,
            "other_text": other_text,
            "answered_at": time.time(),
        },
    )
    await redis_client.expire(answer_key.pack(), _ANSWER_TTL)
    await redis_client.delete(awaiting_key.pack())
    CANCEL_SURVEY_ANSWERS_TOTAL.labels(reason=CancelSurveyReason.OTHER.value, gateway=gateway).inc()

    _track_survey_event(
        experiment_service=experiment_service,
        user=user,
        event="cancel_reason_selected",
    )

    logger.info(f"{log(user)} Free-text cancel-survey answer for '{payment_id}'")

    await notification_service.notify_super_dev(
        payload=MessagePayload.not_deleted(
            i18n_key="ntf-event-cancel-survey-other",
            i18n_kwargs={
                "user_id": str(user.telegram_id),
                "user_name": user.name,
                "username": user.username or False,
                "gateway": gateway,
                "text": other_text,
            },
        ),
    )

    await message.answer(text=i18n.get("msg-cancel-survey-thanks"))
