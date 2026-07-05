"""Tests wiring the cancel-reason survey into payment-link creation
(BDT-442 foundation): every payment link created via
_create_payment_and_get_data must be tracked in the cancel-survey pending
Redis sorted set so the 5-min sweep can later detect a cancellation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from src.bot.routers.subscription.handlers import _create_payment_and_get_data
from src.core.constants import USER_KEY
from src.core.enums import PaymentGatewayType, PurchaseType
from src.core.storage.keys import PendingCancelSurveyChecksKey
from src.models.dto import PlanDto
from src.models.dto.plan import PlanDurationDto
from tests.conftest import make_dialog_manager, make_user


def _plan_with_duration(days: int = 30) -> PlanDto:
    return PlanDto(id=7, name="Pro", durations=[PlanDurationDto(id=1, days=days, prices=[])])


def _dm(plan: PlanDto, telegram_id: int = 777) -> MagicMock:
    dm = make_dialog_manager()
    dm.middleware_data[USER_KEY] = make_user(telegram_id=telegram_id)
    dm.dialog_data["purchase_type"] = PurchaseType.NEW
    return dm


def _make_billing(payment_id: str = "3fa85f64-5717-4562-b3fc-2c963f66afa6") -> AsyncMock:
    billing = AsyncMock()
    billing.get_gateway_by_type.return_value = MagicMock(Currency="RUB")
    billing.create_payment.return_value = MagicMock(ID=payment_id, URL="https://pay.example/1")
    billing.calculate_price.return_value = MagicMock(
        original_amount="119", discount_percent=0, final_amount="119"
    )
    return billing


class TestCreatePaymentSchedulesCancelSurveyCheck:
    async def test_schedules_check_on_successful_payment_creation(self):
        plan = _plan_with_duration()
        dm = _dm(plan)
        billing = _make_billing()
        notification_service = AsyncMock()
        redis_client = AsyncMock()

        result = await _create_payment_and_get_data(
            dialog_manager=dm,
            plan=plan,
            duration_days=30,
            gateway_type=PaymentGatewayType.PLATEGA,
            billing=billing,
            notification_service=notification_service,
            redis_client=redis_client,
        )

        assert result is not None
        redis_client.zadd.assert_awaited_once()
        key, members = redis_client.zadd.call_args[0]
        assert key == PendingCancelSurveyChecksKey().pack()
        (member,) = members.keys()
        assert member.startswith("3fa85f64-5717-4562-b3fc-2c963f66afa6:777:PLATEGA:")

    async def test_does_not_schedule_when_duration_is_missing(self):
        plan = _plan_with_duration(days=30)
        dm = _dm(plan)
        billing = _make_billing()
        notification_service = AsyncMock()
        redis_client = AsyncMock()

        result = await _create_payment_and_get_data(
            dialog_manager=dm,
            plan=plan,
            duration_days=9999,
            gateway_type=PaymentGatewayType.PLATEGA,
            billing=billing,
            notification_service=notification_service,
            redis_client=redis_client,
        )

        assert result is None
        redis_client.zadd.assert_not_awaited()
        billing.create_payment.assert_not_awaited()
