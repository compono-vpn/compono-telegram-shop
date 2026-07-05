"""Tests for subscription checkout instrumentation and experiment-aware pricing context."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import CallbackQuery

from src.bot.routers.subscription.getters import duration_getter, payment_method_getter
from src.bot.routers.subscription.handlers import on_payment_method_select
from src.bot.states import Subscription
from src.core.constants import USER_KEY
from src.core.enums import PaymentGatewayType, PurchaseType
from src.models.dto import PlanDto
from src.models.dto.plan import PlanDurationDto
from src.services.experiment import ExperimentFeature
from tests.conftest import make_dialog_manager, make_i18n, make_user, unwrap_inject


class _ExperimentService:
    def __init__(
        self,
        *,
        start_tier_price: Decimal | None = None,
        intro_price: Decimal | None = None,
    ) -> None:
        self.start_tier_price = start_tier_price
        self.intro_price = intro_price
        self.events: list[tuple[str, int]] = []
        self.exposures: list[tuple[str, int]] = []

    def evaluate_feature_for_user(self, user, experiment_key: str | ExperimentFeature):
        key = (
            experiment_key.value
            if isinstance(experiment_key, ExperimentFeature)
            else experiment_key
        )
        payload = None
        variant = f"{key}_v1_on"
        if key == ExperimentFeature.START_TIER_PRICE.value and self.start_tier_price is not None:
            payload = {"final_amount": str(self.start_tier_price)}
            variant = "price_99"
        if key == ExperimentFeature.INTRO_PRICE.value and self.intro_price is not None:
            payload = {"final_amount": str(self.intro_price)}
            variant = "intro_99"
        return SimpleNamespace(feature_key=key, variant=variant, payload=payload)

    async def expose(self, experiment_key: str, telegram_id: int, created_at=None) -> str:
        self.exposures.append((experiment_key, telegram_id))
        return f"{experiment_key}_v1_on"

    def record_conversion(
        self,
        experiment_key: str,
        telegram_id: int,
        event: str,
        created_at=None,
    ) -> None:
        self.events.append((event, telegram_id))


class _Billing:
    def __init__(self, gateway_currency: str = "USD") -> None:
        self.calls: list[dict[str, Any]] = []
        self.gateway_currency = gateway_currency
        self.gateways = [
            SimpleNamespace(
                ID=1,
                OrderIndex=0,
                Type=PaymentGatewayType.TELEGRAM_STARS.value,
                Channel="BOT",
                Currency=gateway_currency,
                IsActive=True,
            ),
            SimpleNamespace(
                ID=2,
                OrderIndex=1,
                Type=PaymentGatewayType.YOOKASSA.value,
                Channel="BOT",
                Currency="RUB",
                IsActive=True,
            ),
        ]

    async def calculate_price(
        self,
        telegram_id: int,
        plan_id: int,
        duration_days: int,
        currency: str,
        experiment: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        final_amount = Decimal("10")
        if experiment:
            payload = experiment.get("payload") or {}
            if "final_amount" in payload:
                final_amount = Decimal(payload["final_amount"])

        return SimpleNamespace(
            original_amount=Decimal(final_amount) + Decimal("1"),
            discount_percent=0,
            final_amount=Decimal(final_amount),
        )

    async def create_payment(
        self,
        telegram_id: int,
        plan_id: int,
        duration_days: int,
        currency: str,
        gateway_type: str,
        purchase_type: str,
        is_test: bool = False,
        promocode_id: int | None = None,
        gateway_metadata: dict[str, str] | None = None,
        experiment: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        self.calls.append(
            {
                "telegram_id": telegram_id,
                "plan_id": plan_id,
                "duration_days": duration_days,
                "currency": currency,
                "gateway_type": gateway_type,
                "purchase_type": purchase_type,
                "is_test": is_test,
                "promocode_id": promocode_id,
                "gateway_metadata": gateway_metadata,
                "experiment": experiment,
            }
        )
        return SimpleNamespace(ID="pay-1", URL="https://checkout.com/s/1")

    async def get_default_currency(self) -> str:
        return self.gateway_currency

    async def list_active_gateways(self):
        return self.gateways

    async def get_gateway_by_type(self, gateway_type: str) -> SimpleNamespace:
        return SimpleNamespace(Currency=self.gateway_currency)


def _plan_with_durations(plan_id: int, days: list[int]) -> PlanDto:
    return PlanDto(
        id=plan_id,
        name="Pro",
        durations=[PlanDurationDto(id=i, days=d) for i, d in enumerate(days, start=1)],
    )


@pytest.mark.asyncio
async def test_duration_getter_uses_experiment_pricing_context():
    plan = _plan_with_durations(plan_id=42, days=[30, 60])
    dm = make_dialog_manager()
    dm.dialog_data["plandto"] = plan.model_dump()

    billing = _Billing()
    exp_service = _ExperimentService(start_tier_price=Decimal("19.00"))

    raw = unwrap_inject(duration_getter)
    result = await raw(dm, make_user(telegram_id=777), make_i18n(), billing, exp_service)

    by_days = {item["days"]: item["final_amount"] for item in result["durations"]}
    assert by_days == {30: Decimal("19.00"), 60: Decimal("19.00")}


@pytest.mark.asyncio
async def test_payment_method_getter_passes_context_to_pricing():
    plan = _plan_with_durations(plan_id=42, days=[30])
    dm = make_dialog_manager()
    dm.dialog_data["plandto"] = plan.model_dump()
    dm.dialog_data["selected_duration"] = 30

    billing = _Billing()
    exp_service = _ExperimentService(intro_price=Decimal("12.00"))

    raw = unwrap_inject(payment_method_getter)
    result = await raw(dm, make_user(telegram_id=777), billing, make_i18n(), exp_service)

    prices = {item["gateway_type"]: item["price"] for item in result["payment_methods"]}
    assert prices[PaymentGatewayType.YOOKASSA] == Decimal("12.00")
    assert prices[PaymentGatewayType.TELEGRAM_STARS] == Decimal("12.00")


@pytest.mark.asyncio
async def test_duration_and_price_getters_fallback_without_experiments():
    plan = _plan_with_durations(plan_id=42, days=[30])
    dm = make_dialog_manager()
    dm.dialog_data["plandto"] = plan.model_dump()

    billing = _Billing()
    raw = unwrap_inject(duration_getter)

    result = await raw(dm, make_user(telegram_id=777), make_i18n(), billing, None)

    assert result["durations"][0]["final_amount"] == Decimal("10")


@pytest.mark.asyncio
async def test_on_payment_method_select_passes_experiment_context_to_create_payment():
    plan = _plan_with_durations(plan_id=42, days=[30])
    dm = make_dialog_manager()
    dm.middleware_data[USER_KEY] = make_user(telegram_id=777)
    dm.dialog_data["plandto"] = plan.model_dump()
    dm.dialog_data["selected_duration"] = 30
    dm.dialog_data["purchase_type"] = PurchaseType.NEW
    dm.switch_to = AsyncMock()

    billing = _Billing()
    notification_service = AsyncMock()
    exp_service = _ExperimentService(start_tier_price=Decimal("99.00"))
    raw = unwrap_inject(on_payment_method_select)
    redis_client = AsyncMock()

    await raw(
        MagicMock(spec=CallbackQuery),
        MagicMock(),
        dm,
        PaymentGatewayType.TELEGRAM_STARS,
        billing,
        exp_service,
        notification_service,
        redis_client,
    )

    payment_call = billing.calls[0]
    assert payment_call["experiment"]["feature_key"] == "start_tier_price"
    assert payment_call["experiment"]["variant_key"] == "price_99"
    assert payment_call["experiment"]["payload"] == {"final_amount": "99.00"}
    assert payment_call["experiment"]["price_override"] == {"price": "99"}
    assert (ExperimentFeature.CHECKOUT_FLOW.value, 777) in exp_service.exposures
    assert (ExperimentFeature.START_TIER_PRICE.value, 777) in exp_service.exposures
    assert ("checkout_started", 777) in exp_service.events
    assert ("payment_link_created", 777) in exp_service.events

    dm.switch_to.assert_awaited_once_with(state=Subscription.CONFIRM)
