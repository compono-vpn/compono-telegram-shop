from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from aiogram.types import InlineKeyboardMarkup

from src.bot import proxy_view
from src.bot.proxy_view import to_https_link
from src.bot.routers.menu.dialog import tg_proxy
from src.bot.routers.menu.getters import tg_proxy_getter
from src.bot.routers.subscription.dialog import proxy_confirm, proxy_success
from src.bot.routers.subscription.getters import proxy_confirm_getter, proxy_success_getter
from src.core.constants import CONTAINER_KEY
from tests.conftest import (
    make_billing_client,
    make_dialog_manager,
    make_i18n,
    make_subscription,
    make_user,
    unwrap_inject,
)
from tests.test_personal_proxy_plan import (
    EXPIRES,
    PERSONAL_PHONE,
    PERSONAL_WEB,
    PUBLIC_WEB,
    _buy,
    _buy_args,
    _entitled,
    _not_entitled,
    _public_rows,
    _row,
    _shared_rows,
)

PHONE_HTTPS = "https://t.me/proxy?server=me.compono.online&port=443&secret=cc"
SHARED_PHONE_HTTPS = PHONE_HTTPS
HOSTS = ("compono.online", "me.compono", "stable.", "pub.")
VPN_OFF = "⚠️ Перед подключением выключите VPN."
UPDATE_HINT = "📲 Не подключается? Обновите Telegram до последней версии."


async def _render(personal=None, personal_error=None, user=None, **kwargs):
    billing = make_billing_client(personal=personal, personal_error=personal_error, **kwargs)
    result = await unwrap_inject(tg_proxy_getter)(
        dialog_manager=make_dialog_manager(), user=user or make_user(), billing=billing
    )
    return result, billing


async def _keyboard(window, data):
    manager = make_dialog_manager()
    container = AsyncMock()
    container.get.return_value = make_i18n()
    manager.middleware_data[CONTAINER_KEY] = container
    manager.current_context.return_value.state = window.get_state()
    rows = await window.keyboard.render_keyboard(data, manager)
    return rows


def _flat(rows):
    return [b for row in rows for b in row]


class TestLinkConversion:
    def test_mtproto_deep_link_becomes_https(self):
        assert to_https_link("tg://proxy?server=a&port=443&secret=x") == (
            "https://t.me/proxy?server=a&port=443&secret=x"
        )

    def test_web_link_is_untouched(self):
        assert to_https_link(PUBLIC_WEB) == PUBLIC_WEB


class TestProDefaultVpn:
    async def test_text(self):
        result, _ = await _render(personal=_entitled("vpn_plan"))

        assert result["proxy_message"] == (
            "⭐ <b>Ваш Pro-прокси</b>\n"
            "Личный и быстрый, до 3 устройств. Входит в подписку Compono VPN.\n\n"
            f"{VPN_OFF}"
            f"\n{UPDATE_HINT}"
        )

    async def test_urls_flags_and_clean_text(self):
        result, _ = await _render(personal=_entitled("vpn_plan"))

        assert result["desktop_url"] == PERSONAL_WEB
        assert result["phone_url"] == ""
        assert result["free_url"] == PUBLIC_WEB
        assert result["has_personal"] is True
        assert result["has_desktop"] and not result["has_phone"] and result["has_free"]
        assert result["show_plans_offer"] is False
        assert result["can_buy_proxy"] is False and result["can_renew_proxy"] is False
        message = result["proxy_message"]
        assert "http" not in message and "tg://" not in message
        assert not any(h in message for h in HOSTS)


class TestProViaProxyPlan:
    async def test_text_and_renew(self):
        result, _ = await _render(personal=_entitled("proxy_plan", EXPIRES))

        assert result["proxy_message"] == (
            "⭐ <b>Ваш Pro-прокси</b>\n"
            "Личный и быстрый, до 3 устройств. Действует до 12.11.2026.\n\n"
            f"{VPN_OFF}"
            f"\n{UPDATE_HINT}"
        )
        assert result["can_renew_proxy"] is True
        assert result["can_buy_proxy"] is False
        assert result["proxy_price"] == "25"

    async def test_no_renew_without_price(self):
        personal = _entitled("proxy_plan", EXPIRES)
        personal.price_rub = None
        result, _ = await _render(personal=personal)
        assert result["can_renew_proxy"] is False
        assert result["desktop_url"] == PERSONAL_WEB

    async def test_no_renew_without_plan(self):
        personal = _entitled("proxy_plan", EXPIRES)
        personal.proxy_plan_id = None
        result, _ = await _render(personal=personal)
        assert result["can_renew_proxy"] is False


