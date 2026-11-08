from decimal import Decimal
from uuid import UUID

from aiogram import Bot
from aiogram.types import LabeledPrice

STARS_CURRENCY = "XTR"
TITLE_LIMIT = 32
DESCRIPTION_LIMIT = 255


def stars_amount(amount: Decimal) -> int:
    stars = int(amount)
    if stars < 1 or stars != amount:
        raise ValueError(f"Telegram Stars price must be a whole number of stars >= 1, got {amount}")
    return stars


async def create_stars_invoice_link(
    bot: Bot,
    *,
    payment_id: UUID,
    title: str,
    description: str,
    amount: Decimal,
) -> str:
    return await bot.create_invoice_link(
        title=title[:TITLE_LIMIT],
        description=description[:DESCRIPTION_LIMIT],
        payload=str(payment_id),
        currency=STARS_CURRENCY,
        prices=[LabeledPrice(label=STARS_CURRENCY, amount=stars_amount(amount))],
    )
