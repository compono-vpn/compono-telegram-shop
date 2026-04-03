"""Tests for PaymentGatewayService — verifies BillingClient calls and DTO mapping."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.core.enums import (
    Currency,
    GatewayChannel,
    PaymentGatewayType,
    PurchaseType,
    TransactionStatus,
)
from src.infrastructure.billing.models import BillingPaymentGateway
from src.models.dto import (
    PaymentGatewayDto,
    PaymentResult,
    PriceDetailsDto,
)
from src.services.payment_gateway import PaymentGatewayService

from tests.conftest import make_plan_snapshot, make_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_billing_gateway(
    gw_id: int = 1,
    gw_type: str = "TELEGRAM_STARS",
    currency: str = "XTR",
    is_active: bool = True,
    channel: str = "ALL",
    order_index: int = 1,
) -> BillingPaymentGateway:
    return BillingPaymentGateway(
        ID=gw_id,
        OrderIndex=order_index,
        Type=gw_type,
        Channel=channel,
        Currency=currency,
        IsActive=is_active,
    )


def _make_service(
    billing: AsyncMock | None = None,
    transaction_service: AsyncMock | None = None,
    subscription_service: AsyncMock | None = None,
    payment_gateway_factory: MagicMock | None = None,
) -> PaymentGatewayService:
    billing = billing or AsyncMock()
    config = MagicMock()
    config.remnawave.sub_public_domain = ""
    bot = MagicMock()
    redis_client = AsyncMock()
    redis_repository = MagicMock()
    translator_hub = MagicMock()
    i18n = MagicMock()
    i18n.get.side_effect = lambda key, **kw: f"[{key}]"
    translator_hub.get_translator_by_locale.return_value = i18n

    return PaymentGatewayService(
        config=config,
        bot=bot,
        redis_client=redis_client,
        redis_repository=redis_repository,
        translator_hub=translator_hub,
        billing=billing,
        transaction_service=transaction_service or AsyncMock(),
        subscription_service=subscription_service or AsyncMock(),
        payment_gateway_factory=payment_gateway_factory or MagicMock(),
        referral_service=AsyncMock(),
        notification_service=AsyncMock(),
        user_service=AsyncMock(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGet:
    @pytest.mark.asyncio
    async def test_returns_dto_when_found(self):
        billing = AsyncMock()
        billing.get_gateway.return_value = _make_billing_gateway(gw_id=5)

        svc = _make_service(billing=billing)
        result = await svc.get(5)

        billing.get_gateway.assert_awaited_once_with(5)
        assert isinstance(result, PaymentGatewayDto)
        assert result.id == 5

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        billing = AsyncMock()
        billing.get_gateway.return_value = None

        svc = _make_service(billing=billing)
        result = await svc.get(999)

        assert result is None


class TestGetByType:
    @pytest.mark.asyncio
    async def test_returns_dto_by_type(self):
        billing = AsyncMock()
        billing.get_gateway_by_type.return_value = _make_billing_gateway(
            gw_type="CRYPTOMUS", currency="USD",
        )

        svc = _make_service(billing=billing)
        result = await svc.get_by_type(PaymentGatewayType.CRYPTOMUS)

        billing.get_gateway_by_type.assert_awaited_once_with("CRYPTOMUS")
        assert result.type == PaymentGatewayType.CRYPTOMUS

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        billing = AsyncMock()
        billing.get_gateway_by_type.return_value = None

        svc = _make_service(billing=billing)
        result = await svc.get_by_type(PaymentGatewayType.YOOKASSA)

        assert result is None

    @pytest.mark.asyncio
    async def test_filters_by_channel(self):
        billing = AsyncMock()
        # Gateway is BOT-only, but we request WEB
        billing.get_gateway_by_type.return_value = _make_billing_gateway(channel="BOT")

        svc = _make_service(billing=billing)
        result = await svc.get_by_type(PaymentGatewayType.TELEGRAM_STARS, channel=GatewayChannel.WEB)

        assert result is None

    @pytest.mark.asyncio
    async def test_channel_all_matches_any_request(self):
        billing = AsyncMock()
        billing.get_gateway_by_type.return_value = _make_billing_gateway(channel="ALL")

        svc = _make_service(billing=billing)
        result = await svc.get_by_type(PaymentGatewayType.TELEGRAM_STARS, channel=GatewayChannel.BOT)

        assert result is not None


class TestGetAll:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        billing = AsyncMock()
        billing.list_gateways.return_value = [
            _make_billing_gateway(gw_id=1),
            _make_billing_gateway(gw_id=2),
        ]

        svc = _make_service(billing=billing)
        result = await svc.get_all()

        billing.list_gateways.assert_awaited_once()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_sorted_by_order_index(self):
        billing = AsyncMock()
        billing.list_gateways.return_value = [
            _make_billing_gateway(gw_id=1, order_index=3),
            _make_billing_gateway(gw_id=2, order_index=1),
            _make_billing_gateway(gw_id=3, order_index=2),
        ]

        svc = _make_service(billing=billing)
        result = await svc.get_all(sorted=True)

        assert [r.id for r in result] == [2, 3, 1]


class TestFilterActive:
    @pytest.mark.asyncio
    async def test_active_true_calls_list_active(self):
        billing = AsyncMock()
        billing.list_active_gateways.return_value = [
            _make_billing_gateway(is_active=True),
        ]

        svc = _make_service(billing=billing)
        result = await svc.filter_active(is_active=True)

        billing.list_active_gateways.assert_awaited_once()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_active_false_filters_inactive(self):
        billing = AsyncMock()
        billing.list_gateways.return_value = [
            _make_billing_gateway(gw_id=1, is_active=True),
            _make_billing_gateway(gw_id=2, is_active=False),
        ]

        svc = _make_service(billing=billing)
        result = await svc.filter_active(is_active=False)

        billing.list_gateways.assert_awaited_once()
        assert len(result) == 1
        assert result[0].id == 2

    @pytest.mark.asyncio
    async def test_filters_by_channel(self):
        billing = AsyncMock()
        billing.list_active_gateways.return_value = [
            _make_billing_gateway(gw_id=1, channel="BOT"),
            _make_billing_gateway(gw_id=2, channel="WEB"),
            _make_billing_gateway(gw_id=3, channel="ALL"),
        ]

        svc = _make_service(billing=billing)
        result = await svc.filter_active(is_active=True, channel=GatewayChannel.BOT)

        # Should include BOT (id=1) and ALL (id=3), exclude WEB (id=2)
        assert len(result) == 2
        result_ids = {r.id for r in result}
        assert result_ids == {1, 3}

    @pytest.mark.asyncio
    async def test_returns_empty_when_none_match(self):
        billing = AsyncMock()
        billing.list_active_gateways.return_value = []

        svc = _make_service(billing=billing)
        result = await svc.filter_active(is_active=True)

        assert result == []


class TestCreatePayment:
    @pytest.mark.asyncio
    async def test_happy_path_paid(self):
        billing = AsyncMock()
        transaction_service = AsyncMock()
        payment_gateway_factory = MagicMock()

        # Set up the gateway returned by get_by_type
        gw = _make_billing_gateway(gw_type="TELEGRAM_STARS", currency="XTR")
        billing.get_gateway_by_type.return_value = gw

        # The factory returns a gateway instance
        payment_id = uuid4()
        gateway_instance = AsyncMock()
        gateway_instance.data = PaymentGatewayDto(
            id=1,
            order_index=1,
            type=PaymentGatewayType.TELEGRAM_STARS,
            currency=Currency.XTR,
            is_active=True,
        )
        gateway_instance.handle_create_payment.return_value = PaymentResult(
            id=payment_id, url="https://pay.example.com/inv123",
        )
        payment_gateway_factory.return_value = gateway_instance

        svc = _make_service(
            billing=billing,
            transaction_service=transaction_service,
            payment_gateway_factory=payment_gateway_factory,
        )

        user = make_user(telegram_id=100)
        plan = make_plan_snapshot()
        pricing = PriceDetailsDto(original_amount=Decimal("100"), final_amount=Decimal("100"))

        result = await svc.create_payment(
            user=user,
            plan=plan,
            pricing=pricing,
            purchase_type=PurchaseType.NEW,
            gateway_type=PaymentGatewayType.TELEGRAM_STARS,
        )

        assert isinstance(result, PaymentResult)
        assert result.id == payment_id
        assert result.url == "https://pay.example.com/inv123"
        transaction_service.create.assert_awaited_once()
        gateway_instance.handle_create_payment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_free_payment_skips_gateway(self):
        billing = AsyncMock()
        transaction_service = AsyncMock()
        payment_gateway_factory = MagicMock()

        gw = _make_billing_gateway(gw_type="TELEGRAM_STARS", currency="XTR")
        billing.get_gateway_by_type.return_value = gw

        gateway_instance = AsyncMock()
        gateway_instance.data = PaymentGatewayDto(
            id=1,
            order_index=1,
            type=PaymentGatewayType.TELEGRAM_STARS,
            currency=Currency.XTR,
            is_active=True,
        )
        payment_gateway_factory.return_value = gateway_instance

        svc = _make_service(
            billing=billing,
            transaction_service=transaction_service,
            payment_gateway_factory=payment_gateway_factory,
        )

        user = make_user(telegram_id=100)
        plan = make_plan_snapshot()
        pricing = PriceDetailsDto(
            original_amount=Decimal("100"),
            discount_percent=100,
            final_amount=Decimal("0"),
        )

        result = await svc.create_payment(
            user=user,
            plan=plan,
            pricing=pricing,
            purchase_type=PurchaseType.NEW,
            gateway_type=PaymentGatewayType.TELEGRAM_STARS,
        )

        assert isinstance(result, PaymentResult)
        assert result.url is None
        # Transaction is still created for free payments
        transaction_service.create.assert_awaited_once()
        # But the gateway payment handler is NOT called
        gateway_instance.handle_create_payment.assert_not_awaited()


class TestListActiveByType:
    @pytest.mark.asyncio
    async def test_filters_by_gateway_type(self):
        billing = AsyncMock()
        billing.list_active_gateways.return_value = [
            _make_billing_gateway(gw_id=1, gw_type="TELEGRAM_STARS"),
            _make_billing_gateway(gw_id=2, gw_type="CRYPTOMUS"),
            _make_billing_gateway(gw_id=3, gw_type="TELEGRAM_STARS"),
        ]

        svc = _make_service(billing=billing)
        result = await svc.list_active_by_type(PaymentGatewayType.TELEGRAM_STARS)

        assert len(result) == 2
        assert all(r.type == PaymentGatewayType.TELEGRAM_STARS for r in result)
