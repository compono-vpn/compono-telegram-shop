import time
from uuid import UUID

from dishka.integrations.taskiq import FromDishka, inject
from loguru import logger
from redis.asyncio import Redis

from src.bot.keyboards import get_cancel_survey_keyboard
from src.core.enums import TransactionStatus
from src.core.metrics import CANCEL_SURVEY_SENT_TOTAL
from src.core.storage.keys import CancelSurveySentKey, PendingCancelSurveyChecksKey
from src.core.utils.message_payload import MessagePayload
from src.infrastructure.billing import BillingClient
from src.infrastructure.taskiq.broker import broker
from src.services.notification import NotificationService
from src.services.user import UserService

_PENDING_KEY = PendingCancelSurveyChecksKey()
_PING_DELAY_SECONDS = 15 * 60
_MAX_PENDING_AGE = 48 * 60 * 60
_SENT_TTL = 90 * 24 * 60 * 60


async def schedule_cancel_survey_check(
    redis_client: Redis,
    payment_id: str,
    telegram_id: int,
    gateway_type: str,
) -> None:
    created_at = time.time()
    check_at = created_at + _PING_DELAY_SECONDS
    member = f"{payment_id}:{telegram_id}:{gateway_type}:{created_at}"
    await redis_client.zadd(_PENDING_KEY.pack(), {member: check_at}, nx=True)
    logger.debug(f"Scheduled cancel-survey check for payment '{payment_id}'")


async def _has_paid_since(billing: BillingClient, telegram_id: int) -> bool:
    subscription = await billing.get_current_subscription(telegram_id)
    return bool(subscription and subscription.Status == "ACTIVE" and not subscription.IsTrial)


async def _process_due_member(
    member: str,
    now: float,
    billing: BillingClient,
    user_service: UserService,
    notification_service: NotificationService,
    redis_client: Redis,
) -> None:
    key = _PENDING_KEY.pack()
    payment_id, telegram_id_str, gateway_type, created_at_str = member.split(":", 3)
    telegram_id = int(telegram_id_str)
    created_at = float(created_at_str)

    try:
        transaction = await billing.get_transaction(UUID(payment_id))
    except ValueError:
        logger.warning(f"Skipping cancel-survey check: invalid payment id '{payment_id}'")
        return

    if not transaction:
        logger.debug(f"Skipping cancel-survey check for '{payment_id}': transaction not found")
        return

    if transaction.Status == TransactionStatus.PENDING.value:
        if now - created_at < _MAX_PENDING_AGE:
            await redis_client.zadd(key, {member: created_at}, nx=True)
        else:
            logger.debug(
                f"Giving up on cancel-survey check for '{payment_id}': "
                f"still pending after '{_MAX_PENDING_AGE}' seconds"
            )
        return

    if transaction.Status != TransactionStatus.CANCELED.value:
        return

    if await _has_paid_since(billing, telegram_id):
        logger.debug(
            f"Skipping cancel-survey for '{payment_id}': "
            f"user '{telegram_id}' already has a paid subscription"
        )
        return

    sent_key = CancelSurveySentKey(payment_id=UUID(payment_id))
    was_scheduled = await redis_client.set(sent_key.pack(), "1", nx=True, ex=_SENT_TTL)
    if not was_scheduled:
        return

    user = await user_service.get(telegram_id)
    if not user:
        logger.debug(f"Skipping cancel-survey for '{payment_id}': user '{telegram_id}' not found")
        return

    logger.info(f"Sending cancel-reason survey to '{telegram_id}' for payment '{payment_id}'")

    await notification_service.notify_user(
        user=user,
        payload=MessagePayload(
            i18n_key="ntf-event-cancel-survey-prompt",
            reply_markup=get_cancel_survey_keyboard(payment_id),
            auto_delete_after=None,
            add_close_button=False,
        ),
    )
    CANCEL_SURVEY_SENT_TOTAL.labels(gateway=gateway_type).inc()


@broker.task(schedule=[{"cron": "*/5 * * * *"}], retry_on_error=False)
@inject
async def process_pending_cancel_survey_checks_task(
    billing: FromDishka[BillingClient],
    user_service: FromDishka[UserService],
    notification_service: FromDishka[NotificationService],
    redis_client: FromDishka[Redis],
) -> None:
    now = time.time()
    key = _PENDING_KEY.pack()

    due_items: list[bytes] = await redis_client.zrangebyscore(key, "-inf", now)
    if not due_items:
        return

    logger.info(f"Processing {len(due_items)} pending cancel-survey checks")

    for raw_member in due_items:
        member = raw_member.decode() if isinstance(raw_member, bytes) else raw_member
        await redis_client.zrem(key, member)
        await _process_due_member(
            member, now, billing, user_service, notification_service, redis_client
        )

