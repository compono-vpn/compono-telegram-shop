"""The confirm screen offers only the payment made for the user's current choice.

1. The confirm screen reads the payment (invoice link, price) from dialog data. When billing could
   not create the payment for a new choice, the screen still opened with the previous choice's
   invoice: «Старт, 3 месяца» on the screen, Макс for 1 month in the invoice.
2. The dialog reuses a payment made earlier for the same duration. After billing cancelled it
   (30-60 minutes), every new pick gave the same dead invoice, refused at pre-checkout.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.routers.subscription.handlers import on_duration_select, on_payment_method_select
from src.bot.states import Subscription
from src.core.enums import PaymentGatewayType, PurchaseType
from src.models.dto import PlanDto, PlanDurationDto
from tests.conftest import make_experiment_service, unwrap_inject
from tests.test_stars_only import _billing, _dm, _NoIncentive, _plan, invoice  # noqa: F401

pytestmark = pytest.mark.asyncio

OLD = {
    "payment_id": "11111111-1111-4111-8111-111111111111",
    "payment_url": "https://t.me/$old-max-30",
    "final_pricing": '{"original_amount": "399", "final_amount": "399"}',
}
NEW_ID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"


def _with_previous_payment(dm: MagicMock) -> None:
    dm.dialog_data.update(OLD)
    dm.dialog_data["is_free"] = False


async def _method_select(dm, billing):
    await unwrap_inject(on_payment_method_select)(
        MagicMock(), MagicMock(), dm, PaymentGatewayType.TELEGRAM_STARS, billing,
        make_experiment_service(), _NoIncentive(), AsyncMock(), AsyncMock(),
    )  # fmt: skip


async def _duration_select(dm, billing, days=30):
    await unwrap_inject(on_duration_select)(
        MagicMock(), MagicMock(), dm, days, billing, make_experiment_service(), _NoIncentive(),
        AsyncMock(), AsyncMock(),
    )  # fmt: skip


class TestFailedCreation:
    async def test_method_select_does_not_open_confirm_with_the_previous_invoice(self):
        billing = _billing()
        billing.create_payment.side_effect = RuntimeError("billing unavailable")
        dm = _dm(_plan())
        _with_previous_payment(dm)
        dm.dialog_data["selected_duration"] = 90

        await _method_select(dm, billing)

        dm.switch_to.assert_not_awaited()
        assert dm.dialog_data.get("payment_url") != OLD["payment_url"]
        assert dm.dialog_data.get("payment_id") != OLD["payment_id"]

    async def test_duration_select_drops_the_previous_invoice(self):
        billing = _billing()
        billing.create_payment.side_effect = RuntimeError("billing unavailable")
        dm = _dm(_plan())
        _with_previous_payment(dm)

        await _duration_select(dm, billing)

        assert dm.dialog_data.get("payment_url") != OLD["payment_url"]
        assert dm.switch_to.await_args.kwargs["state"] == Subscription.PAYMENT_METHOD


class TestReuse:
    def _cached(self, dm: MagicMock) -> None:
        dm.dialog_data["payment_cache"] = {"1:NEW:30:TELEGRAM_STARS": dict(OLD)}

    @pytest.mark.parametrize("status", ["CANCELED", "COMPLETED", "FAILED", None])
    async def test_a_payment_billing_will_not_complete_is_replaced(self, status):
        billing = _billing()
        billing.get_transaction.return_value = SimpleNamespace(Status=status) if status else None
        dm = _dm(_plan())
        self._cached(dm)

        await _duration_select(dm, billing)

        billing.create_payment.assert_awaited_once()
        assert dm.dialog_data["payment_id"] == NEW_ID
        assert dm.dialog_data["payment_url"] == "https://t.me/$invoice"
        dm.switch_to.assert_awaited_with(state=Subscription.CONFIRM)

    async def test_a_pending_payment_is_reused(self):
        # Also when it was already charged: a new payment could then be paid a second time.
        billing = _billing()
        billing.get_transaction.return_value = SimpleNamespace(Status="PENDING")
        dm = _dm(_plan())
        self._cached(dm)

        await _duration_select(dm, billing)

        billing.create_payment.assert_not_awaited()
        assert dm.dialog_data["payment_url"] == OLD["payment_url"]

    async def test_billing_unreachable_keeps_the_cached_payment(self):
        billing = _billing()
        billing.get_transaction.side_effect = RuntimeError("billing unavailable")
        dm = _dm(_plan())
        self._cached(dm)

        await _duration_select(dm, billing)

        billing.create_payment.assert_not_awaited()
        assert dm.dialog_data["payment_url"] == OLD["payment_url"]

    async def test_method_select_replaces_a_cancelled_payment(self):
        billing = _billing()
        billing.get_transaction.return_value = SimpleNamespace(Status="CANCELED")
        dm = _dm(_plan())
        self._cached(dm)
        dm.dialog_data["selected_duration"] = 30

        await _method_select(dm, billing)

        billing.create_payment.assert_awaited_once()
        assert dm.dialog_data["payment_id"] == NEW_ID


class TestOtherChoiceSameDuration:
    """3. The reuse cache was keyed by duration and method only. «Изменить» → Макс → 30 days made a
    payment; back to the subscription screen, «Продлить» kept the plan cache (only a plan pick
    clears it), so Старт → 30 days reused the Макс CHANGE invoice under «Старт, продление»."""

    async def test_renew_after_change_with_the_same_duration_makes_its_own_payment(self):
        billing = _billing()
        billing.get_transaction.return_value = SimpleNamespace(Status="PENDING")
        max_plan = PlanDto(
            id=3, name="💎 Макс", durations=[PlanDurationDto(id=30, days=30, prices=[])]
        )
        dm = _dm(max_plan)
        dm.dialog_data["purchase_type"] = PurchaseType.CHANGE
        await _duration_select(dm, billing)
        assert billing.create_payment.await_count == 1

        # «Назад» to the subscription screen, then «Продлить»: on_subscription_plans saves the
        # current plan and the purchase type, and keeps the rest of the dialog data.
        dm.dialog_data["plandto"] = _plan().model_dump()
        dm.dialog_data["purchase_type"] = PurchaseType.RENEW
        billing.create_payment.return_value = MagicMock(
            ID="22222222-2222-4222-8222-222222222222", URL=None
        )
        await _duration_select(dm, billing)

        assert billing.create_payment.await_count == 2
        last = billing.create_payment.await_args.kwargs
        assert (last["plan_id"], last["purchase_type"]) == (1, "RENEW")
        assert dm.dialog_data["payment_id"] == "22222222-2222-4222-8222-222222222222"
