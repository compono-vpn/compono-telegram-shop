import pytest

from src.bot.routers.menu.getters import tg_proxy_getter
from src.bot.routers.menu.handlers import on_start_command
from src.bot.states import MainMenu
from src.core.enums import SubscriptionStatus
from src.infrastructure.billing.models import BillingTGProxy
from tests.conftest import (
    make_billing_client,
    make_dialog_manager,
    make_subscription,
    make_user,
    unwrap_inject,
)
from tests.test_menu_getter import _call_menu_getter
from tests.test_on_start_command import _setup


@pytest.mark.parametrize(
    "subscription", [None, make_subscription(active=False), make_subscription(is_trial=True)]
)
async def test_public_proxies_visible_without_paid_access(subscription):
    user = make_user(subscription=subscription)
    proxy = BillingTGProxy(
        id=7,
        server="public.example.com",
        port=443,
        secret="test",
        kind="WEB",
        link="https://example.invalid",
    )
    billing = make_billing_client(tg_proxies=[proxy])
    result = await _call_menu_getter(user=user, billing=billing)
    assert result["tg_proxy_available"]
    billing.get_tg_proxies.assert_awaited_once_with(0)


@pytest.mark.parametrize(
    "subscription", [None, make_subscription(active=False), make_subscription(is_trial=True)]
)
async def test_proxy_window_never_uses_expired_or_trial_plan_for_paid_links(subscription):
    billing = make_billing_client()
    await unwrap_inject(tg_proxy_getter)(
        dialog_manager=make_dialog_manager(),
        user=make_user(subscription=subscription),
        billing=billing,
    )
    billing.get_tg_proxies.assert_awaited_once_with(0)


@pytest.mark.parametrize("payload", ["proxy", "source-channel_proxy"])
async def test_proxy_deep_link_opens_proxies_without_trial_or_extra_prompt(payload):
    message, user, dm, i18n, channel, notification = _setup("/start " + payload)
    await unwrap_inject(on_start_command)(message, user, dm, i18n, channel, notification)
    assert dm.start.await_args.args[0] == MainMenu.TG_PROXY
    channel.should_prompt.assert_not_awaited()
    notification.notify_user.assert_not_awaited()


async def test_active_paid_plan_is_preserved_in_both_proxy_entry_points():
    user = make_user(subscription=make_subscription(plan_id=3))
    billing = make_billing_client()
    await _call_menu_getter(user=user, billing=billing)
    billing.get_tg_proxies.assert_awaited_once_with(3)
    billing.get_tg_proxies.reset_mock()
    result = await unwrap_inject(tg_proxy_getter)(
        dialog_manager=make_dialog_manager(), user=user, billing=billing
    )
    billing.get_tg_proxies.assert_awaited_once_with(3)
    assert not result["show_vpn_offer"]


async def test_expired_timestamp_overrides_stale_active_status():
    subscription = make_subscription(active=False)
    subscription.status = SubscriptionStatus.ACTIVE
    user = make_user(subscription=subscription)
    billing = make_billing_client()
    result = await unwrap_inject(tg_proxy_getter)(
        dialog_manager=make_dialog_manager(), user=user, billing=billing
    )
    billing.get_tg_proxies.assert_awaited_once_with(0)
    assert result["show_vpn_offer"]
