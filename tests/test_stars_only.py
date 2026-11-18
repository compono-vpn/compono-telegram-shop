"""The bot sells only for Telegram Stars (Telegram bot terms 6.2).

Billing may return other active BOT gateways (prod has PLATEGA BOT RUB active today); the bot must
ignore them in every checkout path and must never show a ruble, card, SBP, crypto or website
payment in the texts users see.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.routers.subscription.getters import confirm_getter, payment_method_getter
from src.bot.routers.subscription.handlers import (
    on_duration_select,
    on_payment_method_select,
    on_subscription_plans,
)
from src.bot.states import Subscription
from src.core.constants import PURCHASE_PREFIX, USER_KEY
from src.core.enums import PaymentGatewayType, PurchaseType
from src.infrastructure.billing.models import BillingPaymentGateway, BillingPriceDetails
from src.models.dto import PlanDto
from src.models.dto.plan import PlanDurationDto
from src.services.bot_payments import (
    BOT_CURRENCY,
    RUBLE_SUPPORT_URL,
    bot_gateways,
    is_bot_payment_gateway,
)
from tests.conftest import (
    make_dialog_manager,
    make_experiment_service,
    make_i18n,
    make_user,
    unwrap_inject,
)

TRANSLATIONS = Path("assets/translations/ru")


def row(kind: str, channel: str = "BOT", currency: str = "RUB", active: bool = True):
    return BillingPaymentGateway(Type=kind, Channel=channel, Currency=currency, IsActive=active)


# What prod billing returns today plus every other gateway the bot used to know.
PROD_LIKE = [
    row("PLATEGA"),
    row("PLATEGA", channel="WEB"),
    row("PLATEGA_CRYPTO", currency="USDT"),
    row("TELEGRAM_STARS", currency="XTR"),
    row("YOOKASSA"),
    row("TON", channel="ALL", currency="TON"),
    row("PLAIDLY", currency="USD"),
    row("CRYPTOMUS", channel="ALL", currency="USD"),
]


class TestGatewayFilter:
    def test_only_stars_survives_from_a_prod_like_list(self):
        assert [g.Type for g in bot_gateways(PROD_LIKE)] == ["TELEGRAM_STARS"]

    @pytest.mark.parametrize(
        "gateway",
        [
            row("TELEGRAM_STARS", channel="WEB", currency="XTR"),
            row("TELEGRAM_STARS", currency="XTR", active=False),
        ],
    )
    def test_stars_on_the_web_channel_or_inactive_is_not_offered(self, gateway):
        assert bot_gateways([gateway]) == []

    def test_stars_on_the_all_channel_is_offered(self):
        assert len(bot_gateways([row("TELEGRAM_STARS", channel="ALL", currency="XTR")])) == 1

    @pytest.mark.parametrize("kind", [t for t in PaymentGatewayType if t.value != "TELEGRAM_STARS"])
    def test_every_other_gateway_type_is_refused(self, kind):
        assert not is_bot_payment_gateway(kind)
        assert not is_bot_payment_gateway(kind.value)
        assert bot_gateways([row(kind.value)]) == []

    def test_the_bot_currency_is_stars(self):
        assert BOT_CURRENCY == "XTR"
        assert RUBLE_SUPPORT_URL == "https://t.me/compono_support"


def _plan(durations=(30,)) -> PlanDto:
    return PlanDto(
        id=1,
        name="⚡️ Старт",
        durations=[PlanDurationDto(id=d, days=d, prices=[]) for d in durations],
    )


def _billing(gateways=PROD_LIKE) -> AsyncMock:
    billing = AsyncMock()
    billing.list_active_gateways.return_value = list(gateways)
    billing.get_default_currency.return_value = "RUB"  # prod setting, must be ignored
    billing.get_gateway_by_type.side_effect = lambda t: next(
        (g for g in gateways if g.Type == t and g.Channel in ("BOT", "ALL")), None
    )
    billing.calculate_price.return_value = BillingPriceDetails(
        original_amount="119", discount_percent=0, final_amount="119"
    )
    billing.create_payment.return_value = MagicMock(
        ID="3fa85f64-5717-4562-b3fc-2c963f66afa6", URL=None
    )
    return billing


def _dm(plan: PlanDto) -> MagicMock:
    dm = make_dialog_manager()
    dm.middleware_data[USER_KEY] = make_user(telegram_id=777)
    dm.middleware_data["bot"] = MagicMock()
    dm.dialog_data["plandto"] = plan.model_dump()
    dm.dialog_data["purchase_type"] = PurchaseType.NEW
    dm.switch_to = AsyncMock()
    return dm


class _NoIncentive:
    async def discount_context(self, user, **kwargs):
        return None


@pytest.fixture(autouse=True)
def invoice(monkeypatch):
    link = AsyncMock(return_value="https://t.me/$invoice")
    monkeypatch.setattr("src.bot.routers.subscription.handlers.create_stars_invoice_link", link)
    return link


class TestCheckout:
    async def test_payment_method_screen_lists_only_stars_priced_in_stars(self):
        billing = _billing()
        dm = _dm(_plan())
        dm.dialog_data["selected_duration"] = 30

        result = await unwrap_inject(payment_method_getter)(
            dm, make_user(), billing, make_i18n(), MagicMock(), _NoIncentive()
        )

        assert [m["gateway_type"] for m in result["payment_methods"]] == [
            PaymentGatewayType.TELEGRAM_STARS
        ]
        assert result["payment_methods"][0]["currency"] == "★"
        currencies = {c.kwargs["currency"] for c in billing.calculate_price.await_args_list}
        assert currencies == {"XTR"}

    async def test_duration_select_goes_straight_to_a_stars_invoice(self, invoice):
        billing = _billing()
        dm = _dm(_plan())

        await unwrap_inject(on_duration_select)(
            MagicMock(), MagicMock(), dm, 30, billing, make_experiment_service(), _NoIncentive(),
            AsyncMock(), AsyncMock(),
        )  # fmt: skip

        kwargs = billing.create_payment.await_args.kwargs
        assert (kwargs["gateway_type"], kwargs["currency"]) == ("TELEGRAM_STARS", "XTR")
        assert {c.kwargs["currency"] for c in billing.calculate_price.await_args_list} == {"XTR"}
        invoice.assert_awaited_once()
        assert dm.dialog_data["payment_url"] == "https://t.me/$invoice"
        dm.switch_to.assert_awaited_with(state=Subscription.CONFIRM)

    @pytest.mark.parametrize("method", ["PLATEGA", "PLATEGA_CRYPTO", "YOOKASSA", "TON", "PLAIDLY"])
    async def test_a_forged_method_press_creates_nothing(self, method):
        billing = _billing()
        dm = _dm(_plan())
        dm.dialog_data["selected_duration"] = 30

        await unwrap_inject(on_payment_method_select)(
            MagicMock(), MagicMock(), dm, PaymentGatewayType(method), billing, make_experiment_service(),
            _NoIncentive(), AsyncMock(), AsyncMock(),
        )  # fmt: skip

        billing.create_payment.assert_not_awaited()
        dm.switch_to.assert_not_awaited()

    async def test_without_stars_the_bot_says_no_gateways_instead_of_offering_rubles(self):
        billing = _billing([row("PLATEGA"), row("PLATEGA_CRYPTO", currency="USDT")])
        billing.get_available_plans.return_value = [MagicMock()]
        dm = _dm(_plan())
        notification = AsyncMock()
        callback = SimpleNamespace(data=f"{PURCHASE_PREFIX}{PurchaseType.NEW}")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "src.bot.routers.subscription.handlers.billing_plan_to_dto", lambda p: _plan()
            )
            await unwrap_inject(on_subscription_plans)(
                callback, MagicMock(), dm, billing, make_experiment_service(), _NoIncentive(), notification,
                AsyncMock(),
            )  # fmt: skip

        payload = notification.notify_user.await_args.kwargs["payload"]
        assert payload.i18n_key == "ntf-subscription-gateways-not-available"
        billing.create_payment.assert_not_awaited()

    async def test_confirm_has_no_back_to_methods_when_only_stars_is_offered(self):
        billing = _billing()
        billing.get_gateway_by_type.side_effect = None
        billing.get_gateway_by_type.return_value = row("TELEGRAM_STARS", currency="XTR")
        dm = _dm(_plan())
        dm.dialog_data.update(
            selected_duration=30,
            selected_payment_method=PaymentGatewayType.TELEGRAM_STARS,
            payment_url="https://t.me/$invoice",
            final_pricing='{"original_amount": "119", "final_amount": "119"}',
        )

        result = await unwrap_inject(confirm_getter)(dm, make_i18n(), billing)

        assert result["only_single_gateway"] is True
        assert result["currency"] == "★"
        assert result["show_ruble_note"] == 1


# ------------------------------------------------------------------ texts users see

# Keys a user can see in a purchase, proxy, nudge, offer, expiry or menu screen.
USER_KEY_PREFIXES = (
    "msg-subscription-",
    "msg-proxy-",
    "msg-menu-",
    "msg-ruble-",
    "msg-recovery-",
    "btn-subscription-",
    "btn-proxy-",
    "btn-menu-",
    "btn-payment-nudge-",
    "btn-recovery-offer-",
    "btn-cancel-survey-",
    "btn-trial-",
    "btn-ruble-",
    "ntf-payment-nudge",
    "ntf-recovery-offer",
    "ntf-event-user-expir",
    "ntf-subscription-",
    "ntf-trial-",
)
# Screens that cannot be reached any more because the bot never offers crypto.
UNREACHABLE = {"msg-subscription-crypto-asset", "btn-subscription-back-crypto-asset"}
BANNED = re.compile(r"₽|СБП|[Кк]арт[аоуы]|крипт|Platega|ЮKassa|componovpn\.com|/pricing|/purchase")


def _messages() -> dict[str, str]:
    messages: dict[str, str] = {}
    for path in sorted(TRANSLATIONS.glob("*.ftl")):
        key = None
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^([a-z][a-z0-9-]*)\s*=(.*)$", line)
            if match:
                key = match.group(1)
                messages[key] = match.group(2)
            elif key and (line.startswith(" ") or not line.strip()):
                messages[key] += "\n" + line
            else:
                key = None
    return messages


def test_no_user_facing_text_names_a_ruble_card_crypto_or_website_payment():
    messages = _messages()
    checked = {
        k: v for k, v in messages.items() if k.startswith(USER_KEY_PREFIXES) and k not in UNREACHABLE
    }
    assert "msg-subscription-confirm" in checked and "ntf-payment-nudge" in checked
    offenders = {k: BANNED.findall(v) for k, v in checked.items() if BANNED.search(v)}
    assert offenders == {}


def test_the_ruble_note_is_the_owners_line_and_names_no_website():
    note = _messages()["msg-ruble-payments-note"]
    assert "Оплата в рублях сейчас недоступна." in note
    assert "@compono_support" in note
    assert "componovpn" not in note and "http" not in note


def test_the_old_website_purchase_message_is_gone():
    assert "msg-web-purchase-redirect" not in _messages()


@pytest.mark.parametrize(
    "path",
    # proxy_view.py formats ruble prices for APP_BOT_RUBLE_PAYMENTS=true; its Stars-only texts
    # are checked in test_proxy_screen.py.
    ["src/services/widgets.py", "src/services/first_screen.py"],
)
def test_bot_source_shows_no_ruble_sign(path):
    assert "₽" not in Path(path).read_text(encoding="utf-8")
