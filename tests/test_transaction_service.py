"""Tests for TransactionService — verifies BillingClient calls and DTO mapping."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.core.enums import (
    Currency,
    PaymentGatewayType,
    PurchaseType,
    TransactionStatus,
)
from src.infrastructure.billing.models import (
    BillingPlanSnapshot,
    BillingPriceDetails,
    BillingTransaction,
    BillingUser,
)
from src.models.dto import PlanSnapshotDto, PriceDetailsDto, TransactionDto
from src.services.transaction import TransactionService

from tests.conftest import make_plan_snapshot, make_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_billing_transaction(
    payment_id: str | None = None,
    status: str = "PENDING",
    telegram_id: int = 100,
) -> BillingTransaction:
    return BillingTransaction(
        ID=1,
        PaymentID=payment_id or str(uuid4()),
        UserTelegramID=telegram_id,
        Status=status,
        IsTest=False,
        PurchaseType="NEW",
        GatewayType="TELEGRAM_STARS",
        Pricing=BillingPriceDetails(original_amount="100", discount_percent=0, final_amount="100"),
        Currency="XTR",
        Plan=BillingPlanSnapshot(
            id=2, name="Pro", type="BOTH", traffic_limit=300, device_limit=6,
            duration=30, traffic_limit_strategy="MONTH",
        ),
        CreatedAt=datetime.now(tz=timezone.utc),
        UpdatedAt=datetime.now(tz=timezone.utc),
    )


def _make_service(billing: AsyncMock | None = None) -> TransactionService:
    billing = billing or AsyncMock()
    config = MagicMock()
    redis_client = AsyncMock()
    redis_repository = MagicMock()
    return TransactionService(
        config=config,
        redis_client=redis_client,
        redis_repository=redis_repository,
        billing=billing,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreate:
    @pytest.mark.asyncio
    async def test_calls_billing_and_returns_dto(self):
        billing = AsyncMock()
        billing_tx = _make_billing_transaction()
        billing.create_transaction.return_value = billing_tx

        svc = _make_service(billing)
        user = make_user(telegram_id=100)
        plan = make_plan_snapshot()
        tx_input = TransactionDto(
            payment_id=uuid4(),
            status=TransactionStatus.PENDING,
            purchase_type=PurchaseType.NEW,
            gateway_type=PaymentGatewayType.TELEGRAM_STARS,
            pricing=PriceDetailsDto(original_amount=Decimal("100"), final_amount=Decimal("100")),
            currency=Currency.XTR,
            plan=plan,
        )

        result = await svc.create(user, tx_input)

        billing.create_transaction.assert_awaited_once()
        call_args = billing.create_transaction.call_args
        assert call_args[0][0] == 100  # telegram_id
        assert isinstance(result, TransactionDto)
        assert result.user == user


class TestGet:
    @pytest.mark.asyncio
    async def test_returns_dto_when_found(self):
        billing = AsyncMock()
        payment_id = uuid4()
        billing_tx = _make_billing_transaction(payment_id=str(payment_id))
        billing_tx.UserTelegramID = 0  # no user to attach
        billing.get_transaction.return_value = billing_tx
        billing.get_user.return_value = None

        svc = _make_service(billing)
        result = await svc.get(payment_id)

        billing.get_transaction.assert_awaited_once_with(payment_id)
        assert isinstance(result, TransactionDto)

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        billing = AsyncMock()
        billing.get_transaction.return_value = None

        svc = _make_service(billing)
        result = await svc.get(uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_attaches_user_when_telegram_id_present(self):
        billing = AsyncMock()
        payment_id = uuid4()
        billing_tx = _make_billing_transaction(payment_id=str(payment_id), telegram_id=555)
        billing.get_transaction.return_value = billing_tx
        billing.get_user.return_value = BillingUser(
            ID=1, TelegramID=555, Name="Test", Role="USER", Language="ru", ReferralCode="abc",
        )

        svc = _make_service(billing)
        result = await svc.get(payment_id)

        billing.get_user.assert_awaited_once_with(555)
        assert result.user is not None
        assert result.user.telegram_id == 555


class TestGetByUser:
    @pytest.mark.asyncio
    async def test_calls_list_transactions(self):
        billing = AsyncMock()
        billing.list_transactions.return_value = [
            _make_billing_transaction(telegram_id=42),
            _make_billing_transaction(telegram_id=42),
        ]

        svc = _make_service(billing)
        result = await svc.get_by_user(42)

        billing.list_transactions.assert_awaited_once_with(42)
        assert len(result) == 2
        assert all(isinstance(r, TransactionDto) for r in result)

    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        billing = AsyncMock()
        billing.list_transactions.return_value = []

        svc = _make_service(billing)
        result = await svc.get_by_user(42)

        assert result == []


class TestGetAll:
    @pytest.mark.asyncio
    async def test_calls_list_all_transactions(self):
        billing = AsyncMock()
        billing.list_all_transactions.return_value = [_make_billing_transaction()]

        svc = _make_service(billing)
        result = await svc.get_all()

        billing.list_all_transactions.assert_awaited_once()
        assert len(result) == 1


class TestGetByStatus:
    @pytest.mark.asyncio
    async def test_calls_list_by_status(self):
        billing = AsyncMock()
        billing.list_transactions_by_status.return_value = [
            _make_billing_transaction(status="PENDING"),
        ]

        svc = _make_service(billing)
        result = await svc.get_by_status(TransactionStatus.PENDING)

        billing.list_transactions_by_status.assert_awaited_once_with("PENDING")
        assert len(result) == 1
        assert result[0].status == TransactionStatus.PENDING


class TestTransitionStatus:
    @pytest.mark.asyncio
    async def test_successful_transition(self):
        billing = AsyncMock()
        payment_id = uuid4()
        billing_tx = _make_billing_transaction(payment_id=str(payment_id), status="COMPLETED")
        billing_tx.UserTelegramID = 0
        billing.transition_transaction_status.return_value = billing_tx
        billing.get_user.return_value = None

        svc = _make_service(billing)
        result = await svc.transition_status(
            payment_id, TransactionStatus.PENDING, TransactionStatus.COMPLETED,
        )

        billing.transition_transaction_status.assert_awaited_once_with(
            payment_id, "PENDING", "COMPLETED",
        )
        assert isinstance(result, TransactionDto)

    @pytest.mark.asyncio
    async def test_returns_none_when_transition_fails(self):
        billing = AsyncMock()
        billing.transition_transaction_status.return_value = None

        svc = _make_service(billing)
        result = await svc.transition_status(
            uuid4(), TransactionStatus.PENDING, TransactionStatus.COMPLETED,
        )

        assert result is None


class TestCount:
    @pytest.mark.asyncio
    async def test_count_returns_total(self):
        billing = AsyncMock()
        billing.count_transactions.return_value = {"total": 42, "by_status": {}}

        svc = _make_service(billing)
        result = await svc.count()

        billing.count_transactions.assert_awaited_once()
        assert result == 42

    @pytest.mark.asyncio
    async def test_count_returns_zero_when_missing(self):
        billing = AsyncMock()
        billing.count_transactions.return_value = {}

        svc = _make_service(billing)
        result = await svc.count()

        assert result == 0


class TestCountByStatus:
    @pytest.mark.asyncio
    async def test_returns_count_for_status(self):
        billing = AsyncMock()
        billing.count_transactions.return_value = {
            "total": 10,
            "by_status": {"PENDING": 3, "COMPLETED": 7},
        }

        svc = _make_service(billing)
        result = await svc.count_by_status(TransactionStatus.PENDING)

        assert result == 3

    @pytest.mark.asyncio
    async def test_returns_zero_when_status_not_present(self):
        billing = AsyncMock()
        billing.count_transactions.return_value = {
            "total": 10,
            "by_status": {"COMPLETED": 10},
        }

        svc = _make_service(billing)
        result = await svc.count_by_status(TransactionStatus.PENDING)

        assert result == 0


class TestUpdate:
    @pytest.mark.asyncio
    async def test_update_with_status_change_transitions(self):
        billing = AsyncMock()
        payment_id = uuid4()

        # Current transaction in billing
        current_tx = _make_billing_transaction(payment_id=str(payment_id), status="PENDING")
        billing.get_transaction.return_value = current_tx

        # After transition
        transitioned_tx = _make_billing_transaction(payment_id=str(payment_id), status="COMPLETED")
        transitioned_tx.UserTelegramID = 0
        billing.transition_transaction_status.return_value = transitioned_tx
        billing.get_user.return_value = None

        svc = _make_service(billing)

        tx_dto = TransactionDto(
            payment_id=payment_id,
            status=TransactionStatus.PENDING,
            purchase_type=PurchaseType.NEW,
            gateway_type=PaymentGatewayType.TELEGRAM_STARS,
            pricing=PriceDetailsDto(),
            currency=Currency.XTR,
            plan=make_plan_snapshot(),
        )
        # Trigger changed_data tracking by setting status
        tx_dto.status = TransactionStatus.COMPLETED

        result = await svc.update(tx_dto)

        billing.get_transaction.assert_awaited_once_with(payment_id)
        billing.transition_transaction_status.assert_awaited_once_with(
            payment_id, "PENDING", "COMPLETED",
        )
        assert isinstance(result, TransactionDto)

    @pytest.mark.asyncio
    async def test_update_without_status_change_refetches(self):
        billing = AsyncMock()
        payment_id = uuid4()

        billing_tx = _make_billing_transaction(payment_id=str(payment_id))
        billing_tx.UserTelegramID = 0
        billing.get_transaction.return_value = billing_tx
        billing.get_user.return_value = None

        svc = _make_service(billing)

        tx_dto = TransactionDto(
            payment_id=payment_id,
            status=TransactionStatus.PENDING,
            purchase_type=PurchaseType.NEW,
            gateway_type=PaymentGatewayType.TELEGRAM_STARS,
            pricing=PriceDetailsDto(),
            currency=Currency.XTR,
            plan=make_plan_snapshot(),
        )
        # No status change in changed_data

        result = await svc.update(tx_dto)

        billing.get_transaction.assert_awaited_once_with(payment_id)
        billing.transition_transaction_status.assert_not_awaited()
        assert isinstance(result, TransactionDto)
