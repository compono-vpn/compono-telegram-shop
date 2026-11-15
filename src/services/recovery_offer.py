from enum import StrEnum
from typing import Optional

from loguru import logger

from src.bot.keyboards import get_recovery_offer_keyboard
from src.core.enums import TransactionStatus
from src.infrastructure.billing import BillingClient
from src.infrastructure.billing.client import BillingClientError
from src.models.dto import UserDto

KIND = "RETURN_OFFER"
DEDUP_KEY = "v1"
PROMO_CODE = "RETURN30"
PERCENT = 30

__all__ = [
    "DEDUP_KEY",
    "KIND",
    "PERCENT",
    "PROMO_CODE",
    "OfferActivation",
    "activate_offer",
    "claim_offer",
    "get_recovery_offer_keyboard",
    "has_paid",
    "release_offer",
]


class OfferActivation(StrEnum):
    ACTIVATED = "ACTIVATED"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"


def _paid_amount(transaction: object) -> bool:
    pricing = getattr(transaction, "Pricing", None)
    raw = getattr(pricing, "final_amount", "0") if pricing is not None else "0"
    try:
        return float(raw) > 0
    except (TypeError, ValueError):
        return False


async def has_paid(billing: BillingClient, telegram_id: int) -> bool:
    for transaction in await billing.list_transactions(telegram_id):
        if transaction.Status == TransactionStatus.COMPLETED.value and _paid_amount(transaction):
            return True
    subscription = await billing.get_current_subscription(telegram_id)
    return bool(subscription and subscription.Status == "ACTIVE" and not subscription.IsTrial)


async def claim_offer(billing: BillingClient, user: UserDto) -> bool:
    try:
        if await has_paid(billing, user.telegram_id):
            return False
        return await billing.claim_user_reminder(user.telegram_id, KIND, DEDUP_KEY)
    except Exception:
        logger.opt(exception=True).warning(f"Could not claim the offer for '{user.telegram_id}'")
        return False


async def release_offer(billing: BillingClient, telegram_id: int) -> None:
    try:
        await billing.release_user_reminder(telegram_id, KIND, DEDUP_KEY)
    except Exception:
        logger.opt(exception=True).warning(f"Could not release the offer for '{telegram_id}'")


async def activate_offer(billing: BillingClient, telegram_id: int) -> OfferActivation:
    try:
        await billing.activate_promocode(code=PROMO_CODE, telegram_id=telegram_id)
    except BillingClientError as error:
        if error.status_code == 409:
            return OfferActivation.ACTIVATED
        if error.status_code in (403, 404):
            logger.warning(f"Offer promocode refused for '{telegram_id}': {error}")
            return OfferActivation.UNAVAILABLE
        logger.warning(f"Offer promocode failed for '{telegram_id}': {error}")
        return OfferActivation.FAILED
    except Exception:
        logger.opt(exception=True).warning(f"Offer promocode failed for '{telegram_id}'")
        return OfferActivation.FAILED
    return OfferActivation.ACTIVATED


def offer_payment_id(raw: str) -> Optional[str]:
    return None if raw in ("", "-") else raw
