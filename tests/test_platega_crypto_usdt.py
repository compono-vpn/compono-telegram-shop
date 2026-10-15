from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from fluentogram import TranslatorHub
from fluentogram.storage import FileStorage

from src.core.enums import Currency, Locale, PaymentGatewayType
from src.infrastructure.billing.converters import billing_gateway_to_dto
from src.infrastructure.billing.models import BillingPaymentGateway


def _translator():
    storage = FileStorage(path=Path("assets/translations") / "{locale}")
    hub = TranslatorHub({"ru": ("ru",)}, root_locale="ru", storage=storage)
    return hub.get_translator_by_locale(locale=Locale.RU)


def test_usdt_currency_symbol() -> None:
    assert Currency("USDT").symbol == "USDT"


def test_platega_crypto_default_currency_is_usdt() -> None:
    assert Currency.from_gateway_type(PaymentGatewayType.PLATEGA_CRYPTO) == Currency.USDT


def test_billing_usdt_gateway_converts() -> None:
    dto = billing_gateway_to_dto(
        BillingPaymentGateway(
            ID=9, Type="PLATEGA_CRYPTO", Channel="BOT", Currency="USDT", IsActive=True
        )
    )

    assert dto.currency == Currency.USDT


def test_payment_amount_spaces_usdt() -> None:
    text = _translator().get(
        "frg-payment-amount",
        final_amount=Decimal("1"),
        original_amount=Decimal("1"),
        currency="USDT",
        discount_percent=0,
    )

    assert text.startswith("1 USDT")


def test_payment_amount_keeps_ruble_format() -> None:
    text = _translator().get(
        "frg-payment-amount",
        final_amount=Decimal("119"),
        original_amount=Decimal("119"),
        currency="₽",
        discount_percent=0,
    )

    assert text.startswith("119₽")
