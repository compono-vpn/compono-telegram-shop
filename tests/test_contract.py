"""Pins the shop <-> billing contract (BDT-405).

Loads the shared golden fixtures from contracts/shop-billing/v1/ (checked
into both compono-telegram-shop and compono-billing -- see
contracts/shop-billing/v1/README.md) and drives the real BillingClient
methods against them. For every Pydantic model this asserts, recursively,
that EVERY field the model declares round-trips to the exact fixture value
-- not a silently-applied Pydantic default -- which is exactly the failure
mode BDT-405 is about: a Go field rename/retype means the model keeps
"working" but every consumer just sees Price=0 / IsActive=True / None.

This file intentionally does not change any production code. If billing's
actual serialization drifts from these fixtures, update BOTH copies (here
and in compono-billing/contracts/shop-billing/v1/) together.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest
from pydantic import BaseModel

from src.infrastructure.billing.client import BillingClient
from src.infrastructure.billing.models import (
    BillingCustomer,
    BillingPaymentGateway,
    BillingPaymentResult,
    BillingPlan,
    BillingPlanSnapshot,
    BillingPromocode,
    BillingReferral,
    BillingReferralReward,
    BillingSettings,
    BillingStatistics,
    BillingSubscription,
    BillingTGProxy,
    BillingTransaction,
    BillingUser,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "contracts" / "shop-billing" / "v1" / "http"

BASE_URL = "http://billing.test:8080"
SECRET = "test-internal-secret"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text())


def _make_response(status_code: int, json_data: Any) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = ""
    resp.json.return_value = json_data
    return resp


def _make_client_with_mock(json_data: Any, status_code: int = 200) -> BillingClient:
    """A BillingClient whose HTTP layer always returns json_data, exactly
    like the shared helper in tests/test_billing_client.py."""
    client = BillingClient(BASE_URL, SECRET)
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.is_closed = False
    mock_http.request.return_value = _make_response(status_code, json_data)
    client._client = mock_http
    return client


def assert_model_matches_fixture(instance: Any, raw: Any, path: str = "$") -> None:
    """Recursively assert every field `instance` (a parsed Pydantic model,
    or a nested value inside one) declares equals the value the pinned
    fixture provides at the same path -- proving the field was actually
    populated from the response, not silently defaulted.
    """
    if isinstance(instance, BaseModel):
        assert isinstance(raw, dict), f"{path}: fixture is not an object ({raw!r})"
        for field_name, field in type(instance).model_fields.items():
            key = field.alias if field.alias else field_name
            assert key in raw, (
                f"{path}.{key}: {type(instance).__name__} declares field '{field_name}' "
                f"but the pinned contract fixture has no '{key}' key at this path"
            )
            assert_model_matches_fixture(getattr(instance, field_name), raw[key], f"{path}.{key}")
        return

    if isinstance(instance, list):
        assert isinstance(raw, list), f"{path}: fixture is not an array ({raw!r})"
        assert len(instance) == len(raw), (
            f"{path}: length mismatch -- parsed {len(instance)} item(s), fixture has {len(raw)}"
        )
        for i, (item, raw_item) in enumerate(zip(instance, raw)):
            assert_model_matches_fixture(item, raw_item, f"{path}[{i}]")
        return

    if isinstance(instance, datetime):
        assert raw is not None, (
            f"{path}: parsed as a datetime but the fixture value is null -- "
            "field silently defaulted instead of parsing the response"
        )
        return

    if instance is None:
        assert raw is None, (
            f"{path}: model value is None but the pinned fixture provides {raw!r} -- "
            "the field silently fell back to its default instead of parsing the response"
        )
        return

    assert instance == raw, f"{path}: expected {raw!r} from the fixture, got {instance!r} instead"


class TestPlanContract:
    async def test_get_plan(self):
        fixture = load_fixture("plan.json")
        client = _make_client_with_mock(fixture)

        plan = await client.get_plan(fixture["ID"])

        assert isinstance(plan, BillingPlan)
        assert_model_matches_fixture(plan, fixture)


class TestPlanSnapshotContract:
    def test_parses_pinned_shape(self):
        fixture = load_fixture("plan_snapshot.json")
        snapshot = BillingPlanSnapshot.model_validate(fixture)
        assert_model_matches_fixture(snapshot, fixture)


class TestUserContract:
    async def test_get_user(self):
        fixture = load_fixture("user.json")
        client = _make_client_with_mock(fixture)

        user = await client.get_user(fixture["TelegramID"])

        assert isinstance(user, BillingUser)
        assert_model_matches_fixture(user, fixture)


class TestSubscriptionContract:
    async def test_get_current_subscription(self):
        fixture = load_fixture("subscription.json")
        client = _make_client_with_mock(fixture)

        sub = await client.get_current_subscription(fixture["UserTelegramID"])

        assert isinstance(sub, BillingSubscription)
        assert_model_matches_fixture(sub, fixture)


class TestTransactionContract:
    async def test_get_transaction(self):
        fixture = load_fixture("transaction.json")
        client = _make_client_with_mock(fixture)

        tx = await client.get_transaction(UUID(fixture["PaymentID"]))

        assert isinstance(tx, BillingTransaction)
        assert_model_matches_fixture(tx, fixture)


class TestPromocodeContract:
    async def test_get_promocode(self):
        fixture = load_fixture("promocode.json")
        client = _make_client_with_mock(fixture)

        promo = await client.get_promocode(fixture["ID"])

        assert isinstance(promo, BillingPromocode)
        assert_model_matches_fixture(promo, fixture)


class TestSettingsContract:
    async def test_get_settings(self):
        fixture = load_fixture("settings.json")
        client = _make_client_with_mock(fixture)

        settings = await client.get_settings()

        assert isinstance(settings, BillingSettings)
        assert_model_matches_fixture(settings, fixture)


class TestPaymentGatewayContract:
    async def test_get_gateway(self):
        fixture = load_fixture("payment_gateway.json")
        client = _make_client_with_mock(fixture)

        gateway = await client.get_gateway(fixture["ID"])

        assert isinstance(gateway, BillingPaymentGateway)
        assert_model_matches_fixture(gateway, fixture)


class TestPaymentResultContract:
    async def test_create_payment(self):
        fixture = load_fixture("payment_result.json")
        client = _make_client_with_mock(fixture)

        result = await client.create_payment(
            telegram_id=123456789,
            plan_id=42,
            duration_days=30,
            currency="RUB",
            gateway_type="YOOKASSA",
            purchase_type="NEW",
        )

        assert isinstance(result, BillingPaymentResult)
        assert_model_matches_fixture(result, fixture)


class TestReferralContract:
    async def test_get_referral_by_referred(self):
        fixture = load_fixture("referral.json")
        client = _make_client_with_mock(fixture)

        referral = await client.get_referral_by_referred(fixture["ReferredTelegramID"])

        assert isinstance(referral, BillingReferral)
        assert_model_matches_fixture(referral, fixture)


class TestReferralRewardContract:
    async def test_update_referral_reward(self):
        fixture = load_fixture("referral_reward.json")
        client = _make_client_with_mock(fixture)

        reward = await client.update_referral_reward(fixture["ID"], is_issued=fixture["IsIssued"])

        assert isinstance(reward, BillingReferralReward)
        assert_model_matches_fixture(reward, fixture)


class TestStatisticsContract:
    async def test_get_statistics(self):
        fixture = load_fixture("statistics.json")
        client = _make_client_with_mock(fixture)

        stats = await client.get_statistics()

        assert isinstance(stats, BillingStatistics)
        assert_model_matches_fixture(stats, fixture)


class TestCustomerContract:
    async def test_get_customer_by_id(self):
        fixture = load_fixture("customer.json")
        client = _make_client_with_mock(fixture)

        customer = await client.get_customer_by_id(fixture["ID"])

        assert isinstance(customer, BillingCustomer)
        assert_model_matches_fixture(customer, fixture)


class TestTGProxyContract:
    async def test_get_tg_proxies(self):
        """BillingTGProxy intentionally only consumes a subset of the fields
        billing actually serves (id/server/port/secret/link) -- it does not
        use eligible_plan_ids/is_active/created_at/updated_at. So this only
        asserts the fields the model DOES declare, not full fixture parity;
        see contracts/shop-billing/v1/README.md.
        """
        fixture = load_fixture("tg_proxy.json")
        client = _make_client_with_mock([fixture])

        proxies = await client.get_tg_proxies(plan_id=1)

        assert len(proxies) == 1
        assert isinstance(proxies[0], BillingTGProxy)
        assert_model_matches_fixture(proxies[0], fixture)


class TestUsersCountContract:
    """GET /users (no role) returns {"count": N} -- pins that count_users()
    still reads the real count rather than silently returning its 0
    fallback (client.py: `data.get("count", 0)` when isinstance(data, dict)).
    """

    async def test_count_users_reads_real_count_not_the_fallback(self):
        fixture = load_fixture("users_count.json")
        assert fixture["count"] != 0, "fixture must be non-zero to catch a silent 0 fallback"
        client = _make_client_with_mock(fixture)

        result = await client.count_users()

        assert result == fixture["count"]


class TestUsersListContract:
    """GET /users?role=... returns a JSON array -- pins that
    list_users_by_role() still parses BillingUser instances from it (the
    other branch of the same overloaded endpoint as TestUsersCountContract).
    """

    async def test_list_users_by_role_parses_pinned_user_shape(self):
        fixture = load_fixture("user.json")
        client = _make_client_with_mock([fixture])

        users = await client.list_users_by_role("ADMIN")

        assert len(users) == 1
        assert isinstance(users[0], BillingUser)
        assert_model_matches_fixture(users[0], fixture)


@pytest.mark.parametrize(
    "fixture_name",
    [
        "notify_user_system.json",
        "notify_user_redirect.json",
    ],
)
def test_kafka_notify_user_fixtures_have_documented_shape(fixture_name):
    """The notify.user Kafka event (src/infrastructure/kafka/consumer.py,
    UserNotificationConsumer) is consumed as a raw dict via payload.get(...),
    not a Pydantic model, so there is no DTO to pin here. This just asserts
    the two variants documented in that consumer's docstring / this module's
    docstring still round-trip as valid JSON with the keys the consumer
    reads, so the fixtures can't silently rot relative to the code comment.
    """
    fixture = json.loads((FIXTURES_DIR.parent / "kafka" / fixture_name).read_text())
    assert fixture["telegram_id"]
    assert fixture["type"] in ("system", "redirect")
    if fixture["type"] == "system":
        assert {"ntf_type", "i18n_key", "i18n_kwargs"} <= fixture.keys()
    else:
        assert {"redirect_to", "purchase_type"} <= fixture.keys()
