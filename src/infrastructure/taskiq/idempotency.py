"""Idempotency guards for provisioning/renewal taskiq tasks.

purchase/trial/renew/change subscription tasks run with
retry_on_error=True (broker.py's SmartRetryMiddleware, count=5), and a
worker crash mid-task can also leave a Redis Stream message unacked so it
gets redelivered later. Either path re-runs the same task body from
scratch. Without a guard this can:
  - re-provision a second Remnawave user (trial / new purchase), or
  - re-apply the renew/change expiry math a second time (free paid time).

The guard is a Redis marker set immediately *after* the Remnawave-side
mutation succeeds, keyed on a value that stays stable across retries of
the same logical purchase (payment_id) or trial grant (telegram_id).
Checking it *before* the mutation and only setting it *after* the
mutation succeeds means a genuine failure before any mutation happened
never blocks a legitimate retry -- only a second mutation attempt for an
operation that already succeeded is skipped.
"""

from redis.asyncio import Redis

from src.core.storage.key_builder import StorageKey

# Comfortably longer than any realistic retry/crash-recovery window
# (SmartRetryMiddleware maxes out at 5 attempts with backoff capped
# around 2 minutes, but a crashed worker's message may sit unacked until
# the next deploy/restart). Payment/telegram ids never repeat, so a long
# TTL just bounds Redis memory rather than gating correctness.
IDEMPOTENCY_TTL_SECONDS = 60 * 60 * 24 * 7


async def already_applied(redis_client: Redis, key: StorageKey) -> bool:
    """Return True if the mutation for this key has already succeeded."""
    return bool(await redis_client.exists(key.pack()))


async def mark_applied(redis_client: Redis, key: StorageKey) -> None:
    """Record that the mutation for this key has succeeded."""
    await redis_client.set(key.pack(), "1", ex=IDEMPOTENCY_TTL_SECONDS)
