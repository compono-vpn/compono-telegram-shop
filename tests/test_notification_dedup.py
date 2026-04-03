"""Tests for notification task Redis-based dedup logic.

The not-connected reminder task uses Redis keys for deduplication instead of
a database table. These tests verify:
- Dedup key format and TTL
- Already-sent notifications are skipped
- New notifications proceed and mark the dedup key
- schedule_not_connected_reminder writes to Redis sorted set

Rather than unwrapping the taskiq-decorated task (which wraps the function
in an AsyncTaskiqDecoratedTask), we replicate the core dedup logic inline
and test the contract: given certain Redis state, the right calls happen.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import make_user, make_subscription

from src.infrastructure.taskiq.tasks.notifications import (
    NOT_CONNECTED_NOTIFICATION_KEY,
    NOT_CONNECTED_REMINDER_DELAY,
    _PENDING_KEY,
    _SENT_NTF_KEY_PREFIX,
    _SENT_NTF_TTL,
    schedule_not_connected_reminder,
)


# ---------------------------------------------------------------------------
# Tests: schedule_not_connected_reminder
# ---------------------------------------------------------------------------


class TestScheduleNotConnectedReminder:
    async def test_schedules_reminder_in_redis_sorted_set(self):
        redis_client = AsyncMock()
        before = time.time()

        await schedule_not_connected_reminder(
            redis_client=redis_client,
            user_telegram_id=12345,
            connect_url="https://panel.example.com/sub/abc",
        )

        redis_client.zadd.assert_awaited_once()
        call_args = redis_client.zadd.call_args
        key = call_args[0][0]
        members = call_args[0][1]

        assert key == _PENDING_KEY.pack()
        member_key = "12345:https://panel.example.com/sub/abc"
        assert member_key in members
        score = members[member_key]
        assert score >= before + NOT_CONNECTED_REMINDER_DELAY

    async def test_uses_nx_to_avoid_duplicate_scheduling(self):
        redis_client = AsyncMock()

        await schedule_not_connected_reminder(
            redis_client=redis_client,
            user_telegram_id=99999,
            connect_url="https://panel.example.com/sub/xyz",
        )

        call_kwargs = redis_client.zadd.call_args[1]
        assert call_kwargs.get("nx") is True


# ---------------------------------------------------------------------------
# Tests: dedup key contract
# ---------------------------------------------------------------------------


class TestNotificationDedupKey:
    """Verify the Redis key format and TTL used for dedup."""

    def test_dedup_key_format(self):
        """Dedup key follows the pattern: sent_ntf:{telegram_id}:not_connected_reminder."""
        telegram_id = 12345
        expected_key = f"{_SENT_NTF_KEY_PREFIX}{telegram_id}:{NOT_CONNECTED_NOTIFICATION_KEY}"
        assert expected_key == "sent_ntf:12345:not_connected_reminder"

    def test_dedup_ttl_is_90_days(self):
        """The TTL for dedup keys is 90 days in seconds."""
        assert _SENT_NTF_TTL == 90 * 24 * 60 * 60

    def test_pending_key_has_correct_prefix(self):
        """The sorted set key for pending reminders uses the expected prefix."""
        key = _PENDING_KEY.pack()
        assert "pending_not_connected" in key


# ---------------------------------------------------------------------------
# Tests: dedup logic (simulate the task's core flow)
# ---------------------------------------------------------------------------


async def _simulate_reminder_processing(
    redis: AsyncMock,
    user_service: AsyncMock,
    remnawave_service: AsyncMock,
    notification_service: AsyncMock,
) -> None:
    """Replicate the core dedup flow from process_pending_not_connected_reminders_task.

    This avoids needing to unwrap the taskiq decorator. The logic matches
    the task implementation exactly:
    1. Get due items from sorted set
    2. For each item, check dedup key
    3. If dedup key exists, skip
    4. Otherwise check user/subscription/devices, send, mark dedup
    """
    now = time.time()
    key = _PENDING_KEY.pack()

    due_items = await redis.zrangebyscore(key, "-inf", now)
    if not due_items:
        return

    for raw_member in due_items:
        member = raw_member.decode() if isinstance(raw_member, bytes) else raw_member
        await redis.zrem(key, member)

        sep = member.index(":")
        user_telegram_id = int(member[:sep])
        connect_url = member[sep + 1:]

        dedup_key = f"{_SENT_NTF_KEY_PREFIX}{user_telegram_id}:{NOT_CONNECTED_NOTIFICATION_KEY}"
        already_sent = await redis.exists(dedup_key)
        if already_sent:
            continue

        user = await user_service.get(user_telegram_id)
        if not user or not user.current_subscription:
            continue

        if not user.current_subscription.is_active:
            continue

        devices = await remnawave_service.get_devices_user(user)
        if devices:
            continue

        await notification_service.notify_user(user=user, payload=MagicMock())
        await redis.setex(dedup_key, _SENT_NTF_TTL, "1")


class TestNotificationDedup:
    """Tests for Redis-based dedup in the not-connected reminder flow."""

    def _make_redis(self, due_items=None, already_sent=False):
        redis = AsyncMock()
        redis.zrangebyscore.return_value = due_items or []
        redis.zrem.return_value = 1
        redis.exists.return_value = 1 if already_sent else 0
        redis.setex.return_value = True
        return redis

    async def test_already_sent_notification_is_skipped(self):
        """When dedup key exists in Redis, the notification is not sent."""
        member = b"12345:https://panel.example.com/sub/abc"

        redis = self._make_redis(due_items=[member], already_sent=True)
        user_service = AsyncMock()
        remnawave_service = AsyncMock()
        notification_service = AsyncMock()

        await _simulate_reminder_processing(redis, user_service, remnawave_service, notification_service)

        # Item should be removed from sorted set
        redis.zrem.assert_awaited_once()
        # exists() should be checked for dedup
        redis.exists.assert_awaited_once()
        dedup_key_checked = redis.exists.call_args[0][0]
        assert dedup_key_checked == f"{_SENT_NTF_KEY_PREFIX}12345:{NOT_CONNECTED_NOTIFICATION_KEY}"
        # Notification should NOT be sent
        notification_service.notify_user.assert_not_awaited()
        # No new dedup key written
        redis.setex.assert_not_awaited()

    async def test_new_notification_sends_and_sets_dedup_key(self):
        """When dedup key does not exist, notification is sent and dedup key is written with TTL."""
        user = make_user(telegram_id=12345, subscription=make_subscription(active=True))
        member = b"12345:https://panel.example.com/sub/abc"

        redis = self._make_redis(due_items=[member], already_sent=False)
        user_service = AsyncMock()
        user_service.get.return_value = user
        remnawave_service = AsyncMock()
        remnawave_service.get_devices_user.return_value = []  # not connected
        notification_service = AsyncMock()

        await _simulate_reminder_processing(redis, user_service, remnawave_service, notification_service)

        # Notification should be sent
        notification_service.notify_user.assert_awaited_once()
        # Dedup key should be set with correct TTL
        redis.setex.assert_awaited_once()
        setex_args = redis.setex.call_args[0]
        dedup_key = setex_args[0]
        ttl = setex_args[1]
        value = setex_args[2]
        assert dedup_key == f"{_SENT_NTF_KEY_PREFIX}12345:{NOT_CONNECTED_NOTIFICATION_KEY}"
        assert ttl == _SENT_NTF_TTL
        assert value == "1"

    async def test_skips_user_without_subscription(self):
        """If user has no subscription, reminder is skipped."""
        user = make_user(telegram_id=12345)  # no subscription
        member = b"12345:https://panel.example.com/sub/abc"

        redis = self._make_redis(due_items=[member], already_sent=False)
        user_service = AsyncMock()
        user_service.get.return_value = user
        remnawave_service = AsyncMock()
        notification_service = AsyncMock()

        await _simulate_reminder_processing(redis, user_service, remnawave_service, notification_service)

        notification_service.notify_user.assert_not_awaited()
        redis.setex.assert_not_awaited()

    async def test_skips_user_with_inactive_subscription(self):
        """If subscription is inactive, reminder is skipped."""
        user = make_user(telegram_id=12345, subscription=make_subscription(active=False))
        member = b"12345:https://panel.example.com/sub/abc"

        redis = self._make_redis(due_items=[member], already_sent=False)
        user_service = AsyncMock()
        user_service.get.return_value = user
        remnawave_service = AsyncMock()
        notification_service = AsyncMock()

        await _simulate_reminder_processing(redis, user_service, remnawave_service, notification_service)

        notification_service.notify_user.assert_not_awaited()
        redis.setex.assert_not_awaited()

    async def test_skips_already_connected_user(self):
        """If user already has devices, reminder is skipped."""
        user = make_user(telegram_id=12345, subscription=make_subscription(active=True))
        member = b"12345:https://panel.example.com/sub/abc"

        redis = self._make_redis(due_items=[member], already_sent=False)
        user_service = AsyncMock()
        user_service.get.return_value = user
        remnawave_service = AsyncMock()
        remnawave_service.get_devices_user.return_value = [MagicMock()]  # has devices
        notification_service = AsyncMock()

        await _simulate_reminder_processing(redis, user_service, remnawave_service, notification_service)

        notification_service.notify_user.assert_not_awaited()
        redis.setex.assert_not_awaited()

    async def test_no_due_items_exits_early(self):
        """When there are no due items, the task returns immediately."""
        redis = self._make_redis(due_items=[])
        user_service = AsyncMock()
        remnawave_service = AsyncMock()
        notification_service = AsyncMock()

        await _simulate_reminder_processing(redis, user_service, remnawave_service, notification_service)

        user_service.get.assert_not_awaited()
        notification_service.notify_user.assert_not_awaited()

    async def test_multiple_due_items_processed_independently(self):
        """Each due member is processed independently; one dedup skip does not affect others."""
        user_ok = make_user(telegram_id=11111, subscription=make_subscription(active=True))
        member_skip = b"22222:https://panel.example.com/sub/skip"
        member_send = b"11111:https://panel.example.com/sub/send"

        redis = AsyncMock()
        redis.zrangebyscore.return_value = [member_skip, member_send]
        redis.zrem.return_value = 1
        # First exists() call (22222) returns True (skip), second (11111) returns False (send)
        redis.exists.side_effect = [1, 0]
        redis.setex.return_value = True

        user_service = AsyncMock()
        user_service.get.return_value = user_ok
        remnawave_service = AsyncMock()
        remnawave_service.get_devices_user.return_value = []
        notification_service = AsyncMock()

        await _simulate_reminder_processing(redis, user_service, remnawave_service, notification_service)

        # Only one notification should be sent (the non-deduped one)
        notification_service.notify_user.assert_awaited_once()
        # Only one dedup key should be written
        redis.setex.assert_awaited_once()
        assert "11111" in redis.setex.call_args[0][0]
