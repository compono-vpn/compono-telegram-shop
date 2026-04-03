"""Tests for BroadcastService — verifies BillingClient calls."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from tests.conftest import make_config

from src.core.enums import (
    BroadcastAudience,
    BroadcastMessageStatus,
    BroadcastStatus,
)
from src.core.utils.message_payload import MessagePayload
from src.infrastructure.billing.models import (
    BillingBroadcast,
    BillingBroadcastMessage,
)
from src.models.dto.broadcast import BroadcastDto, BroadcastMessageDto
from src.services.broadcast import BroadcastService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TASK_ID = uuid4()


def _make_billing_broadcast(**overrides) -> BillingBroadcast:
    defaults = dict(
        ID=1,
        TaskID=str(TASK_ID),
        Status="PROCESSING",
        Audience="ALL",
        TotalCount=10,
        SuccessCount=0,
        FailedCount=0,
        Payload={"i18n_key": "test-broadcast", "is_deleted": False},
    )
    defaults.update(overrides)
    return BillingBroadcast(**defaults)


def _make_billing_broadcast_message(**overrides) -> BillingBroadcastMessage:
    defaults = dict(
        ID=1,
        BroadcastID=1,
        UserID=100,
        Status="PENDING",
    )
    defaults.update(overrides)
    return BillingBroadcastMessage(**defaults)


def _make_broadcast_dto(**overrides) -> BroadcastDto:
    defaults = dict(
        id=1,
        task_id=TASK_ID,
        status=BroadcastStatus.PROCESSING,
        audience=BroadcastAudience.ALL,
        total_count=10,
        success_count=0,
        failed_count=0,
        payload=MessagePayload(i18n_key="test-broadcast"),
    )
    defaults.update(overrides)
    return BroadcastDto(**defaults)


def _make_service(billing: AsyncMock | None = None) -> tuple[BroadcastService, AsyncMock]:
    """Return (service, billing_mock)."""
    billing = billing or AsyncMock()
    config = make_config()
    redis_client = AsyncMock()
    redis_repository = AsyncMock()

    svc = BroadcastService(
        config=config,
        redis_client=redis_client,
        redis_repository=redis_repository,
        billing=billing,
    )
    return svc, billing


# ---------------------------------------------------------------------------
# create()
# ---------------------------------------------------------------------------


class TestCreate:
    async def test_calls_billing_create_broadcast(self):
        billing = AsyncMock()
        billing.create_broadcast.return_value = _make_billing_broadcast()
        svc, _ = _make_service(billing)

        broadcast = _make_broadcast_dto()
        result = await svc.create(broadcast)

        billing.create_broadcast.assert_awaited_once()
        call_data = billing.create_broadcast.call_args[0][0]
        assert call_data["task_id"] == str(TASK_ID)
        assert call_data["status"] == "PROCESSING"
        assert call_data["audience"] == "ALL"
        assert call_data["total_count"] == 10
        assert result.task_id == TASK_ID


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------


class TestGet:
    async def test_returns_broadcast_when_found(self):
        billing = AsyncMock()
        billing.list_broadcasts.return_value = [
            _make_billing_broadcast(TaskID=str(TASK_ID)),
        ]
        svc, _ = _make_service(billing)

        result = await svc.get(TASK_ID)

        billing.list_broadcasts.assert_awaited_once()
        assert result is not None
        assert result.task_id == TASK_ID

    async def test_returns_none_when_not_found(self):
        billing = AsyncMock()
        billing.list_broadcasts.return_value = []
        svc, _ = _make_service(billing)

        result = await svc.get(uuid4())

        assert result is None

    async def test_filters_by_task_id(self):
        other_id = uuid4()
        billing = AsyncMock()
        billing.list_broadcasts.return_value = [
            _make_billing_broadcast(TaskID=str(other_id)),
            _make_billing_broadcast(TaskID=str(TASK_ID)),
        ]
        svc, _ = _make_service(billing)

        result = await svc.get(TASK_ID)

        assert result is not None
        assert result.task_id == TASK_ID


# ---------------------------------------------------------------------------
# get_all()
# ---------------------------------------------------------------------------


class TestGetAll:
    async def test_returns_reversed_list(self):
        billing = AsyncMock()
        id1, id2 = uuid4(), uuid4()
        billing.list_broadcasts.return_value = [
            _make_billing_broadcast(ID=1, TaskID=str(id1)),
            _make_billing_broadcast(ID=2, TaskID=str(id2)),
        ]
        svc, _ = _make_service(billing)

        result = await svc.get_all()

        billing.list_broadcasts.assert_awaited_once()
        assert len(result) == 2
        # Reversed order
        assert result[0].task_id == id2
        assert result[1].task_id == id1


# ---------------------------------------------------------------------------
# update()
# ---------------------------------------------------------------------------


class TestUpdate:
    async def test_calls_billing_update_broadcast(self):
        billing = AsyncMock()
        billing.update_broadcast.return_value = _make_billing_broadcast(
            Status="COMPLETED", SuccessCount=10
        )
        svc, _ = _make_service(billing)

        broadcast = _make_broadcast_dto()
        broadcast.status = BroadcastStatus.COMPLETED
        broadcast.success_count = 10

        result = await svc.update(broadcast)

        billing.update_broadcast.assert_awaited_once()
        args = billing.update_broadcast.call_args
        assert args[0][0] == 1  # broadcast.id
        assert result is not None

    async def test_returns_none_when_no_id(self):
        svc, billing = _make_service()

        broadcast = _make_broadcast_dto(id=None)
        result = await svc.update(broadcast)

        billing.update_broadcast.assert_not_awaited()
        assert result is None

    async def test_returns_none_when_billing_returns_none(self):
        billing = AsyncMock()
        billing.update_broadcast.return_value = None
        svc, _ = _make_service(billing)

        broadcast = _make_broadcast_dto()
        broadcast.status = BroadcastStatus.ERROR

        result = await svc.update(broadcast)

        assert result is None

    async def test_converts_enum_values_to_strings(self):
        billing = AsyncMock()
        billing.update_broadcast.return_value = _make_billing_broadcast()
        svc, _ = _make_service(billing)

        broadcast = _make_broadcast_dto()
        broadcast.status = BroadcastStatus.COMPLETED
        broadcast.audience = BroadcastAudience.SUBSCRIBED

        await svc.update(broadcast)

        call_data = billing.update_broadcast.call_args[0][1]
        # Enum values should be converted to strings
        if "status" in call_data:
            assert isinstance(call_data["status"], str)
        if "audience" in call_data:
            assert isinstance(call_data["audience"], str)


# ---------------------------------------------------------------------------
# delete_broadcast()
# ---------------------------------------------------------------------------


class TestDelete:
    async def test_calls_billing_delete(self):
        billing = AsyncMock()
        billing.delete_broadcast.return_value = None
        svc, _ = _make_service(billing)

        await svc.delete_broadcast(42)

        billing.delete_broadcast.assert_awaited_once_with(42)


# ---------------------------------------------------------------------------
# create_messages()
# ---------------------------------------------------------------------------


class TestCreateMessages:
    async def test_calls_billing_create_broadcast_messages(self):
        billing = AsyncMock()
        billing.create_broadcast_messages.return_value = [
            _make_billing_broadcast_message(ID=1, UserID=100),
            _make_billing_broadcast_message(ID=2, UserID=200),
        ]
        svc, _ = _make_service(billing)

        messages = [
            BroadcastMessageDto(user_id=100, status=BroadcastMessageStatus.PENDING),
            BroadcastMessageDto(user_id=200, status=BroadcastMessageStatus.PENDING),
        ]

        result = await svc.create_messages(broadcast_id=1, messages=messages)

        billing.create_broadcast_messages.assert_awaited_once()
        args = billing.create_broadcast_messages.call_args
        assert args[0][0] == 1  # broadcast_id
        messages_data = args[0][1]
        assert len(messages_data) == 2
        assert messages_data[0]["user_id"] == 100
        assert messages_data[0]["status"] == "PENDING"
        assert len(result) == 2


# ---------------------------------------------------------------------------
# update_message()
# ---------------------------------------------------------------------------


class TestUpdateMessage:
    async def test_calls_billing_update_broadcast_messages(self):
        billing = AsyncMock()
        billing.update_broadcast_messages.return_value = None
        svc, _ = _make_service(billing)

        msg = BroadcastMessageDto(user_id=100, status=BroadcastMessageStatus.PENDING)
        msg.status = BroadcastMessageStatus.SENT

        await svc.update_message(broadcast_id=1, message=msg)

        billing.update_broadcast_messages.assert_awaited_once()
        call_data = billing.update_broadcast_messages.call_args[0][0]
        assert len(call_data) == 1
        assert call_data[0]["user_id"] == 100
        assert call_data[0]["broadcast_id"] == 1


# ---------------------------------------------------------------------------
# get_audience_count() / get_audience_users()
# ---------------------------------------------------------------------------


class TestAudience:
    async def test_get_audience_count(self):
        billing = AsyncMock()
        billing.get_broadcast_audience_count.return_value = 42
        svc, _ = _make_service(billing)

        count = await svc.get_audience_count(BroadcastAudience.ALL)

        billing.get_broadcast_audience_count.assert_awaited_once_with("ALL", plan_id=None)
        assert count == 42

    async def test_get_audience_count_with_plan(self):
        billing = AsyncMock()
        billing.get_broadcast_audience_count.return_value = 10
        svc, _ = _make_service(billing)

        count = await svc.get_audience_count(BroadcastAudience.PLAN, plan_id=5)

        billing.get_broadcast_audience_count.assert_awaited_once_with("PLAN", plan_id=5)
        assert count == 10

    async def test_get_audience_users(self):
        from src.infrastructure.billing.models import BillingUser

        billing = AsyncMock()
        billing.get_broadcast_audience.return_value = [
            BillingUser(TelegramID=100, Name="A", Role="USER", Language="en"),
            BillingUser(TelegramID=200, Name="B", Role="USER", Language="en"),
        ]
        svc, _ = _make_service(billing)

        users = await svc.get_audience_users(BroadcastAudience.SUBSCRIBED)

        billing.get_broadcast_audience.assert_awaited_once_with("SUBSCRIBED", plan_id=None)
        assert len(users) == 2
        assert users[0].telegram_id == 100


# ---------------------------------------------------------------------------
# get_status()
# ---------------------------------------------------------------------------


class TestGetStatus:
    async def test_returns_status(self):
        billing = AsyncMock()
        billing.list_broadcasts.return_value = [
            _make_billing_broadcast(TaskID=str(TASK_ID), Status="COMPLETED"),
        ]
        svc, _ = _make_service(billing)

        status = await svc.get_status(TASK_ID)

        assert status == BroadcastStatus.COMPLETED

    async def test_returns_none_when_not_found(self):
        billing = AsyncMock()
        billing.list_broadcasts.return_value = []
        svc, _ = _make_service(billing)

        status = await svc.get_status(uuid4())

        assert status is None
