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
        rows = sorted(
            ((m.encode(), s) for m, s in self.zsets.get(key, {}).items()), key=lambda r: r[1]
        )
        return rows if withscores else [m for m, _ in rows]

    def members(self, key: str) -> dict[str, float]:
        return dict(self.zsets.get(key, {}))


class KvRedis:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.zsets: dict[str, dict[str, float]] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str):
        value = self.values.get(key)
        return value.encode() if isinstance(value, str) else value

    async def set(self, key: str, value: Any, nx: bool = False, ex: Optional[int] = None):
        if nx and key in self.values:
            return None
        self.values[key] = value
        if ex:
            self.ttls[key] = ex
        return True

    async def delete(self, *keys: str) -> int:
        return sum(self.values.pop(key, None) is not None for key in keys)

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
        hi = float("inf") if high == "+inf" else float(high)
        lo = float("-inf") if low == "-inf" else float(low)
        rows = sorted(
            (item for item in self.zsets.get(key, {}).items() if lo <= item[1] <= hi),
            key=lambda item: item[1],
        )
        if withscores:
            return [(member.encode(), score) for member, score in rows]
        return [member.encode() for member, _ in rows]


class FakeBilling:
    """Records reminder claims exactly like billing's unique (user, kind, key) row."""

    def __init__(self) -> None:
        self.claims: dict[tuple[int, str, str], Optional[str]] = {}
        self.answer_texts: dict[tuple[int, str, str], str] = {}
        self.subscriptions: list[Any] = []
        self.by_id: dict[int, Any] = {}
        self.release_calls = 0
        self.claim_error: Optional[Exception] = None
        self.referrals: dict[int, Any] = {}
        self.referral_error: Optional[Exception] = None
        self.referral_lookups: list[int] = []
        self.transactions: dict[int, list[Any]] = {}
        self.current_subscriptions: dict[int, Any] = {}
        self.activated: list[tuple[str, int]] = []
        self.activate_error: Optional[Exception] = None

    async def list_transactions(self, telegram_id: int):
        return list(self.transactions.get(telegram_id, []))

    async def get_current_subscription(self, telegram_id: int):
        return self.current_subscriptions.get(telegram_id)

    async def activate_promocode(self, code: str, telegram_id: int) -> None:
        if self.activate_error:
            raise self.activate_error
        self.activated.append((code, telegram_id))

    async def get_referral_by_referred(self, telegram_id: int):
        self.referral_lookups.append(telegram_id)
        if self.referral_error:
            raise self.referral_error
        return self.referrals.get(telegram_id)

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

    async def answer_user_reminder(
        self, telegram_id, kind, dedup_key, answer, answer_text: str = ""
    ) -> bool:
        ref = (telegram_id, kind, dedup_key)
        if ref not in self.claims:
            return False
        self.claims[ref] = answer
        if answer_text:
            self.answer_texts[ref] = answer_text
        else:
            self.answer_texts.pop(ref, None)
        return True

    async def list_user_reminders(self, telegram_id: int, kind: str = ""):
        return [
            SimpleNamespace(telegram_id=t, kind=k, dedup_key=d, answer=a)
            for (t, k, d), a in self.claims.items()
            if t == telegram_id and (not kind or k == kind)
        ]

    async def list_expiring_subscriptions(self, expires_after, expires_until):
        """Same contract as billing: (after, until] over ACTIVE subscriptions."""
        return [sub for sub in self.subscriptions if expires_after < sub.ExpireAt <= expires_until]

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
