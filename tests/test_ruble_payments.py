"""APP_BOT_RUBLE_PAYMENTS=true (the default, owner 2026-11-18): rubles (Platega) next to Stars.

Every test here is marked `rubles`; the unmarked suite (tests/test_stars_only.py and others) keeps
proving the Stars-only behaviour of v0.61.5 with the flag off.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fluentogram import TranslatorHub
from fluentogram.storage import FileStorage

from src.bot.keyboards import get_payment_nudge_keyboard
from src.bot.routers.extra.payment import _pre_checkout_error
from src.bot.routers.subscription.getters import (
    confirm_getter,
    payment_method_getter,
    proxy_confirm_getter,
)
from src.bot.routers.subscription.handlers import on_payment_method_select
from src.bot.states import Subscription
from src.core.constants import PAYMENT_NUDGE_PREFIX
from src.core.enums import PaymentGatewayType
from src.infrastructure.billing.models import (
    BillingPaymentGateway,
    BillingTransaction,
)
from src.services import bot_payments
from src.services.bot_payments import (
    bot_gateways,
    display_currency,
    is_bot_payment_gateway,
    is_stars_gateway,
    ruble_payments_enabled,
)
from src.services.widgets import pick_gateway
from tests.conftest import make_experiment_service, make_i18n, make_user, unwrap_inject
from tests.test_personal_proxy_plan import (  # noqa: F401 (stars_invoice is a fixture)
    _buy,
    _buy_args,
    _not_entitled,
    _render,
    stars_invoice,
)
from tests.test_stars_only import PROD_LIKE, _billing, _dm, _NoIncentive, _plan, row

pytestmark = pytest.mark.rubles

PLATEGA_URL = "https://pay.platega.io/x"


def _hub():
    hub = TranslatorHub(
        {"ru": ("ru",)},
        root_locale="ru",
        storage=FileStorage(path=Path("assets/translations") / "{locale}"),
    )
    return hub.get_translator_by_locale("ru")


def test_the_flag_defaults_to_on_without_the_env_var(monkeypatch):
    monkeypatch.delenv("APP_BOT_RUBLE_PAYMENTS", raising=False)
    assert bot_payments.BotPaymentsConfig().ruble_payments is True


def test_the_flag_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("APP_BOT_RUBLE_PAYMENTS", "false")
    assert ruble_payments_enabled() is False


class TestGatewayFilter:
    def test_platega_and_stars_from_a_prod_like_list_crypto_ton_and_web_stay_out(self):
        assert [g.Type for g in bot_gateways(PROD_LIKE)] == [
            "PLATEGA",
            "TELEGRAM_STARS",
            "YOOKASSA",
        ]

    @pytest.mark.parametrize("kind", ["PLATEGA_CRYPTO", "PLAIDLY", "CRYPTOMUS", "HELEKET", "TON"])
    def test_crypto_and_ton_are_never_offered(self, kind):
        assert not is_bot_payment_gateway(kind)

    def test_telegram_invoices_stay_stars_only(self):
        assert is_stars_gateway("TELEGRAM_STARS")
        assert not is_stars_gateway("PLATEGA")

    async def test_display_currency_is_billings_default(self):
        billing = AsyncMock()
        billing.get_default_currency.return_value = "RUB"
        assert await display_currency(billing) == "RUB"


class TestCheckout:
    async def test_payment_method_screen_lists_sbp_and_stars_with_their_own_prices(self):
        billing = _billing([row("PLATEGA"), row("TELEGRAM_STARS", currency="XTR")])
        dm = _dm(_plan())
        dm.dialog_data["selected_duration"] = 30

        result = await unwrap_inject(payment_method_getter)(
            dm, make_user(), billing, make_i18n(), MagicMock(), _NoIncentive()
        )

        methods = [(m["gateway_type"], m["currency"]) for m in result["payment_methods"]]
        assert methods == [
            (PaymentGatewayType.PLATEGA, "₽"),
            (PaymentGatewayType.TELEGRAM_STARS, "★"),
        ]
        currencies = {c.kwargs["currency"] for c in billing.calculate_price.await_args_list}
        assert currencies == {"RUB", "XTR"}
        assert result["stars_only"] == 0

    async def test_choosing_sbp_creates_a_platega_ruble_payment_with_billings_link(self, invoice):
        billing = _billing([row("PLATEGA"), row("TELEGRAM_STARS", currency="XTR")])
        billing.create_payment.return_value = MagicMock(ID=str(uuid4()), URL=PLATEGA_URL)
        dm = _dm(_plan())
        dm.dialog_data["selected_duration"] = 30

        await unwrap_inject(on_payment_method_select)(
            MagicMock(), MagicMock(), dm, PaymentGatewayType.PLATEGA, billing, make_experiment_service(),
            _NoIncentive(), AsyncMock(), AsyncMock(),
        )  # fmt: skip

        kwargs = billing.create_payment.await_args.kwargs
        assert (kwargs["gateway_type"], kwargs["currency"]) == ("PLATEGA", "RUB")
        invoice.assert_not_awaited()
        assert dm.dialog_data["payment_url"] == PLATEGA_URL
        dm.switch_to.assert_awaited_with(state=Subscription.CONFIRM)

    async def test_choosing_stars_still_makes_an_xtr_invoice(self, invoice):
        billing = _billing([row("PLATEGA"), row("TELEGRAM_STARS", currency="XTR")])
        dm = _dm(_plan())
        dm.dialog_data["selected_duration"] = 30

        await unwrap_inject(on_payment_method_select)(
            MagicMock(), MagicMock(), dm, PaymentGatewayType.TELEGRAM_STARS, billing, make_experiment_service(),
            _NoIncentive(), AsyncMock(), AsyncMock(),
        )  # fmt: skip

        kwargs = billing.create_payment.await_args.kwargs
        assert (kwargs["gateway_type"], kwargs["currency"]) == ("TELEGRAM_STARS", "XTR")
        invoice.assert_awaited_once()

    @pytest.mark.parametrize("method", ["PLATEGA_CRYPTO", "TON", "PLAIDLY"])
    async def test_a_forged_crypto_press_creates_nothing(self, method):
        billing = _billing()
        dm = _dm(_plan())
        dm.dialog_data["selected_duration"] = 30

        await unwrap_inject(on_payment_method_select)(
            MagicMock(), MagicMock(), dm, PaymentGatewayType(method), billing, make_experiment_service(),
            _NoIncentive(), AsyncMock(), AsyncMock(),
        )  # fmt: skip

        billing.create_payment.assert_not_awaited()

    async def test_confirm_hides_the_ruble_note(self):
        billing = _billing([row("PLATEGA"), row("TELEGRAM_STARS", currency="XTR")])
        billing.get_gateway_by_type.side_effect = None
        billing.get_gateway_by_type.return_value = row("PLATEGA")
        dm = _dm(_plan())
        dm.dialog_data.update(
            selected_duration=30,
            selected_payment_method=PaymentGatewayType.PLATEGA,
            payment_url=PLATEGA_URL,
            final_pricing='{"original_amount": "119", "final_amount": "119"}',
        )

        result = await unwrap_inject(confirm_getter)(dm, make_i18n(), billing)

        assert result["currency"] == "₽"
        assert result["show_ruble_note"] == 0
        assert result["only_single_gateway"] is False


@pytest.fixture
def invoice(monkeypatch):
    link = AsyncMock(return_value="https://t.me/$invoice")
    monkeypatch.setattr("src.bot.routers.subscription.handlers.create_stars_invoice_link", link)
    return link


class TestPreCheckout:
    async def test_a_platega_payment_is_never_paid_with_a_telegram_invoice(self):
        user = make_user(telegram_id=777)
        billing = AsyncMock()
        billing.get_transaction.return_value = BillingTransaction(
            UserTelegramID=777, GatewayType="PLATEGA", Status="PENDING"
        )
        error = await _pre_checkout_error(billing, AsyncMock(), user, uuid4())
        assert error is not None


class TestNudge:
    def test_keyboard_has_pay_and_other_method(self):
        payment_id = str(uuid4())
        keyboard = get_payment_nudge_keyboard(PLATEGA_URL, payment_id=payment_id, stars=False)
        (buttons,) = keyboard.inline_keyboard
        assert buttons[0].text == "btn-payment-nudge-pay-rub" and buttons[0].url == PLATEGA_URL
        assert buttons[1].callback_data == f"{PAYMENT_NUDGE_PREFIX}{payment_id}"

    def test_copy_renders_for_a_ruble_payment(self):
        i18n = _hub()
        text = i18n.get("ntf-payment-nudge", plan="⚡️ Старт", price="119 ₽", stars=0)
        assert "119 ₽" in text and "другой способ" in text
        assert i18n.get("btn-payment-nudge-other") == "🔄 Другой способ"
        offer = i18n.get("ntf-recovery-offer", stars_only=0)
        assert "звёзд" not in offer and "способ оплаты" in offer


class TestTexts:
    def test_payment_method_and_confirm_texts_have_no_ruble_note(self):
        i18n = _hub()
        assert "недоступна" not in i18n.get(
            "msg-subscription-payment-method",
            stars_only=0, plan="P", description=0, type="BOTH", devices="1", traffic="1",
            period="30", final_amount=0, currency="",
        )  # fmt: skip
        assert i18n.get("btn-subscription-pay", payment_method="PLATEGA") == "💳 Оплатить"
        assert i18n.get("btn-subscription-pay", payment_method="TELEGRAM_STARS") == (
            "⭐ Оплатить звёздами"
        )
        assert i18n.get("btn-proxy-pay", stars_only=0, price="49 ₽") == "💳 Оплатить 49 ₽"


class TestProxy:
    async def test_offer_shows_the_ruble_price(self):
        result, _ = await _render(personal=_not_entitled())
        assert "<b>25 ₽ в месяц</b>" in result["proxy_message"]
        assert result["can_buy_proxy"] is True

    async def test_buy_creates_a_platega_payment_and_opens_confirm(self, stars_invoice):
        user, dm, billing, notification = _buy_args(
            _not_entitled(),
            create_result=MagicMock(ID=str(uuid4()), URL=PLATEGA_URL),
            recorded_stars="25",
        )
        billing.get_gateway_by_type.return_value = BillingPaymentGateway(
            Type="PLATEGA", Channel="BOT", Currency="RUB", IsActive=True
        )

        await _buy(dm, billing, notification)

        kwargs = billing.create_payment.await_args.kwargs
        assert (kwargs["gateway_type"], kwargs["currency"]) == ("PLATEGA", "RUB")
        stars_invoice.assert_not_awaited()
        assert dm.start.await_args.kwargs["data"] == {
            "payment_url": PLATEGA_URL,
            "price": "25 ₽",
            "rubles": 1,
        }
        notification.notify_user.assert_not_awaited()

    async def test_buy_uses_the_bot_row_when_billing_by_type_returns_the_web_row(
        self, stars_invoice
    ):
        # Prod billing has PLATEGA WEB (id 8) and PLATEGA BOT (id 7) with the same order_index;
        # /gateways/by-type returns the WEB row (verified 2026-11-18). The bot must still sell.
        user, dm, billing, notification = _buy_args(
            _not_entitled(),
            create_result=MagicMock(ID=str(uuid4()), URL=PLATEGA_URL),
            recorded_stars="25",
        )
        web = BillingPaymentGateway(Type="PLATEGA", Channel="WEB", Currency="RUB", IsActive=True)
        bot = BillingPaymentGateway(Type="PLATEGA", Channel="BOT", Currency="RUB", IsActive=True)
        billing.get_gateway_by_type.return_value = web
        billing.list_active_gateways.return_value = [web, bot]

        await _buy(dm, billing, notification)

        kwargs = billing.create_payment.await_args.kwargs
        assert (kwargs["gateway_type"], kwargs["currency"]) == ("PLATEGA", "RUB")
        notification.notify_user.assert_not_awaited()

    async def test_confirm_getter(self):
        from tests.conftest import make_dialog_manager  # noqa: PLC0415

        dm = make_dialog_manager()
        dm.start_data = {"payment_url": PLATEGA_URL, "price": "25 ₽", "rubles": 1}
        assert (await proxy_confirm_getter(dm))["stars_only"] == 0

    async def test_without_a_ruble_price_the_proxy_falls_back_to_stars(self):
        personal = _not_entitled()
        personal.price_rub = None
        result, _ = await _render(personal=personal)
        assert "49 ★" in result["proxy_message"]


def test_widgets_stay_stars_only():
    gateways = [
        BillingPaymentGateway(Type="PLATEGA", Channel="BOT", Currency="RUB", IsActive=True),
        BillingPaymentGateway(Type="TELEGRAM_STARS", Channel="BOT", Currency="XTR", IsActive=True),
    ]
    assert pick_gateway(gateways, "star").Type == "TELEGRAM_STARS"
    assert pick_gateway(gateways, "pay") is None
