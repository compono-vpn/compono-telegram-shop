from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from fluentogram import TranslatorRunner
from loguru import logger

from src.core.enums import Currency
from src.core.utils.formatters import i18n_format_days
from src.infrastructure.billing import BillingClient
from src.infrastructure.billing.models import BillingPlan
from src.services.payment_nudge import format_price_text

MONTH_DAYS = 30


def _trial_terms(i18n: TranslatorRunner, trial_plan: BillingPlan) -> str | bool:
    days = min((d.Days for d in trial_plan.Durations if d.Days > 0), default=0)
    if not days:
        return False
    key, kwargs = i18n_format_days(days)
    return ", ".join(
        [
            i18n.get(key, **kwargs),
            i18n.get("unit-gigabyte", value=trial_plan.TrafficLimit),
            i18n.get("unit-device", value=trial_plan.DeviceLimit),
        ]
    )


def _month_price(plan: BillingPlan, currency: str) -> Optional[Decimal]:
    if not plan.IsActive or plan.Type == "PROXY" or plan.Availability == "TRIAL":
        return None
    for duration in plan.Durations:
        if duration.Days != MONTH_DAYS:
            continue
        for price in duration.Prices:
            if price.Currency != currency:
                continue
            try:
                return Decimal(price.Price)
            except InvalidOperation:
                return None
    return None


async def _price_from(billing: BillingClient, telegram_id: int) -> str | bool:
    try:
        currency = await billing.get_default_currency()
        plans = await billing.get_available_plans(telegram_id)
        prices = [p for p in (_month_price(plan, currency) for plan in plans) if p and p > 0]
        if not prices:
            return False
        return f"{format_price_text(min(prices), Currency(currency).value)}/мес"
    except Exception:
        logger.opt(exception=True).warning("Could not read the cheapest plan price")
        return False


async def first_screen_terms(
    billing: BillingClient,
    i18n: TranslatorRunner,
    trial_plan: Optional[BillingPlan],
    telegram_id: int,
) -> dict[str, Any]:
    if trial_plan is None:
        return {"trial_terms": False, "price_from": False}
    return {
        "trial_terms": _trial_terms(i18n, trial_plan),
        "price_from": await _price_from(billing, telegram_id),
    }