class TestNotEntitled:
    async def test_offer_text(self):
        result, _ = await _render(personal=_not_entitled())

        assert result["proxy_message"] == (
            "📡 <b>Прокси для Telegram</b>\n"
            "Telegram работает без VPN.\n\n"
            "🆓 <b>Бесплатный</b> — общий, при нагрузке скорость снижается.\n"
            "⭐ <b>Pro</b> — личный и быстрый, до 3 устройств."
            " <s>49 ₽</s> <b>25 ₽/мес</b> до 31 октября.\n"
            "🎁 С подпиской Compono VPN — Pro бесплатно.\n\n"
            f"{VPN_OFF}"
        )

    async def test_flags(self):
        result, _ = await _render(personal=_not_entitled())

        assert result["can_buy_proxy"] is True
        assert result["free_url"] == PUBLIC_WEB
        assert result["has_free"] is True
        assert result["is_entitled"] is False
        assert result["show_plans_offer"] is True
        assert result["has_phone"] is False and result["has_desktop"] is False
        assert "http" not in result["proxy_message"]

    @pytest.mark.parametrize("plan_id,price", [(None, 25), (9, None), (None, None), (0, 25)])
    async def test_no_pro_offer_when_plan_or_price_missing(self, plan_id, price):
        personal = _not_entitled()
        personal.proxy_plan_id = plan_id
        personal.price_rub = price
        result, _ = await _render(personal=personal)

        assert result["can_buy_proxy"] is False
        assert result["proxy_message"] == (
            "📡 <b>Прокси для Telegram</b>\n"
            "Telegram работает без VPN.\n\n"
            "🆓 <b>Бесплатный</b> — общий, при нагрузке скорость снижается.\n\n"
            f"{VPN_OFF}"
        )
        assert result["has_free"] is True

    async def test_no_offer_for_active_vpn_subscriber(self):
        user = make_user(subscription=make_subscription(plan_id=2))
        result, _ = await _render(personal=_not_entitled(), user=user)
        assert result["can_buy_proxy"] is False
        assert "<s>" not in result["proxy_message"]
        assert "Pro" not in result["proxy_message"]

    async def test_trial_user_can_buy(self):
        user = make_user(subscription=make_subscription(is_trial=True))
        result, _ = await _render(personal=_not_entitled(), user=user)
        assert result["can_buy_proxy"] is True

    async def test_nothing_available_says_so(self):
        personal = _not_entitled(proxies=[])
        personal.proxy_plan_id = None
        result, _ = await _render(personal=personal)
        assert "Сейчас прокси недоступны. Попробуйте позже." in result["proxy_message"]
        assert result["has_free"] is False

    @pytest.mark.parametrize(
        "price,text", [(25, "25"), (25.0, "25"), (24.9, "24.9"), (30.25, "30.25")]
    )
    async def test_price_has_no_trailing_zero(self, price, text):
        personal = _not_entitled()
        personal.price_rub = price
        result, _ = await _render(personal=personal)
        assert f"<b>{text} ₽/мес</b>" in result["proxy_message"]
        assert result["proxy_price"] == text


class TestSharedRows:
    async def test_vpn_plan_text_has_no_device_claim(self):
        result, _ = await _render(personal=_entitled("vpn_plan", proxies=_shared_rows()))

        assert result["proxy_message"] == (
            "⭐ <b>Стабильный прокси</b>\n"
            "Стабильное подключение. Входит в подписку Compono VPN.\n\n"
            f"{VPN_OFF}"
            f"\n{UPDATE_HINT}"
        )
        assert result["phone_url"] == ""
        assert result["desktop_url"] == PERSONAL_WEB
        assert result["has_personal"] is False

    async def test_proxy_plan_text_has_no_device_claim(self):
        result, _ = await _render(personal=_entitled("proxy_plan", EXPIRES, _shared_rows()))
        assert "Действует до 12.11.2026." in result["proxy_message"]
        assert "3 устройств" not in result["proxy_message"]


