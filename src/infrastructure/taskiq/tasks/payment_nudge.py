from dishka.integrations.taskiq import FromDishka, inject
from redis.asyncio import Redis

from src.infrastructure.billing import BillingClient
from src.infrastructure.taskiq.broker import broker
from src.services.notification import NotificationService
from src.services.payment_nudge import process_due_payment_nudges
from src.services.user import UserService


@broker.task(schedule=[{"cron": "* * * * *"}], retry_on_error=False)
@inject
async def process_pending_payment_nudges_task(
    billing: FromDishka[BillingClient],
    user_service: FromDishka[UserService],
    notification_service: FromDishka[NotificationService],
    redis_client: FromDishka[Redis],
) -> None:
    await process_due_payment_nudges(
        redis_client=redis_client,
        billing=billing,
        user_service=user_service,
        notification_service=notification_service,
    )
