"""Tests for the always-on cancel-reason survey (BDT-442 foundation).

Covers:
- schedule_cancel_survey_check: writes the pending Redis sorted-set entry
  at payment-link creation time.
- _process_due_member: the 5-min sweep's per-transaction decision logic
  (poll billing, re-queue PENDING, drop terminal non-CANCELED, dedupe via
  SETNX, suppress if the user already has a paid subscription, send once).

Rather than unwrapping the taskiq-decorated cron task (wrapped in an
AsyncTaskiqDecoratedTask by dishka/taskiq), we call the extracted
_process_due_member helper directly -- same approach as
test_notification_dedup.py uses for the not-connected reminder sweep.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

from src.core.enums import TransactionStatus
from src.core.metrics import CANCEL_SURVEY_ANSWERS_TOTAL, CANCEL_SURVEY_SENT_TOTAL
from src.core.storage.keys import CancelSurveySentKey, PendingCancelSurveyChecksKey
from src.infrastructure.taskiq.tasks.cancel_survey import (
    _MAX_PENDING_AGE,
    _PENDING_KEY,
    _SENT_TTL,
    _process_due_member,
    schedule_cancel_survey_check,
)
from tests.conftest import make_user


def _make_transaction(status: str, gateway_type: str = "PLATEGA") -> MagicMock:
    return MagicMock(Status=status, GatewayType=gateway_type)


def _make_billing(
    transaction: MagicMock | None,
    subscription: MagicMock | None = None,
) -> AsyncMock:
    billing = AsyncMock()
    billing.get_transaction.return_value = transaction
    billing.get_current_subscription.return_value = subscription
    return billing


def _counter_value(counter, **labels) -> float:
    return counter.labels(**labels)._value.get()


class TestScheduleCancelSurveyCheck:
    async def test_writes_pending_zset_entry(self):
        redis_client = AsyncMock()
        payment_id = str(uuid4())
        before = time.time()

        await schedule_cancel_survey_check(
            redis_client=redis_client,
            payment_id=payment_id,
            telegram_id=12345,
            gateway_type="PLATEGA",
        )

        redis_client.zadd.assert_awaited_once()
        call_args = redis_client.zadd.call_args
        key = call_args[0][0]
        members = call_args[0][1]

        assert key == _PENDING_KEY.pack()
        assert key == PendingCancelSurveyChecksKey().pack()
        (member,) = members.keys()
        assert member.startswith(f"{payment_id}:12345:PLATEGA:")
        assert members[member] >= before

    async def test_uses_nx_to_avoid_duplicate_scheduling(self):
        redis_client = AsyncMock()

        await schedule_cancel_survey_check(
            redis_client=redis_client,
            payment_id=str(uuid4()),
            telegram_id=99999,
            gateway_type="TELEGRAM_STARS",
        )

        assert redis_client.zadd.call_args[1].get("nx") is True


class TestProcessDueMemberTerminalStatuses:
    async def test_transaction_not_found_is_dropped(self):
        payment_id = str(uuid4())
        member = f"{payment_id}:12345:PLATEGA:{time.time()}"

        redis_client = AsyncMock()
        billing = _make_billing(transaction=None)
        user_service = AsyncMock()
        notification_service = AsyncMock()

        await _process_due_member(
            member, time.time(), billing, user_service, notification_service, redis_client
        )

        notification_service.notify_user.assert_not_awaited()
        redis_client.zadd.assert_not_awaited()

    async def test_invalid_payment_id_does_not_raise(self):
        member = f"not-a-uuid:12345:PLATEGA:{time.time()}"

        redis_client = AsyncMock()
        billing = AsyncMock()
        user_service = AsyncMock()
        notification_service = AsyncMock()

        await _process_due_member(
            member, time.time(), billing, user_service, notification_service, redis_client
        )

        billing.get_transaction.assert_not_awaited()
        notification_service.notify_user.assert_not_awaited()

    async def test_completed_transaction_is_dropped_without_survey(self):
        payment_id = str(uuid4())
        member = f"{payment_id}:12345:PLATEGA:{time.time()}"

        redis_client = AsyncMock()
        billing = _make_billing(transaction=_make_transaction(TransactionStatus.COMPLETED.value))
        user_service = AsyncMock()
        notification_service = AsyncMock()

        await _process_due_member(
            member, time.time(), billing, user_service, notification_service, redis_client
        )

        notification_service.notify_user.assert_not_awaited()
        redis_client.zadd.assert_not_awaited()

    async def test_refunded_transaction_is_dropped_without_survey(self):
        payment_id = str(uuid4())
        member = f"{payment_id}:12345:PLATEGA:{time.time()}"

        redis_client = AsyncMock()
        billing = _make_billing(transaction=_make_transaction(TransactionStatus.REFUNDED.value))
        user_service = AsyncMock()
        notification_service = AsyncMock()

        await _process_due_member(
            member, time.time(), billing, user_service, notification_service, redis_client
        )

        notification_service.notify_user.assert_not_awaited()


class TestProcessDueMemberPending:
    async def test_young_pending_is_requeued(self):
        payment_id = str(uuid4())
        created_at = time.time()
        member = f"{payment_id}:12345:PLATEGA:{created_at}"

        redis_client = AsyncMock()
        billing = _make_billing(transaction=_make_transaction(TransactionStatus.PENDING.value))
        user_service = AsyncMock()
        notification_service = AsyncMock()

        await _process_due_member(
            member, created_at + 60, billing, user_service, notification_service, redis_client
        )

        redis_client.zadd.assert_awaited_once_with(
            _PENDING_KEY.pack(), {member: created_at}, nx=True
        )
        notification_service.notify_user.assert_not_awaited()

    async def test_stale_pending_past_max_age_is_dropped(self):
        payment_id = str(uuid4())
        created_at = time.time() - _MAX_PENDING_AGE - 1
        member = f"{payment_id}:12345:PLATEGA:{created_at}"

        redis_client = AsyncMock()
        billing = _make_billing(transaction=_make_transaction(TransactionStatus.PENDING.value))
        user_service = AsyncMock()
        notification_service = AsyncMock()

        await _process_due_member(
            member, time.time(), billing, user_service, notification_service, redis_client
        )

        redis_client.zadd.assert_not_awaited()
        notification_service.notify_user.assert_not_awaited()


class TestProcessDueMemberCanceled:
    async def test_sends_survey_when_canceled_and_not_paid_since(self):
        user = make_user(telegram_id=555)
        payment_id = str(uuid4())
        member = f"{payment_id}:555:PLATEGA:{time.time()}"

        redis_client = AsyncMock()
        redis_client.set.return_value = True
        billing = _make_billing(
            transaction=_make_transaction(TransactionStatus.CANCELED.value),
            subscription=None,
        )
        user_service = AsyncMock()
        user_service.get.return_value = user
        notification_service = AsyncMock()

        before = _counter_value(CANCEL_SURVEY_SENT_TOTAL, gateway="PLATEGA")

        await _process_due_member(
            member, time.time(), billing, user_service, notification_service, redis_client
        )

        notification_service.notify_user.assert_awaited_once()
        payload = notification_service.notify_user.await_args.kwargs["payload"]
        assert payload.i18n_key == "ntf-event-cancel-survey-prompt"
        assert payload.reply_markup is not None

        set_args = redis_client.set.call_args
        assert set_args[0][0] == CancelSurveySentKey(payment_id=UUID(payment_id)).pack()
        assert set_args[1]["nx"] is True
        assert set_args[1]["ex"] == _SENT_TTL

        after = _counter_value(CANCEL_SURVEY_SENT_TOTAL, gateway="PLATEGA")
        assert after == before + 1

    async def test_skips_when_user_already_has_active_paid_subscription(self):
        payment_id = str(uuid4())
        member = f"{payment_id}:555:PLATEGA:{time.time()}"

        redis_client = AsyncMock()
        active_paid_sub = MagicMock(Status="ACTIVE", IsTrial=False)
        billing = _make_billing(
            transaction=_make_transaction(TransactionStatus.CANCELED.value),
            subscription=active_paid_sub,
        )
        user_service = AsyncMock()
        notification_service = AsyncMock()

        await _process_due_member(
            member, time.time(), billing, user_service, notification_service, redis_client
        )

        notification_service.notify_user.assert_not_awaited()
        redis_client.set.assert_not_awaited()

    async def test_still_sends_when_active_subscription_is_only_a_trial(self):
        user = make_user(telegram_id=555)
        payment_id = str(uuid4())
        member = f"{payment_id}:555:PLATEGA:{time.time()}"

        redis_client = AsyncMock()
        redis_client.set.return_value = True
        active_trial_sub = MagicMock(Status="ACTIVE", IsTrial=True)
        billing = _make_billing(
            transaction=_make_transaction(TransactionStatus.CANCELED.value),
            subscription=active_trial_sub,
        )
        user_service = AsyncMock()
        user_service.get.return_value = user
        notification_service = AsyncMock()

        await _process_due_member(
            member, time.time(), billing, user_service, notification_service, redis_client
        )

        notification_service.notify_user.assert_awaited_once()

    async def test_already_sent_survey_is_not_resent(self):
        payment_id = str(uuid4())
        member = f"{payment_id}:555:PLATEGA:{time.time()}"

        redis_client = AsyncMock()
        redis_client.set.return_value = None  # NX prevented -- already sent
        billing = _make_billing(
            transaction=_make_transaction(TransactionStatus.CANCELED.value),
            subscription=None,
        )
        user_service = AsyncMock()
        notification_service = AsyncMock()

        await _process_due_member(
            member, time.time(), billing, user_service, notification_service, redis_client
        )

        notification_service.notify_user.assert_not_awaited()

    async def test_skips_when_user_not_found(self):
        payment_id = str(uuid4())
        member = f"{payment_id}:555:PLATEGA:{time.time()}"

        redis_client = AsyncMock()
        redis_client.set.return_value = True
        billing = _make_billing(
            transaction=_make_transaction(TransactionStatus.CANCELED.value),
            subscription=None,
        )
        user_service = AsyncMock()
        user_service.get.return_value = None
        notification_service = AsyncMock()

        await _process_due_member(
            member, time.time(), billing, user_service, notification_service, redis_client
        )

        notification_service.notify_user.assert_not_awaited()


def test_answers_metric_has_reason_and_gateway_labels():
    before = _counter_value(CANCEL_SURVEY_ANSWERS_TOTAL, reason="TOO_EXPENSIVE", gateway="PLATEGA")
    CANCEL_SURVEY_ANSWERS_TOTAL.labels(reason="TOO_EXPENSIVE", gateway="PLATEGA").inc()
    after = _counter_value(CANCEL_SURVEY_ANSWERS_TOTAL, reason="TOO_EXPENSIVE", gateway="PLATEGA")
    assert after == before + 1
