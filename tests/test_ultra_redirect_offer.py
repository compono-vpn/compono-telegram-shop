from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.infrastructure.billing import BillingClient
from src.infrastructure.kafka.consumer import UserNotificationConsumer
from src.services.notification import NotificationService
from src.services.user import UserService


def _consumer(billing, user_service, notification_service) -> UserNotificationConsumer:
    consumer = UserNotificationConsumer(MagicMock(), MagicMock())
    deps = {
        BillingClient: billing,
        UserService: user_service,
        NotificationService: notification_service,
    }

    @asynccontextmanager
    async def container():
        rc = MagicMock()
        rc.get = AsyncMock(side_effect=lambda t: deps[t])
        yield rc

    consumer._container = container
    consumer._start_redirect = AsyncMock()
    return consumer


async def test_paid_subscription_redirect_offers_the_ultra_country():
    billing = MagicMock()
    billing.get_current_subscription = AsyncMock(
        return_value=SimpleNamespace(Plan=SimpleNamespace(tag="ULTRA"))
    )
    user = SimpleNamespace(telegram_id=123)
    user_service = MagicMock(get=AsyncMock(return_value=user))
    notification_service = MagicMock()
    consumer = _consumer(billing, user_service, notification_service)

    with patch(
        "src.infrastructure.kafka.consumer.offer_country_choice", new=AsyncMock(return_value=True)
    ) as offer:
        await consumer._handle_redirect(
            123, {"redirect_to": "subscription_success", "purchase_type": "NEW"}
        )

    offer.assert_awaited_once_with(
        user=user, plan_tag="ULTRA", billing=billing, notification_service=notification_service
    )


async def test_proxy_redirect_does_not_offer_the_country():
    consumer = _consumer(MagicMock(), MagicMock(), MagicMock())
    with patch("src.infrastructure.kafka.consumer.offer_country_choice", new=AsyncMock()) as offer:
        await consumer._handle_redirect(123, {"redirect_to": "proxy_success"})
    offer.assert_not_awaited()
