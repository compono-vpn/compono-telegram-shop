"""Tests for the main menu getter.

Covers TG proxy visibility, subscription states, and error handling.
"""

from __future__ import annotations

import pytest

from src.infrastructure.billing.models import BillingTGProxy

from tests.conftest import (
    make_billing_client,
    make_config,
    make_dialog_manager,
    make_i18n,
    make_referral_service,
    make_subscription,
    make_user,
    unwrap_inject,
)

from src.bot.routers.menu.getters import menu_getter as _menu_getter

menu_getter = unwrap_inject(_menu_getter)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _call_menu_getter(
    user=None,
    billing=None,
    config=None,
    i18n=None,
    referral_service=None,
):
    return await menu_getter(
        dialog_manager=make_dialog_manager(),
        config=config or make_config(),
        user=user or make_user(),
        i18n=i18n or make_i18n(),
        billing=billing or make_billing_client(),
        referral_service=referral_service or make_referral_service(),
    )


# ---------------------------------------------------------------------------
# TG proxy visibility
# ---------------------------------------------------------------------------

class TestTGProxyVisibility:
    """TG proxy button should only appear for eligible, active subscribers."""

    @pytest.mark.asyncio
    async def test_pro_plan_with_proxies_shows_button(self):
        proxies = [BillingTGProxy(ID=1, Server="1.2.3.4", Port=443, Secret="abc", Link="tg://proxy?server=1.2.3.4&port=443&secret=abc")]
        user = make_user(subscription=make_subscription(plan_id=2))
        billing = make_billing_client(tg_proxies=proxies)

        result = await _call_menu_getter(user=user, billing=billing)

        assert result["tg_proxy_available"] is True

    @pytest.mark.asyncio
    async def test_max_plan_with_proxies_shows_button(self):
        proxies = [BillingTGProxy(ID=1, Server="1.2.3.4", Port=443, Secret="abc", Link="tg://proxy?server=1.2.3.4&port=443&secret=abc")]
        user = make_user(subscription=make_subscription(plan_id=3, plan_name="💎 Макс"))
        billing = make_billing_client(tg_proxies=proxies)

        result = await _call_menu_getter(user=user, billing=billing)

        assert result["tg_proxy_available"] is True

    @pytest.mark.asyncio
    async def test_start_plan_no_proxies_hides_button(self):
        user = make_user(subscription=make_subscription(plan_id=1, plan_name="⚡️ Старт", traffic_limit=100, device_limit=2))
        billing = make_billing_client(tg_proxies=[])

        result = await _call_menu_getter(user=user, billing=billing)

        assert result["tg_proxy_available"] is False

    @pytest.mark.asyncio
    async def test_no_subscription_hides_button(self):
        user = make_user(subscription=None)
        billing = make_billing_client()

        result = await _call_menu_getter(user=user, billing=billing)

        assert result["tg_proxy_available"] is False

    @pytest.mark.asyncio
    async def test_expired_subscription_hides_button(self):
        user = make_user(subscription=make_subscription(plan_id=2, active=False))
        billing = make_billing_client()

        result = await _call_menu_getter(user=user, billing=billing)

        # Expired sub: is_active is False, so get_tg_proxies is not called
        assert result["tg_proxy_available"] is False

    @pytest.mark.asyncio
    async def test_billing_api_error_hides_button_gracefully(self):
        """The bug that crashed the menu — billing returns 404, menu must still render."""
        user = make_user(subscription=make_subscription(plan_id=2))
        billing = make_billing_client(tg_proxies_error=Exception("Billing API error 404: 404 page not found"))

        result = await _call_menu_getter(user=user, billing=billing)

        assert result["tg_proxy_available"] is False
        assert result["connectable"] is True  # rest of menu still works

    @pytest.mark.asyncio
    async def test_billing_timeout_hides_button_gracefully(self):
        user = make_user(subscription=make_subscription(plan_id=3, plan_name="💎 Макс"))
        billing = make_billing_client(tg_proxies_error=TimeoutError("billing timeout"))

        result = await _call_menu_getter(user=user, billing=billing)

        assert result["tg_proxy_available"] is False
        assert result["has_subscription"] is True


# ---------------------------------------------------------------------------
# Menu state basics
# ---------------------------------------------------------------------------

class TestMenuState:
    """Basic menu getter state for different subscription scenarios."""

    @pytest.mark.asyncio
    async def test_active_subscription_shows_connectable(self):
        user = make_user(subscription=make_subscription(plan_id=1, plan_name="⚡️ Старт"))

        result = await _call_menu_getter(user=user)

        assert result["connectable"] is True
        assert result["has_subscription"] is True

    @pytest.mark.asyncio
    async def test_no_subscription_not_connectable(self):
        user = make_user(subscription=None)

        result = await _call_menu_getter(user=user)

        assert result["connectable"] is False
        assert result["has_subscription"] is False

    @pytest.mark.asyncio
    async def test_expired_subscription_not_connectable(self):
        user = make_user(subscription=make_subscription(active=False))

        result = await _call_menu_getter(user=user)

        assert result["connectable"] is False
