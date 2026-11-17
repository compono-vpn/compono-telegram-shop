"""The first Telegram charge of each Stars payment, recorded in Redis.

Billing completes a payment once and asynchronously (Kafka), so a payment can stay PENDING for a
while after Telegram took the stars. The record tells the bot that the user has paid: a second
charge for the same payment is refused or refunded, and no reminder asks the user to pay again.
"""

from typing import Optional
from uuid import UUID

from loguru import logger
from redis.asyncio import Redis

CHARGE_KEY = "stars_charge:{payment_id}"
CHARGE_KEY_TTL = 7 * 24 * 3600


async def first_charge(redis_client: Redis, payment_id: UUID | str) -> Optional[str]:
    """The charge already recorded for this payment, or None (also when Redis is unavailable)."""
    try:
        value = await redis_client.get(CHARGE_KEY.format(payment_id=payment_id))
    except Exception:
        logger.opt(exception=True).warning(f"Could not read the Stars charge of '{payment_id}'")
        return None
    return value.decode() if isinstance(value, bytes) else value


async def claim_charge(redis_client: Redis, payment_id: UUID, charge_id: str) -> bool:
    """Record the payment's first charge. False only when another charge was recorded first.

    A redelivered update carries the same charge id and is not a second charge. Without Redis the
    claim cannot be checked, so the charge is treated as the first one (the behaviour before).
    """
    key = CHARGE_KEY.format(payment_id=payment_id)
    try:
        if await redis_client.set(key, charge_id, nx=True, ex=CHARGE_KEY_TTL):
            return True
    except Exception:
        logger.opt(exception=True).warning(f"Could not record the Stars charge of '{payment_id}'")
        return True
    first = await first_charge(redis_client, payment_id)
    return first is None or first == charge_id
