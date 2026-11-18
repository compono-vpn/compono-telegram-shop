"""The bot sells only for Telegram Stars.

Telegram's bot terms (section 6.2) allow digital goods in a bot to be sold only for Telegram Stars,
and a bot found using other payment systems can be shut down. Billing may still return other active
BOT gateways (Platega, crypto, TON); the bot ignores them, whatever their is_active flag says.
Rubles are sold on the website; the bot only points people to @compono_support.
"""

from typing import Any, Iterable, Optional

from src.core.enums import Currency, PaymentGatewayType

BOT_PAYMENT_GATEWAYS = frozenset({PaymentGatewayType.TELEGRAM_STARS.value})
BOT_CURRENCY = Currency.XTR.value
BOT_CHANNELS = ("BOT", "ALL")
RUBLE_SUPPORT_URL = "https://t.me/compono_support"


def gateway_value(gateway_type: Any) -> str:
    return gateway_type.value if hasattr(gateway_type, "value") else str(gateway_type)


def is_bot_payment_gateway(gateway_type: Any) -> bool:
    return gateway_value(gateway_type) in BOT_PAYMENT_GATEWAYS


def bot_gateways(gateways: Iterable[Any]) -> list[Any]:
    """Billing gateway rows the bot may offer: active, BOT/ALL channel, Telegram Stars only."""
    return [
        g
        for g in gateways
        if g.IsActive and g.Channel in BOT_CHANNELS and is_bot_payment_gateway(g.Type)
    ]


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
