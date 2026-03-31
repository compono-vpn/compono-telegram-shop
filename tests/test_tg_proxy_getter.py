"""Tests for the TG proxy window getter."""

from __future__ import annotations

import pytest

from src.infrastructure.billing.models import BillingTGProxy

from tests.conftest import (
    make_billing_client,
    make_dialog_manager,
    make_subscription,
    make_user,
    unwrap_inject,
)

from src.bot.routers.menu.getters import tg_proxy_getter as _tg_proxy_getter

tg_proxy_getter = unwrap_inject(_tg_proxy_getter)


async def _call_tg_proxy_getter(user=None, billing=None):
    return await tg_proxy_getter(
        dialog_manager=make_dialog_manager(),
        user=user or make_user(subscription=make_subscription(plan_id=2)),
        billing=billing or make_billing_client(),
    )


class TestTGProxyGetter:
    @pytest.mark.asyncio
    async def test_returns_proxies_for_eligible_user(self):
        proxies = [
            BillingTGProxy(id=1, server="1.2.3.4", port=443, secret="abc", link="tg://proxy?server=1.2.3.4&port=443&secret=abc"),
            BillingTGProxy(id=2, server="5.6.7.8", port=443, secret="def", link="tg://proxy?server=5.6.7.8&port=443&secret=def"),
        ]
        billing = make_billing_client(tg_proxies=proxies)
        user = make_user(subscription=make_subscription(plan_id=2))

        result = await _call_tg_proxy_getter(user=user, billing=billing)

        assert result["has_proxies"] is True
        assert len(result["proxies"]) == 2
        assert result["proxies"][0]["server"] == "1.2.3.4"
        assert result["proxies"][1]["server"] == "5.6.7.8"

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_proxies(self):
        billing = make_billing_client(tg_proxies=[])

        result = await _call_tg_proxy_getter(billing=billing)

        assert result["has_proxies"] is False
        assert result["proxies"] == []

    @pytest.mark.asyncio
    async def test_billing_error_returns_empty_gracefully(self):
        billing = make_billing_client(tg_proxies_error=Exception("Billing API error 404"))

        result = await _call_tg_proxy_getter(billing=billing)

        assert result["has_proxies"] is False
        assert result["proxies"] == []

    @pytest.mark.asyncio
    async def test_no_subscription_returns_empty(self):
        user = make_user(subscription=None)
        billing = make_billing_client()

        result = await _call_tg_proxy_getter(user=user, billing=billing)

        assert result["has_proxies"] is False

    @pytest.mark.asyncio
    async def test_passes_plan_id_to_billing(self):
        billing = make_billing_client(tg_proxies=[])
        user = make_user(subscription=make_subscription(plan_id=3, plan_name="💎 Макс"))

        await _call_tg_proxy_getter(user=user, billing=billing)

        billing.get_tg_proxies.assert_called_once_with(3)
