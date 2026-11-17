"""The plan list sells only the plans billing offers this user (/plans/available).

aiogram-dialog's Select passes whatever item id the callback carries to on_plan_select; it never
checks it against the rendered list. The handler then read any plan by id, so a press from an older
message, or a modified client, could start a checkout for a plan not offered: the trial plan
(0 stars, billing completes a 0-price payment by itself, so a free trial again and again), the proxy
plan (billing records it undiscounted while the invoice used the user's discount), or an inactive
or user-restricted plan (billing's CreatePayment checks neither).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.routers.subscription.handlers import on_plan_select
from tests.conftest import make_user, unwrap_inject

pytestmark = pytest.mark.asyncio

UID = 4242


def _plan(plan_id: int) -> MagicMock:
    plan = MagicMock()
    plan.ID = plan_id
    return plan


async def _select(plan_id: int, offered: list[int]) -> tuple[AsyncMock, MagicMock]:
    billing = AsyncMock()
    billing.get_available_plans.return_value = [_plan(i) for i in offered]
    billing.get_plan.side_effect = AssertionError("a plan not offered was read by id")
    dm = MagicMock()
    dm.middleware_data = {"user": make_user(telegram_id=UID)}
    dm.dialog_data = {}
    dm.switch_to = AsyncMock()
    await unwrap_inject(on_plan_select)(
        AsyncMock(),
        MagicMock(),
        dm,
        plan_id,
        billing,
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
    )
    return billing, dm


@pytest.mark.parametrize("plan_id", [4, 5, 99])  # trial, proxy, hidden or unknown
async def test_plan_not_offered_to_the_user_starts_no_checkout(plan_id):
    billing, dm = await _select(plan_id, offered=[1, 2, 3])
    billing.get_plan.assert_not_awaited()
    billing.create_payment.assert_not_awaited()
    dm.switch_to.assert_not_awaited()
