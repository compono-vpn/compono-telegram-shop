"""Tests for PlanService -- verifies correct BillingClient delegation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.billing.models import BillingPlan, BillingPlanDuration, BillingPlanPrice
from src.models.dto.plan import PlanDto
from src.services.plan import PlanService

from tests.conftest import make_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_billing_plan(**overrides) -> BillingPlan:
    defaults = {
        "ID": 1,
        "OrderIndex": 0,
        "IsActive": True,
        "Type": "BOTH",
        "Availability": "ALL",
        "Name": "Test Plan",
        "Description": "A test plan",
        "Tag": None,
        "TrafficLimit": 100,
        "DeviceLimit": 3,
        "TrafficLimitStrategy": "NO_RESET",
        "AllowedUserIDs": [],
        "InternalSquads": [],
        "ExternalSquad": None,
        "Durations": [
            BillingPlanDuration(
                ID=1,
                PlanID=1,
                Days=30,
                Prices=[BillingPlanPrice(ID=1, DurationID=1, Currency="XTR", Price="100")],
            ),
        ],
    }
    defaults.update(overrides)
    return BillingPlan(**defaults)


def _make_service(
    billing: AsyncMock | None = None,
    redis_client: AsyncMock | None = None,
) -> PlanService:
    config = MagicMock()
    redis_client = redis_client or AsyncMock()
    redis_repository = MagicMock()
    billing = billing or AsyncMock()
    return PlanService(
        config=config,
        redis_client=redis_client,
        redis_repository=redis_repository,
        billing=billing,
    )


# ---------------------------------------------------------------------------
# Tests: get()
# ---------------------------------------------------------------------------


class TestPlanGet:
    async def test_get_returns_plan_dto(self):
        billing = AsyncMock()
        billing.get_plan.return_value = _make_billing_plan(ID=42, Name="Pro")

        svc = _make_service(billing=billing)
        result = await svc.get(42)

        billing.get_plan.assert_awaited_once_with(42)
        assert isinstance(result, PlanDto)
        assert result.name == "Pro"

    async def test_get_returns_none_when_not_found(self):
        billing = AsyncMock()
        billing.get_plan.return_value = None

        svc = _make_service(billing=billing)
        result = await svc.get(999)

        assert result is None


# ---------------------------------------------------------------------------
# Tests: get_all()
# ---------------------------------------------------------------------------


class TestPlanGetAll:
    async def test_get_all_returns_list_of_dtos(self):
        billing = AsyncMock()
        billing.list_plans.return_value = [
            _make_billing_plan(ID=1, Name="Basic"),
            _make_billing_plan(ID=2, Name="Pro"),
        ]

        svc = _make_service(billing=billing)
        result = await svc.get_all()

        billing.list_plans.assert_awaited_once()
        assert len(result) == 2
        assert result[0].name == "Basic"
        assert result[1].name == "Pro"


# ---------------------------------------------------------------------------
# Tests: get_by_name()
# ---------------------------------------------------------------------------


class TestPlanGetByName:
    async def test_get_by_name_delegates_to_billing(self):
        billing = AsyncMock()
        billing.get_plan_by_name.return_value = _make_billing_plan(Name="Premium")

        svc = _make_service(billing=billing)
        result = await svc.get_by_name("Premium")

        billing.get_plan_by_name.assert_awaited_once_with("Premium")
        assert result is not None
        assert result.name == "Premium"

    async def test_get_by_name_returns_none_when_not_found(self):
        billing = AsyncMock()
        billing.get_plan_by_name.return_value = None

        svc = _make_service(billing=billing)
        result = await svc.get_by_name("nonexistent")

        assert result is None


# ---------------------------------------------------------------------------
# Tests: get_trial()
# ---------------------------------------------------------------------------


class TestPlanGetTrial:
    async def test_get_trial_returns_active_plan(self):
        billing = AsyncMock()
        billing.get_trial_plan.return_value = _make_billing_plan(Name="Trial", IsActive=True)
        redis_client = AsyncMock()
        redis_client.get.return_value = None  # cache miss

        svc = _make_service(billing=billing, redis_client=redis_client)
        result = await svc.get_trial_plan()

        billing.get_trial_plan.assert_awaited_once()
        assert result is not None
        assert result.name == "Trial"

    async def test_get_trial_returns_none_when_inactive(self):
        billing = AsyncMock()
        billing.get_trial_plan.return_value = _make_billing_plan(Name="Trial", IsActive=False)
        redis_client = AsyncMock()
        redis_client.get.return_value = None

        svc = _make_service(billing=billing, redis_client=redis_client)
        result = await svc.get_trial_plan()

        # Inactive trial plan should not be returned
        assert result is None

    async def test_get_trial_returns_none_when_no_plan(self):
        billing = AsyncMock()
        billing.get_trial_plan.return_value = None
        redis_client = AsyncMock()
        redis_client.get.return_value = None

        svc = _make_service(billing=billing, redis_client=redis_client)
        result = await svc.get_trial_plan()

        assert result is None


# ---------------------------------------------------------------------------
# Tests: get_available()
# ---------------------------------------------------------------------------


class TestPlanGetAvailable:
    async def test_get_available_passes_telegram_id(self):
        billing = AsyncMock()
        billing.get_available_plans.return_value = [
            _make_billing_plan(ID=1, Name="Basic"),
        ]

        svc = _make_service(billing=billing)
        user = make_user(telegram_id=12345)
        result = await svc.get_available_plans(user)

        billing.get_available_plans.assert_awaited_once_with(12345)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Tests: create()
# ---------------------------------------------------------------------------


class TestPlanCreate:
    async def test_create_calls_billing_and_clears_cache(self):
        billing = AsyncMock()
        billing.create_plan.return_value = _make_billing_plan(ID=10, Name="New")
        redis_client = AsyncMock()

        svc = _make_service(billing=billing, redis_client=redis_client)

        from src.core.enums import PlanAvailability, PlanType
        from remnapy.enums import TrafficLimitStrategy
        plan = PlanDto(
            name="New",
            type=PlanType.BOTH,
            availability=PlanAvailability.ALL,
            traffic_limit=100,
            device_limit=3,
            traffic_limit_strategy=TrafficLimitStrategy.NO_RESET,
            internal_squads=[],
            durations=[],
        )
        result = await svc.create(plan)

        billing.create_plan.assert_awaited_once()
        assert result.name == "New"
        # Cache should be cleared after create
        redis_client.delete.assert_awaited()


# ---------------------------------------------------------------------------
# Tests: update()
# ---------------------------------------------------------------------------


class TestPlanUpdate:
    async def test_update_delegates_to_billing(self):
        billing = AsyncMock()
        billing.update_plan.return_value = _make_billing_plan(ID=1, Name="Updated")
        redis_client = AsyncMock()

        svc = _make_service(billing=billing, redis_client=redis_client)

        from src.core.enums import PlanAvailability, PlanType
        from remnapy.enums import TrafficLimitStrategy
        plan = PlanDto(
            id=1,
            name="Updated",
            type=PlanType.BOTH,
            availability=PlanAvailability.ALL,
            traffic_limit=100,
            device_limit=3,
            traffic_limit_strategy=TrafficLimitStrategy.NO_RESET,
            internal_squads=[],
            durations=[],
        )
        result = await svc.update(plan)

        billing.update_plan.assert_awaited_once()
        assert result is not None
        assert result.name == "Updated"
        redis_client.delete.assert_awaited()

    async def test_update_returns_none_when_billing_returns_none(self):
        billing = AsyncMock()
        billing.update_plan.return_value = None
        redis_client = AsyncMock()

        svc = _make_service(billing=billing, redis_client=redis_client)

        from src.core.enums import PlanAvailability, PlanType
        from remnapy.enums import TrafficLimitStrategy
        plan = PlanDto(
            id=1,
            name="Fail",
            type=PlanType.BOTH,
            availability=PlanAvailability.ALL,
            traffic_limit=100,
            device_limit=3,
            traffic_limit_strategy=TrafficLimitStrategy.NO_RESET,
            internal_squads=[],
            durations=[],
        )
        result = await svc.update(plan)

        assert result is None


# ---------------------------------------------------------------------------
# Tests: delete()
# ---------------------------------------------------------------------------


class TestPlanDelete:
    async def test_delete_calls_billing_and_returns_true(self):
        billing = AsyncMock()
        billing.delete_plan.return_value = True
        redis_client = AsyncMock()

        svc = _make_service(billing=billing, redis_client=redis_client)
        result = await svc.delete(42)

        billing.delete_plan.assert_awaited_once_with(42)
        assert result is True
        redis_client.delete.assert_awaited()

    async def test_delete_returns_false_on_exception(self):
        billing = AsyncMock()
        billing.delete_plan.side_effect = Exception("not found")
        redis_client = AsyncMock()

        svc = _make_service(billing=billing, redis_client=redis_client)
        result = await svc.delete(999)

        assert result is False