class TestFallback:
    async def test_text_and_buttons_from_legacy_list(self):
        rows = [
            _row(1, "MTPROTO", "p.example", PERSONAL_PHONE, False),
            _row(2, "WEB", "w.example", PERSONAL_WEB, False),
            _row(3, "WEB", "x.example", PUBLIC_WEB, True),
            _row(4, "WEB", "y.example", PUBLIC_WEB + "2", True),
        ]
        result, billing = await _render(tg_proxies=rows)

        assert result["proxy_message"] == (
            f"📡 <b>Прокси для Telegram</b>\nTelegram работает без VPN.\n\n{VPN_OFF}"
        )
        billing.get_tg_proxies.assert_awaited_once_with(0)
        assert result["is_fallback"] is True
        assert result["show_plans_offer"] is False
        assert result["can_buy_proxy"] is False
        assert [(b["label"], b["url"]) for b in result["fallback_buttons"]] == [
            ("📱 Подключить на телефоне", PHONE_HTTPS),
            ("💻 Подключить на компьютере", PERSONAL_WEB),
            ("💻 Запасной 1", PUBLIC_WEB),
            ("💻 Запасной 2", PUBLIC_WEB + "2"),
        ]

    async def test_public_only_first_web_is_primary(self):
        result, _ = await _render(tg_proxies=_public_rows())
        assert result["fallback_buttons"][0]["label"] == "💻 Подключить на компьютере"

    async def test_keeps_plan_id_for_paid_subscriber(self):
        user = make_user(subscription=make_subscription(plan_id=3))
        _, billing = await _render(tg_proxies=[], user=user)
        billing.get_tg_proxies.assert_awaited_once_with(3)

    async def test_both_calls_failing_never_raises(self):
        result, _ = await _render(tg_proxies_error=Exception("down"))
        assert result["has_proxies"] is False
        assert "Сейчас прокси недоступны" in result["proxy_message"]
        assert result["fallback_buttons"] == []


class TestSuccessScreen:
    async def _success(self, personal):
        billing = make_billing_client(personal=personal)
        return await unwrap_inject(proxy_success_getter)(
            dialog_manager=make_dialog_manager(), user=make_user(), billing=billing
        )

    async def test_text_and_urls(self):
        result = await self._success(_entitled("proxy_plan", EXPIRES))

        assert result["proxy_message"] == (
            "✅ <b>Pro подключён</b>\n"
            "Действует до 12.11.2026. До 3 устройств одновременно.\n\n"
            f"{VPN_OFF}"
            f"\n{UPDATE_HINT}"
        )
        assert result["desktop_url"] == PERSONAL_WEB
        assert result["phone_url"] == ""
        assert "http" not in result["proxy_message"]

    async def test_shared_rows_have_no_device_claim(self):
        result = await self._success(_entitled("proxy_plan", EXPIRES, _shared_rows()))
        assert "3 устройств" not in result["proxy_message"]
        assert "Pro" not in result["proxy_message"]

    async def test_not_visible_yet(self):
        billing = make_billing_client(personal=_not_entitled())
        with patch.object(proxy_view.asyncio, "sleep", new=AsyncMock()):
            result = await unwrap_inject(proxy_success_getter)(
                dialog_manager=make_dialog_manager(), user=make_user(), billing=billing
            )
        assert result["proxy_message"] == (
            "✅ <b>Оплата прошла</b>\nPro скоро появится — откройте «Прокси» в меню через минуту."
        )
        assert result["has_desktop"] is False

    async def test_waits_until_entitlement_is_visible(self):
        billing = make_billing_client(personal=_not_entitled())
        billing.get_personal_tg_proxies.side_effect = [
            _not_entitled(),
            _entitled("proxy_plan", EXPIRES),
        ]
        with patch.object(proxy_view.asyncio, "sleep", new=AsyncMock()):
            result = await unwrap_inject(proxy_success_getter)(
                dialog_manager=make_dialog_manager(), user=make_user(), billing=billing
            )
        assert result["desktop_url"] == PERSONAL_WEB


