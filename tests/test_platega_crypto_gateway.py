from __future__ import annotations

from pathlib import Path

from fluentogram import TranslatorHub
from fluentogram.storage import FileStorage

from src.core.enums import Currency, GatewayChannel, Locale, PaymentGatewayType
from src.infrastructure.billing.converters import billing_gateway_to_dto
from src.infrastructure.billing.models import BillingPaymentGateway


def test_billing_platega_crypto_gateway_converts() -> None:
    dto = billing_gateway_to_dto(
        BillingPaymentGateway(
            ID=9, Type="PLATEGA_CRYPTO", Channel="BOT", Currency="RUB", IsActive=True
        )
    )

    assert dto.type == PaymentGatewayType.PLATEGA_CRYPTO
    assert dto.channel == GatewayChannel.BOT
    assert dto.currency == Currency.RUB


def test_platega_crypto_currency_is_rub() -> None:
    assert Currency.from_gateway_type(PaymentGatewayType.PLATEGA_CRYPTO) == Currency.RUB


def test_platega_crypto_has_russian_label() -> None:
    storage = FileStorage(path=Path("assets/translations") / "{locale}")
    hub = TranslatorHub({"ru": ("ru",)}, root_locale="ru", storage=storage)
    translator = hub.get_translator_by_locale(locale=Locale.RU)

    assert translator.get("gateway-type", gateway_type="PLATEGA_CRYPTO") == "🪙 Криптовалюта"
