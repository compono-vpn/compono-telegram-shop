"""In-memory stand-ins for Redis sorted sets, billing reminder claims and Telegram sends."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock


class FakeRedis:
    def __init__(self) -> None:
        self.zsets: dict[str, dict[str, float]] = {}

    async def zadd(self, key: str, mapping: dict[str, float], nx: bool = False) -> int:
        zset = self.zsets.setdefault(key, {})
        added = 0
        for member, score in mapping.items():
            if nx and member in zset:
                continue
            added += member not in zset
            zset[member] = score
        return added

    async def zrem(self, key: str, *members: str) -> int:
        zset = self.zsets.get(key, {})
        return sum(zset.pop(member, None) is not None for member in members)

    async def zrangebyscore(self, key: str, low: Any, high: Any, withscores: bool = False):
        lo = float("-inf") if low == "-inf" else float(low)
        hi = float("inf") if high == "+inf" else float(high)
        rows = sorted(
            ((m.encode(), s) for m, s in self.zsets.get(key, {}).items() if lo <= s <= hi),
            key=lambda row: row[1],
        )
        return rows if withscores else [m for m, _ in rows]

    async def zrange(self, key: str, start: int, stop: int, withscores: bool = False):
        rows = sorted(((m.encode(), s) for m, s in self.zsets.get(key, {}).items()), key=lambda r: r[1])
        return rows if withscores else [m for m, _ in rows]

    def members(self, key: str) -> dict[str, float]:
        return dict(self.zsets.get(key, {}))


class FakeBilling:
    """Records reminder claims exactly like billing's unique (user, kind, key) row."""

    def __init__(self) -> None:
        self.claims: dict[tuple[int, str, str], Optional[str]] = {}
        self.subscriptions: list[Any] = []
        self.by_id: dict[int, Any] = {}
        self.release_calls = 0
        self.claim_error: Optional[Exception] = None

    async def claim_user_reminder(self, telegram_id: int, kind: str, dedup_key: str) -> bool:
        if self.claim_error:
            raise self.claim_error
        ref = (telegram_id, kind, dedup_key)
        if ref in self.claims:
            return False
        self.claims[ref] = None
        return True

    async def release_user_reminder(self, telegram_id: int, kind: str, dedup_key: str) -> bool:
        self.release_calls += 1
        return self.claims.pop((telegram_id, kind, dedup_key), "missing") != "missing"

    async def answer_user_reminder(self, telegram_id, kind, dedup_key, answer) -> bool:
        ref = (telegram_id, kind, dedup_key)
        if ref not in self.claims:
            return False
        self.claims[ref] = answer
        return True

    async def list_user_reminders(self, telegram_id: int, kind: str = ""):
        return [
            SimpleNamespace(telegram_id=t, kind=k, dedup_key=d, answer=a)
            for (t, k, d), a in self.claims.items()
            if t == telegram_id and (not kind or k == kind)
        ]

    async def list_expiring_subscriptions(self, expires_after, expires_until):
        """Same contract as billing: (after, until] over ACTIVE subscriptions."""
        return [
            sub
            for sub in self.subscriptions
            if expires_after < sub.ExpireAt <= expires_until
        ]

    async def get_subscription(self, subscription_id: int):
        return self.by_id.get(subscription_id)


def make_notification_service(*, result: Any = "sent", error: Optional[Exception] = None):
    """notify_user stand-in returning a message with a stable id, or raising."""
    service = MagicMock()
    messages: list[Any] = []

    async def notify_user(user, payload, ntf_type=None):
        if error:
            raise error
        if result is None:
            return None
        message = SimpleNamespace(message_id=1000 + len(messages))
        messages.append((user.telegram_id, payload, ntf_type, message))
        return message

    service.notify_user = AsyncMock(side_effect=notify_user)
    service.sent = messages
    return service


def make_settings_service(**switches: bool):
    """Per-type switches keyed by enum value; anything not listed is enabled."""
    service = MagicMock()
    service.refresh = AsyncMock()

    async def is_enabled(ntf_type) -> bool:
        return switches.get(ntf_type.value, True)

    service.is_notification_enabled = AsyncMock(side_effect=is_enabled)
    return service


class NoSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
