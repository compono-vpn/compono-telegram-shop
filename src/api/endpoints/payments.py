import time
import traceback

from aiogram.utils.formatting import Text
from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Request, Response, status
from loguru import logger
from redis.asyncio import Redis

from src.core.constants import API_V1, PAYMENTS_WEBHOOK_PATH
from src.core.enums import PaymentGatewayType
from src.core.metrics import PAYMENT_WEBHOOK_ERRORS_TOTAL, PAYMENT_WEBHOOK_PROCESSING_TIME
from src.core.utils.message_payload import MessagePayload
from src.infrastructure.database import UnitOfWork
from src.infrastructure.database.models.sql import WebhookLog
from src.infrastructure.taskiq.tasks.payments import handle_payment_transaction_task
from src.services.notification import NotificationService
from src.services.payment_gateway import PaymentGatewayService

router = APIRouter(prefix=API_V1 + PAYMENTS_WEBHOOK_PATH)

# Redis key TTL for webhook deduplication (10 minutes)
_WEBHOOK_DEDUP_TTL = 600


@router.post("/{gateway_type}")
@inject
async def payments_webhook(
    gateway_type: str,
    request: Request,
    payment_gateway_service: FromDishka[PaymentGatewayService],
    notification_service: FromDishka[NotificationService],
    uow: FromDishka[UnitOfWork],
    redis_client: FromDishka[Redis],
) -> Response:
    start = time.monotonic()
    log_id: int | None = None

    # Read body early so it's cached for both logging and gateway.handle_webhook
    await request.body()
    payload: dict | None = None
    try:
        payload = await request.json()
    except Exception:
        # Body might be empty, form-encoded, or otherwise not JSON — that's fine
        pass

    # Persist the webhook log immediately so it survives crashes
    try:
        async with uow:
            webhook_log = await uow.repository.webhook_logs.create(
                WebhookLog(
                    gateway_type=gateway_type,
                    payload=payload,
                    status_code=0,
                )
            )
            log_id = webhook_log.id
    except Exception:
        logger.exception("Failed to persist initial webhook log")

    try:
        gateway_enum = PaymentGatewayType(gateway_type.upper())
    except ValueError:
        logger.exception(f"Invalid gateway type received: '{gateway_type}'")
        if log_id is not None:
            await _update_log(uow, log_id, status_code=404, error=f"Invalid gateway type: {gateway_type}")
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    try:
        gateway = await payment_gateway_service._get_gateway_instance(gateway_enum)

        if not gateway.data.is_active:
            logger.warning(f"Webhook received for disabled payment gateway {gateway_enum}")
            if log_id is not None:
                await _update_log(uow, log_id, status_code=404, error="Gateway is disabled")
            return Response(status_code=status.HTTP_404_NOT_FOUND)

        payment_id, payment_status = await gateway.handle_webhook(request)

        # Deduplicate: only enqueue the task if this payment_id hasn't been
        # processed in the last _WEBHOOK_DEDUP_TTL seconds.  SET NX ensures
        # only the first webhook delivery wins; duplicates get 200 but skip
        # the task enqueue entirely.
        dedup_key = f"webhook:dedup:{payment_id}:{payment_status.value}"
        is_first = await redis_client.set(dedup_key, "1", nx=True, ex=_WEBHOOK_DEDUP_TTL)

        if is_first:
            await handle_payment_transaction_task.kiq(payment_id, payment_status)
            logger.info(f"Webhook enqueued for payment '{payment_id}' status='{payment_status}'")
        else:
            logger.warning(
                f"Duplicate webhook for payment '{payment_id}' status='{payment_status}', "
                f"skipping task enqueue"
            )

        if log_id is not None:
            await _update_log(uow, log_id, status_code=200, payment_id=payment_id)

        return Response(status_code=status.HTTP_200_OK)

    except Exception as exception:
        PAYMENT_WEBHOOK_ERRORS_TOTAL.labels(gateway_type=gateway_type).inc()
        logger.exception(f"Error processing webhook for '{gateway_type}': {exception}")
        traceback_str = traceback.format_exc()
        error_type_name = type(exception).__name__
        error_message = Text(str(exception)[:512])

        if log_id is not None:
            await _update_log(
                uow, log_id, status_code=500, error=f"{error_type_name}: {exception}"
            )

        await notification_service.error_notify(
            traceback_str=traceback_str,
            payload=MessagePayload.not_deleted(
                i18n_key="ntf-event-error",
                i18n_kwargs={
                    "user": False,
                    "error": f"{error_type_name}: {error_message.as_html()}",
                },
            ),
        )

        return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        duration = time.monotonic() - start
        PAYMENT_WEBHOOK_PROCESSING_TIME.labels(gateway_type=gateway_type).observe(duration)


async def _update_log(uow: UnitOfWork, log_id: int, **data) -> None:
    try:
        async with uow:
            await uow.repository.webhook_logs.update(log_id, **data)
    except Exception:
        logger.exception(f"Failed to update webhook log {log_id}")
