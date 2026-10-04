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


MT_LINK = "tg://proxy?server=1.2.3.4&port=443&secret=abc"
WEB_LINK = "https://t.me/webproxy?server=tg.cdn.mynetcloud.online&secret=e7ddfe619b1b5e5d53bdb85d5070cc82"

PHONE_HEADER = "📱 <b>Телефон</b>"
DESKTOP_HEADER = "💻 <b>Компьютер</b> (Telegram Desktop 7.1.1 и новее)"
CLOSING = "Нажмите на ссылку, прокси подключится автоматически."
VPN_WARNING = "⚠️ <b>Важно:</b> подключайте прокси с <b>выключенным VPN</b>"


def _mtproto_proxy(id=1, server="1.2.3.4", port=443, link=MT_LINK):
    return BillingTGProxy(id=id, server=server, port=port, secret="abc", link=link, kind="MTPROTO")


def _web_proxy(id=2, server="tg.cdn.mynetcloud.online", link=WEB_LINK):
    return BillingTGProxy(id=id, server=server, port=443, secret="e7dd", link=link, kind="WEB")


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
    async def test_proxy_message_explains_purpose_and_vpn_off(self):
        proxies = [
            BillingTGProxy(id=1, server="1.2.3.4", port=443, secret="abc", link="tg://proxy?server=1.2.3.4&port=443&secret=abc"),
        ]
        billing = make_billing_client(tg_proxies=proxies)
        user = make_user(subscription=make_subscription(plan_id=2))

        result = await _call_tg_proxy_getter(user=user, billing=billing)
        msg = result["proxy_message"]

        assert "без включённого VPN" in msg, "message should explain proxy works without VPN"
        assert "выключенным VPN" in msg, "message should warn to turn VPN off"
        assert "1.2.3.4:443" in msg, "message should contain server:port"
        assert "tg://proxy" in msg, "message should contain clickable tg:// link"

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


class TestTGProxyGetterKinds:
    @pytest.mark.asyncio
    async def test_renders_phone_section_before_desktop_section(self):
        billing = make_billing_client(tg_proxies=[_web_proxy(id=2), _mtproto_proxy(id=1)])

        msg = (await _call_tg_proxy_getter(billing=billing))["proxy_message"]

        assert PHONE_HEADER in msg
        assert DESKTOP_HEADER in msg
        assert msg.index(PHONE_HEADER) < msg.index(DESKTOP_HEADER)

    @pytest.mark.asyncio
    async def test_mtproto_line_lives_in_phone_section_with_server_and_port(self):
        billing = make_billing_client(tg_proxies=[_mtproto_proxy(), _web_proxy()])

        msg = (await _call_tg_proxy_getter(billing=billing))["proxy_message"]

        line = f'▸ <a href="{MT_LINK}">Подключить 1.2.3.4:443</a>'
        assert line in msg
        assert msg.index(PHONE_HEADER) < msg.index(line) < msg.index(DESKTOP_HEADER)

    @pytest.mark.asyncio
    async def test_web_line_lives_in_desktop_section_without_port(self):
        billing = make_billing_client(tg_proxies=[_mtproto_proxy(), _web_proxy()])

        msg = (await _call_tg_proxy_getter(billing=billing))["proxy_message"]

        line = f'▸ <a href="{WEB_LINK}">Подключить tg.cdn.mynetcloud.online</a>'
        assert line in msg
        assert msg.index(DESKTOP_HEADER) < msg.index(line)
        assert "tg.cdn.mynetcloud.online:443" not in msg

    @pytest.mark.asyncio
    async def test_full_message_layout(self):
        billing = make_billing_client(
            tg_proxies=[_mtproto_proxy(id=1), _mtproto_proxy(id=3, server="5.6.7.8", port=8443, link="tg://proxy?server=5.6.7.8&port=8443&secret=abc"), _web_proxy()]
        )

        msg = (await _call_tg_proxy_getter(billing=billing))["proxy_message"]

        assert msg.startswith("<b>📡 Прокси для Telegram</b>\n")
        assert VPN_WARNING in msg
        tail = msg[msg.index(PHONE_HEADER):]
        assert tail == (
            f"{PHONE_HEADER}\n"
            f'▸ <a href="{MT_LINK}">Подключить 1.2.3.4:443</a>\n'
            '▸ <a href="tg://proxy?server=5.6.7.8&port=8443&secret=abc">Подключить 5.6.7.8:8443</a>\n'
            f"\n{DESKTOP_HEADER}\n"
            f'▸ <a href="{WEB_LINK}">Подключить tg.cdn.mynetcloud.online</a>\n'
            f"\n{CLOSING}"
        )

    @pytest.mark.asyncio
    async def test_omits_desktop_section_when_no_web_proxies(self):
        billing = make_billing_client(tg_proxies=[_mtproto_proxy()])

        msg = (await _call_tg_proxy_getter(billing=billing))["proxy_message"]

        assert PHONE_HEADER in msg
        assert "Компьютер" not in msg
        assert "Telegram Desktop" not in msg

    @pytest.mark.asyncio
    async def test_omits_phone_section_when_no_mtproto_proxies(self):
        billing = make_billing_client(tg_proxies=[_web_proxy()])

        msg = (await _call_tg_proxy_getter(billing=billing))["proxy_message"]

        assert DESKTOP_HEADER in msg
        assert "Телефон" not in msg
        assert "tg://proxy" not in msg

    @pytest.mark.asyncio
    async def test_keeps_intro_warning_and_closing_line(self):
        billing = make_billing_client(tg_proxies=[_mtproto_proxy(), _web_proxy()])

        msg = (await _call_tg_proxy_getter(billing=billing))["proxy_message"]

        assert "без включённого VPN" in msg
        assert VPN_WARNING in msg
        assert msg.endswith(CLOSING)

    @pytest.mark.asyncio
    async def test_proxy_without_kind_is_treated_as_phone_proxy(self):
        legacy = BillingTGProxy.model_validate(
            {"id": 1, "server": "1.2.3.4", "port": 443, "secret": "abc", "link": MT_LINK}
        )
        billing = make_billing_client(tg_proxies=[legacy])

        msg = (await _call_tg_proxy_getter(billing=billing))["proxy_message"]

        assert PHONE_HEADER in msg
        assert "Компьютер" not in msg
        assert f'▸ <a href="{MT_LINK}">Подключить 1.2.3.4:443</a>' in msg

    @pytest.mark.asyncio
    async def test_proxies_list_includes_both_kinds_with_kind_field(self):
        billing = make_billing_client(tg_proxies=[_mtproto_proxy(), _web_proxy()])

        result = await _call_tg_proxy_getter(billing=billing)

        assert result["has_proxies"] is True
        assert [(p["server"], p["kind"]) for p in result["proxies"]] == [
            ("1.2.3.4", "MTPROTO"),
            ("tg.cdn.mynetcloud.online", "WEB"),
        ]

    @pytest.mark.asyncio
    async def test_empty_state_has_no_sections(self):
        msg = (await _call_tg_proxy_getter(billing=make_billing_client(tg_proxies=[])))["proxy_message"]

        assert "Нет доступных прокси." in msg
        assert PHONE_HEADER not in msg
        assert DESKTOP_HEADER not in msg
