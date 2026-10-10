from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.services.trial_activation import has_verified_traffic, get_monthly_trial_plan
from tests.conftest import make_subscription, make_user


def test_import_or_first_connection_flag_without_bytes_is_not_activation():
    assert not has_verified_traffic(SimpleNamespace(first_connected=True, user_traffic=None))
    assert not has_verified_traffic(SimpleNamespace(user_traffic=SimpleNamespace(
        used_traffic_bytes=0, lifetime_used_traffic_bytes=0)))


def test_usage_survives_counter_reset():
    assert has_verified_traffic(SimpleNamespace(user_traffic=SimpleNamespace(
        used_traffic_bytes=0, lifetime_used_traffic_bytes=4096)))


@pytest.mark.asyncio
async def test_offer_requires_active_trial_and_real_traffic():
    user = make_user(subscription=make_subscription(is_trial=True))
    remna = AsyncMock()
    remna.get_user.return_value = SimpleNamespace(user_traffic=None)
    billing = AsyncMock()
    assert await get_monthly_trial_plan(user, remna, billing) is None
    billing.get_available_plans.assert_not_called()


@pytest.mark.asyncio
async def test_paid_users_never_get_trial_upgrade():
    user = make_user(subscription=make_subscription(is_trial=False))
    remna, billing = AsyncMock(), AsyncMock()
    assert await get_monthly_trial_plan(user, remna, billing) is None
    remna.get_user.assert_not_called()


def monthly_plan(plan_id=1, order=0, active=True, days=30):
    from src.infrastructure.billing.models import BillingPlan, BillingPlanDuration
    return BillingPlan(ID=plan_id, OrderIndex=order, IsActive=active, Type="BOTH",
                       Availability="ALL", Name="Start", TrafficLimitStrategy="MONTH",
                       Durations=[BillingPlanDuration(Days=days)])


@pytest.mark.asyncio
async def test_offer_selects_available_active_monthly_plan_in_catalog_order():
    user = make_user(subscription=make_subscription(is_trial=True))
    remna, billing = AsyncMock(), AsyncMock()
    remna.get_user.return_value = SimpleNamespace(user_traffic=SimpleNamespace(
        used_traffic_bytes=1024, lifetime_used_traffic_bytes=1024))
    billing.get_available_plans.return_value = [monthly_plan(9, 0, False),
        monthly_plan(8, 0, days=365), monthly_plan(2, 2), monthly_plan(1, 1)]
    assert (await get_monthly_trial_plan(user, remna, billing)).id == 1


@pytest.mark.asyncio
async def test_unavailable_telemetry_hides_offer_without_breaking_menu():
    user = make_user(subscription=make_subscription(is_trial=True))
    remna, billing = AsyncMock(), AsyncMock()
    remna.get_user.side_effect = TimeoutError()
    assert await get_monthly_trial_plan(user, remna, billing) is None


@pytest.mark.asyncio
async def test_monthly_shortcut_resets_stale_checkout_and_keeps_payment_explicit():
    from src.bot.routers.subscription.handlers import on_trial_monthly_upgrade
    from src.bot.states import Subscription
    from src.core.constants import USER_KEY
    from src.core.enums import PurchaseType
    from src.infrastructure.billing.models import BillingPaymentGateway
    from tests.conftest import make_dialog_manager, unwrap_inject
    user = make_user(subscription=make_subscription(is_trial=True))
    dm = make_dialog_manager()
    dm.switch_to = AsyncMock()
    dm.middleware_data[USER_KEY] = user
    dm.dialog_data.update(payment_id="old", payment_cache={"old": "stale"})
    remna, billing = AsyncMock(), AsyncMock()
    remna.get_user.return_value = SimpleNamespace(user_traffic=SimpleNamespace(
        used_traffic_bytes=1024, lifetime_used_traffic_bytes=1024))
    billing.get_available_plans.return_value = [monthly_plan()]
    billing.list_active_gateways.return_value = [BillingPaymentGateway(IsActive=True, Channel="BOT")]
    await unwrap_inject(on_trial_monthly_upgrade)(AsyncMock(), None, dm, billing, remna)
    assert dm.dialog_data["selected_duration"] == 30
    assert dm.dialog_data["purchase_type"] == PurchaseType.NEW
    assert "payment_id" not in dm.dialog_data and "payment_cache" not in dm.dialog_data
    dm.switch_to.assert_awaited_once_with(state=Subscription.PAYMENT_METHOD)
    billing.create_payment.assert_not_called()


def test_shortcut_preserves_free_checkout_for_fully_discounted_price():
    from src.bot.routers.subscription.handlers import _save_payment_data
    from src.models.dto import PriceDetailsDto
    from tests.conftest import make_dialog_manager
    dm = make_dialog_manager()
    _save_payment_data(dm, {"payment_id": "test", "payment_url": None,
                           "final_pricing": PriceDetailsDto(final_amount=0).model_dump_json()})
    assert dm.dialog_data["is_free"] is True