class TestConfirmScreen:
    async def test_getter(self):
        dm = make_dialog_manager()
        dm.start_data = {
            "payment_url": "https://pay.example.invalid/x",
            "price": "25",
            "original_price": 49,
        }
        assert await proxy_confirm_getter(dm) == {
            "url": "https://pay.example.invalid/x",
            "price": "25",
            "original_price": 49,
        }

    async def test_buy_passes_formatted_price(self):
        _, dm, billing, notification = _buy_args(_not_entitled())
        await _buy(dm, billing, notification)
        assert dm.start.await_args.kwargs["data"]["price"] == "25"


class TestButtonColors:
    async def test_pro_keyboard(self):
        result, _ = await _render(personal=_entitled("proxy_plan", EXPIRES))
        buttons = _flat(await _keyboard(tg_proxy, result))

        assert [b.text for b in buttons] == [
            "[btn-proxy-pro]",
            "[btn-proxy-free-backup]",
            "[btn-menu-proxy-renew]",
            "[btn-back]",
        ]
        assert [b.style for b in buttons] == ["success", None, "primary", None]
        assert buttons[0].url == PERSONAL_WEB
        assert buttons[1].url == PUBLIC_WEB

    async def test_vpn_pro_keyboard_has_no_renew(self):
        result, _ = await _render(personal=_entitled("vpn_plan"))
        buttons = _flat(await _keyboard(tg_proxy, result))
        assert "[btn-menu-proxy-renew]" not in [b.text for b in buttons]
        assert "[btn-menu-proxy-plans]" not in [b.text for b in buttons]

    async def test_shared_keyboard_uses_stable_label(self):
        result, _ = await _render(personal=_entitled("vpn_plan", proxies=_shared_rows()))
        buttons = _flat(await _keyboard(tg_proxy, result))
        assert buttons[0].text == "[btn-proxy-stable]"
        assert buttons[0].style == "success"

    async def test_free_keyboard(self):
        result, _ = await _render(personal=_not_entitled())
        buttons = _flat(await _keyboard(tg_proxy, result))

        assert [b.text for b in buttons] == [
            "[btn-proxy-free-connect]",
            "[btn-menu-proxy-buy]",
            "[btn-menu-proxy-plans]",
            "[btn-back]",
        ]
        assert [b.style for b in buttons] == [None, "primary", None, None]
        assert buttons[0].url == PUBLIC_WEB

    async def test_free_keyboard_without_offer_drops_buy(self):
        user = make_user(subscription=make_subscription(plan_id=2))
        result, _ = await _render(personal=_not_entitled(), user=user)
        buttons = _flat(await _keyboard(tg_proxy, result))
        assert "[btn-menu-proxy-buy]" not in [b.text for b in buttons]

    async def test_fallback_keyboard_has_green_url_buttons(self):
        result, _ = await _render(tg_proxies=_public_rows())
        buttons = _flat(await _keyboard(tg_proxy, result))

        assert buttons[0].url == PUBLIC_WEB
        assert buttons[0].style == "success"
        assert buttons[-1].text == "[btn-back]"

    async def test_success_window_keyboard(self):
        billing = make_billing_client(personal=_entitled("proxy_plan", EXPIRES))
        data = await unwrap_inject(proxy_success_getter)(
            dialog_manager=make_dialog_manager(), user=make_user(), billing=billing
        )
        buttons = _flat(await _keyboard(proxy_success, data))

        assert [b.text for b in buttons] == [
            "[btn-proxy-pro]",
            "[btn-proxy-to-menu]",
        ]
        assert [b.style for b in buttons] == ["success", None]

    async def test_confirm_window_keyboard(self):
        data = {"url": "https://pay.example.invalid/x", "price": "25", "original_price": 49}
        buttons = _flat(await _keyboard(proxy_confirm, data))

        assert buttons[0].text == "[btn-proxy-pay]"
        assert buttons[0].url == "https://pay.example.invalid/x"
        assert buttons[0].style == "primary"
        assert buttons[1].style is None

    async def test_style_is_serialized_into_reply_markup(self):
        result, _ = await _render(personal=_not_entitled())
        rows = await _keyboard(tg_proxy, result)
        markup = InlineKeyboardMarkup(inline_keyboard=rows)

        flat = [b for row in markup.model_dump(exclude_none=True)["inline_keyboard"] for b in row]
        assert flat[1]["style"] == "primary"
        assert '"style":"primary"' in markup.model_dump_json(exclude_none=True)
