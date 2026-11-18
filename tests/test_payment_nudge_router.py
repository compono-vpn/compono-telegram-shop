"""The nudge's «Другой способ» button reopens the method list for the same plan and period."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from aiogram_dialog import ShowMode, StartMode

from src.bot.routers.extra.payment_nudge import on_payment_nudge_other
from src.bot.states import Subscription
from src.core.constants import PAYMENT_NUDGE_PREFIX
from src.core.enums import PurchaseType
from src.infrastructure.billing.models import BillingPlan, BillingPlanDuration
from tests.conftest import make_dialog_manager, make_user, unwrap_inject

TG = 777


def _transaction(user_id=TG, status="PENDING", plan_id=1, days=30, purchase_type="NEW"):
    return MagicMock(
        UserTelegramID=user_id,
        Status=status,
        PurchaseType=purchase_type,
        Plan=MagicMock(id=plan_id, duration=days),
    )


def _callback(payment_id: str) -> MagicMock:
    callback = MagicMock()
    callback.data = f"{PAYMENT_NUDGE_PREFIX}{payment_id}"
    callback.answer = AsyncMock()
    return callback


def _dialog_manager() -> MagicMock:
    dm = make_dialog_manager()
    dm.start = AsyncMock()
    dm.update = AsyncMock()
    return dm


def _billing(transaction):
    billing = AsyncMock()
    billing.get_transaction.return_value = transaction
    plan = BillingPlan(
        ID=1,
        Name="⚡️ Старт",
        Type="BOTH",
        Durations=[BillingPlanDuration(ID=1, Days=30, Prices=[])],
    )
    billing.get_plan.return_value = plan
    billing.get_available_plans.return_value = [plan]
    return billing


async def _call(callback, dm, billing, user=None):
    raw = unwrap_inject(on_payment_nudge_other)
    await raw(callback, user or make_user(telegram_id=TG), dm, billing)


async def test_opens_the_method_list_for_the_same_plan_and_period():
    payment_id = str(uuid4())
    dm = _dialog_manager()
    billing = _billing(_transaction())

    await _call(_callback(payment_id), dm, billing)

    dm.start.assert_awaited_once()
    args, kwargs = dm.start.await_args
    assert args[0] == Subscription.PAYMENT_METHOD
    assert kwargs["mode"] == StartMode.RESET_STACK
    assert kwargs["show_mode"] == ShowMode.NO_UPDATE
    assert dm.show_mode == ShowMode.DELETE_AND_SEND
    dm.update.assert_awaited_once()
    seeded = dm.update.await_args.args[0]
    assert seeded["selected_duration"] == 30
    assert seeded["purchase_type"] == PurchaseType.NEW
    assert seeded["plandto"]["id"] == 1
    assert seeded["only_single_plan"] is False


async def test_renewal_keeps_its_purchase_type():
    dm = _dialog_manager()
    billing = _billing(_transaction(purchase_type="RENEW"))

    await _call(_callback(str(uuid4())), dm, billing)

    assert dm.update.await_args.args[0]["purchase_type"] == PurchaseType.RENEW


async def test_someone_elses_payment_is_ignored():
    dm = _dialog_manager()
    billing = _billing(_transaction(user_id=999))
    callback = _callback(str(uuid4()))

    await _call(callback, dm, billing)

    dm.start.assert_not_awaited()
    callback.answer.assert_awaited_once_with()


async def test_paid_payment_does_not_reopen_checkout():
    dm = _dialog_manager()
    billing = _billing(_transaction(status="COMPLETED"))
    callback = _callback(str(uuid4()))

    await _call(callback, dm, billing)

    dm.start.assert_not_awaited()
    callback.answer.assert_awaited_once()


async def test_unknown_or_malformed_payment_is_ignored():
    dm = _dialog_manager()
    billing = _billing(None)
    for data in (str(uuid4()), "not-a-uuid"):
        callback = _callback(data)
        await _call(callback, dm, billing)
        callback.answer.assert_awaited_once_with()

    dm.start.assert_not_awaited()


async def test_plan_that_no_longer_exists_is_ignored():
    dm = _dialog_manager()
    billing = _billing(_transaction())
    billing.get_available_plans.return_value = []
    callback = _callback(str(uuid4()))

    await _call(callback, dm, billing)

    dm.start.assert_not_awaited()
    callback.answer.assert_awaited_once_with()


async def test_a_plan_no_longer_offered_is_not_sold():
    # The payment's plan can be the proxy plan (priced without the user's discount by billing,
    # with it by the invoice), an archived plan, or the trial: sell only what the plan list offers.
    dm = _dialog_manager()
    billing = _billing(_transaction(plan_id=5))
    callback = _callback(str(uuid4()))

    await _call(callback, dm, billing)

    dm.start.assert_not_awaited()
    callback.answer.assert_awaited_once()
