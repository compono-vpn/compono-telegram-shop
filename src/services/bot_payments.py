"""Which payment methods the bot sells with.

Telegram Stars is always offered. Ruble gateways (Platega SBP and the other ruble gateways the bot
offered before v0.61.5) are offered next to Stars while APP_BOT_RUBLE_PAYMENTS is on (the default,
owner decision 2026-11-18). With it off the bot sells for Telegram Stars only (bot terms 6.2) and
points people who want rubles to @compono_support. Crypto gateways and TON never appear in the bot
checkout, whatever billing's is_active flag says.

Telegram invoices (pre-checkout, successful_payment) are always Stars: use is_stars_gateway there.
"""

from typing import Any, Iterable, Optional

from src.core.config.base import BaseConfig
from src.core.enums import Currency, PaymentGatewayType

STARS_GATEWAYS = frozenset({PaymentGatewayType.TELEGRAM_STARS.value})
# Ruble gateways the pre-v0.61.5 checkout offered. Crypto (PLATEGA_CRYPTO, PLAIDLY, CRYPTOMUS,
# HELEKET, CRYPTOPAY) and TON stay out of the bot.
RUBLE_GATEWAYS = frozenset(
    {
        PaymentGatewayType.PLATEGA.value,
        PaymentGatewayType.YOOKASSA.value,
        PaymentGatewayType.YOOMONEY.value,
        PaymentGatewayType.ROBOKASSA.value,
    }
)
# Kept for the Stars-only mode and Stars-only callers.
BOT_PAYMENT_GATEWAYS = STARS_GATEWAYS
BOT_CURRENCY = Currency.XTR.value
BOT_CHANNELS = ("BOT", "ALL")
RUBLE_SUPPORT_URL = "https://t.me/compono_support"


class BotPaymentsConfig(BaseConfig, env_prefix="APP_BOT_"):
    ruble_payments: bool = True


def ruble_payments_enabled() -> bool:
    """APP_BOT_RUBLE_PAYMENTS (default true). Read on every call so a test or restart flips it."""
    return BotPaymentsConfig().ruble_payments


def gateway_value(gateway_type: Any) -> str:
    return gateway_type.value if hasattr(gateway_type, "value") else str(gateway_type)


def is_stars_gateway(gateway_type: Any) -> bool:
    return gateway_value(gateway_type) in STARS_GATEWAYS


def allowed_gateway_types() -> frozenset[str]:
    if ruble_payments_enabled():
        return STARS_GATEWAYS | RUBLE_GATEWAYS
    return STARS_GATEWAYS


def is_bot_payment_gateway(gateway_type: Any) -> bool:
    """True for a method the bot may create a payment with (Stars, plus rubles when enabled)."""
    return gateway_value(gateway_type) in allowed_gateway_types()


def bot_gateways(gateways: Iterable[Any]) -> list[Any]:
    """Billing gateway rows the bot may offer: active, BOT/ALL channel, an allowed type."""
    allowed = allowed_gateway_types()
    return [
        g
        for g in gateways
        if g.IsActive and g.Channel in BOT_CHANNELS and gateway_value(g.Type) in allowed
    ]


async def display_currency(billing: Any) -> str:
    """Currency of the prices the bot shows: billing's default (RUB) with rubles on, else XTR."""
    if ruble_payments_enabled():
        return await billing.get_default_currency()
    return BOT_CURRENCY


async def offered_plan(billing: Any, telegram_id: int, plan_id: int) -> Optional[Any]:
    """The plan only if billing's plan list offers it to this user, else None.

    Billing's payment creation accepts any plan id, so every checkout entry (a plan button, an
    old reminder, the 30% offer) must sell only an offered plan: never the trial, the proxy plan
    (billing records it without the user's discount, the invoice would carry it) or an archived
    plan.
    """
    if not plan_id:
        return None
    offered = await billing.get_available_plans(telegram_id)
    return next((p for p in offered if p.ID == plan_id), None)
