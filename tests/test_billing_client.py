"""Tests for BillingClient -- verifies HTTP calls, serialization, and error handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import httpx
import pytest

from src.infrastructure.billing.client import BillingClient, BillingClientError
from src.infrastructure.billing.models import (
    BillingCustomer,
    BillingPaymentGateway,
    BillingPaymentResult,
    BillingPlan,
    BillingPortalLookup,
    BillingPriceDetails,
    BillingPromocode,
    BillingReferral,
    BillingReferralReward,
    BillingSettings,
    BillingStatistics,
    BillingSubscription,
    BillingTGProxy,
    BillingTransaction,
    BillingUser,
    BillingWebOrder,
    BillingWebOrderResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_URL = "http://billing.test:8080"
SECRET = "test-internal-secret"


_SENTINEL = object()


def _make_response(status_code: int = 200, json_data=_SENTINEL, text: str = "") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text or ""
    if json_data is not _SENTINEL:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = Exception("No JSON body")
    return resp


def _make_client_with_mock() -> tuple[BillingClient, AsyncMock]:
    """Return a BillingClient with a mocked httpx.AsyncClient injected."""
    client = BillingClient(BASE_URL, SECRET)
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.is_closed = False
    client._client = mock_http
    return client, mock_http


SAMPLE_PLAN = {
    "ID": 42,
    "OrderIndex": 1,
    "IsActive": True,
    "Type": "BOTH",
    "Availability": "ALL",
    "Name": "Pro Plan",
    "Description": "Best plan",
    "Tag": "pro",
    "TrafficLimit": 300,
    "DeviceLimit": 6,
    "TrafficLimitStrategy": "MONTH",
    "AllowedUserIDs": [],
    "InternalSquads": [],
    "ExternalSquad": None,
    "Durations": [
        {
            "ID": 1,
            "PlanID": 42,
            "Days": 30,
            "Prices": [{"ID": 1, "DurationID": 1, "Currency": "RUB", "Price": "119"}],
        }
    ],
}

SAMPLE_USER = {
    "ID": 1,
    "TelegramID": 123456789,
    "Username": "testuser",
    "ReferralCode": "REF123",
    "Name": "Test User",
    "Role": "USER",
    "Language": "RU",
    "PersonalDiscount": 0,
    "PurchaseDiscount": 10,
    "PurchaseDiscountMaxDays": 30,
    "Points": 100,
    "Source": "organic",
    "IsBlocked": False,
    "IsBotBlocked": False,
    "IsRulesAccepted": True,
    "CreatedAt": "2025-01-01T00:00:00Z",
    "UpdatedAt": "2025-06-01T00:00:00Z",
}

SAMPLE_SUBSCRIPTION = {
    "ID": 10,
    "UserRemnaID": "550e8400-e29b-41d4-a716-446655440000",
    "UserTelegramID": 123456789,
    "Status": "ACTIVE",
    "IsTrial": False,
    "TrafficLimit": 300,
    "DeviceLimit": 6,
    "TrafficLimitStrategy": "MONTH",
    "Tag": "pro",
    "InternalSquads": [],
    "ExternalSquad": None,
    "ExpireAt": "2026-05-01T00:00:00Z",
    "URL": "https://panel.example.com/sub/abc",
    "Plan": {
        "id": 42,
        "name": "Pro Plan",
        "tag": "pro",
        "type": "BOTH",
        "traffic_limit": 300,
        "device_limit": 6,
        "duration": 30,
        "traffic_limit_strategy": "MONTH",
        "internal_squads": [],
        "external_squad": None,
    },
    "CreatedAt": "2025-01-01T00:00:00Z",
    "UpdatedAt": "2025-06-01T00:00:00Z",
}

SAMPLE_TRANSACTION = {
    "ID": 5,
    "PaymentID": "550e8400-e29b-41d4-a716-446655440001",
    "UserTelegramID": 123456789,
    "Status": "COMPLETED",
    "IsTest": False,
    "PurchaseType": "NEW",
    "GatewayType": "TELEGRAM_STARS",
    "Pricing": {
        "original_amount": "100",
        "discount_percent": 10,
        "final_amount": "90",
    },
    "Currency": "XTR",
    "Plan": {
        "id": 42,
        "name": "Pro Plan",
        "tag": "pro",
        "type": "BOTH",
        "traffic_limit": 300,
        "device_limit": 6,
        "duration": 30,
        "traffic_limit_strategy": "MONTH",
        "internal_squads": [],
        "external_squad": None,
    },
    "CreatedAt": "2025-06-01T00:00:00Z",
    "UpdatedAt": "2025-06-01T00:00:00Z",
}

SAMPLE_GATEWAY = {
    "ID": 3,
    "OrderIndex": 1,
    "Type": "PLATEGA",
    "Channel": "ALL",
    "Currency": "RUB",
    "IsActive": True,
    "Settings": None,
}

SAMPLE_SETTINGS = {
    "ID": 1,
    "RulesRequired": True,
    "ChannelRequired": False,
    "RulesLink": "https://example.com/rules",
    "ChannelID": -1001234567890,
    "ChannelLink": "@test_channel",
    "AccessMode": "PUBLIC",
    "PurchasesAllowed": True,
    "RegistrationAllowed": True,
    "DefaultCurrency": "XTR",
    "UserNotifications": {"expires_in_3_days": True, "expired": False},
    "SystemNotifications": {"user_registered": True, "subscription": False},
    "Referral": {
        "Enable": True,
        "Level": "1",
        "AccrualStrategy": "ON_FIRST_PAYMENT",
        "Reward": {"Type": "EXTRA_DAYS", "Strategy": "AMOUNT", "Config": {"1": 5}},
    },
}

SAMPLE_REFERRAL = {
    "ID": 7,
    "ReferrerTelegramID": 111111,
    "ReferredTelegramID": 222222,
    "Level": "1",
    "CreatedAt": "2025-06-01T00:00:00Z",
    "UpdatedAt": "2025-06-01T00:00:00Z",
}

SAMPLE_REFERRAL_REWARD = {
    "ID": 9,
    "ReferralID": 7,
    "UserTelegramID": 111111,
    "Type": "EXTRA_DAYS",
    "Amount": 5,
    "IsIssued": False,
    "CreatedAt": "2025-06-01T00:00:00Z",
    "UpdatedAt": "2025-06-01T00:00:00Z",
}

SAMPLE_PROMOCODE = {
    "ID": 15,
    "Code": "WELCOME10",
    "IsActive": True,
    "Availability": "ALL",
    "RewardType": "PERSONAL_DISCOUNT",
    "Reward": 10,
    "Plan": None,
    "PurchaseDiscountMaxDays": 30,
    "Lifetime": -1,
    "MaxActivations": 100,
    "AllowedTelegramIDs": None,
    "Activations": [],
    "CreatedAt": "2025-01-01T00:00:00Z",
    "UpdatedAt": "2025-06-01T00:00:00Z",
}



# ---------------------------------------------------------------------------
# _request internals
# ---------------------------------------------------------------------------


class TestRequestInternals:
    """Tests for the _request method: URL construction, headers, error handling."""

    async def test_constructs_correct_url(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, {"ok": True})

        await client._request("GET", "/plans")

        call_args = mock_http.request.call_args
        assert call_args[0] == ("GET", f"{BASE_URL}/api/v1/internal/plans")

    async def test_passes_json_body(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, {"ID": 1})

        body = {"telegram_id": 123, "plan_id": 1}
        await client._request("POST", "/users", json=body)

        call_args = mock_http.request.call_args
        assert call_args[1]["json"] == body

    async def test_passes_query_params(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, [])

        await client._request("GET", "/plans/available", params={"telegram_id": "123"})

        call_args = mock_http.request.call_args
        assert call_args[1]["params"] == {"telegram_id": "123"}

    async def test_returns_none_on_204(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(204)

        result = await client._request("DELETE", "/plans/1")
        assert result is None

    async def test_raises_billing_error_on_4xx(self):
        client, mock_http = _make_client_with_mock()
        resp = _make_response(400, json_data={"error": "invalid input"}, text="bad request")
        mock_http.request.return_value = resp

        with pytest.raises(BillingClientError) as exc_info:
            await client._request("POST", "/users")
        assert exc_info.value.status_code == 400
        assert "invalid input" in exc_info.value.message

    async def test_raises_billing_error_on_500(self):
        client, mock_http = _make_client_with_mock()
        resp = _make_response(500, text="internal error")
        resp.json.side_effect = Exception("not json")
        mock_http.request.return_value = resp

        with pytest.raises(BillingClientError) as exc_info:
            await client._request("GET", "/settings")
        assert exc_info.value.status_code == 500

    async def test_raises_billing_error_on_http_error(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.side_effect = httpx.ConnectError("connection refused")

        with pytest.raises(BillingClientError) as exc_info:
            await client._request("GET", "/plans")
        assert exc_info.value.status_code == 0
        assert "connection refused" in exc_info.value.message

    async def test_headers_include_internal_secret(self):
        client = BillingClient(BASE_URL, SECRET)
        headers = client._headers()
        assert headers["X-Internal-Secret"] == SECRET
        assert headers["Content-Type"] == "application/json"

    async def test_base_path(self):
        client = BillingClient(BASE_URL, SECRET)
        assert client._base_path == f"{BASE_URL}/api/v1/internal"

    async def test_base_url_trailing_slash_stripped(self):
        client = BillingClient(f"{BASE_URL}/", SECRET)
        assert client.base_url == BASE_URL


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------


class TestPlans:

    async def test_list_plans(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, [SAMPLE_PLAN])

        result = await client.list_plans()

        assert len(result) == 1
        assert isinstance(result[0], BillingPlan)
        assert result[0].ID == 42
        assert result[0].Name == "Pro Plan"

    async def test_list_plans_empty(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, [])

        result = await client.list_plans()
        assert result == []

    async def test_get_plan(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_PLAN)

        result = await client.get_plan(42)

        assert isinstance(result, BillingPlan)
        assert result.ID == 42
        mock_http.request.assert_called_once()
        url = mock_http.request.call_args[0][1]
        assert url.endswith("/plans/42")

    async def test_get_plan_by_name(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_PLAN)

        result = await client.get_plan_by_name("Pro Plan")

        assert isinstance(result, BillingPlan)
        call_kwargs = mock_http.request.call_args[1]
        assert call_kwargs["params"] == {"name": "Pro Plan"}

    async def test_get_plan_by_name_not_found(self):
        client, mock_http = _make_client_with_mock()
        resp = _make_response(404, text="not found")
        resp.json.return_value = {"error": "not found"}
        mock_http.request.return_value = resp

        result = await client.get_plan_by_name("NonExistent")
        assert result is None

    async def test_get_trial_plan(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_PLAN)

        result = await client.get_trial_plan()

        assert isinstance(result, BillingPlan)
        url = mock_http.request.call_args[0][1]
        assert url.endswith("/plans/trial")

    async def test_get_available_plans(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, [SAMPLE_PLAN])

        result = await client.get_available_plans(123456789)

        assert len(result) == 1
        call_kwargs = mock_http.request.call_args[1]
        assert call_kwargs["params"] == {"telegram_id": "123456789"}

    async def test_get_allowed_plans(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, [SAMPLE_PLAN])

        result = await client.get_allowed_plans()

        assert len(result) == 1
        url = mock_http.request.call_args[0][1]
        assert url.endswith("/plans/allowed")

    async def test_create_plan(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_PLAN)

        plan_data = {"Name": "New Plan", "Type": "BOTH"}
        result = await client.create_plan(plan_data)

        assert isinstance(result, BillingPlan)
        call_args = mock_http.request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[1]["json"] == plan_data

    async def test_update_plan(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_PLAN)

        plan_data = {"ID": 42, "Name": "Updated Plan"}
        result = await client.update_plan(plan_data)

        assert isinstance(result, BillingPlan)
        call_args = mock_http.request.call_args
        assert call_args[0][0] == "PUT"

    async def test_delete_plan(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(204)

        result = await client.delete_plan(42)

        assert result is True
        url = mock_http.request.call_args[0][1]
        assert url.endswith("/plans/42")

    async def test_move_plan_up(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(204)

        result = await client.move_plan_up(42)

        assert result is True
        url = mock_http.request.call_args[0][1]
        assert url.endswith("/plans/42/move-up")


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class TestUsers:

    async def test_get_user(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_USER)

        result = await client.get_user(123456789)

        assert isinstance(result, BillingUser)
        assert result.TelegramID == 123456789
        assert result.Username == "testuser"
        url = mock_http.request.call_args[0][1]
        assert url.endswith("/users/123456789")

    async def test_get_user_returns_none_on_empty(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, json_data=None)

        result = await client.get_user(999)
        assert result is None

    async def test_create_user(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_USER)

        user_data = {"TelegramID": 123456789, "Name": "Test"}
        result = await client.create_user(user_data)

        assert isinstance(result, BillingUser)
        call_args = mock_http.request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[1]["json"] == user_data

    async def test_update_user(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_USER)

        user_data = {"Name": "Updated"}
        result = await client.update_user(123456789, user_data)

        assert isinstance(result, BillingUser)
        url = mock_http.request.call_args[0][1]
        assert url.endswith("/users/123456789")

    async def test_delete_user(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(204)

        await client.delete_user(123456789)

        call_args = mock_http.request.call_args
        assert call_args[0][0] == "DELETE"
        url = call_args[0][1]
        assert url.endswith("/users/123456789")

    async def test_list_users_by_role(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, [SAMPLE_USER])

        result = await client.list_users_by_role("ADMIN")

        assert len(result) == 1
        assert isinstance(result[0], BillingUser)

    async def test_count_users(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, {"count": 42})

        result = await client.count_users()
        assert result == 42

    async def test_get_user_by_referral_code(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_USER)

        result = await client.get_user_by_referral_code("REF123")

        assert isinstance(result, BillingUser)
        assert result.ReferralCode == "REF123"


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------


class TestSubscriptions:

    async def test_get_current_subscription(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_SUBSCRIPTION)

        result = await client.get_current_subscription(123456789)

        assert isinstance(result, BillingSubscription)
        assert result.ID == 10
        assert result.Status == "ACTIVE"
        url = mock_http.request.call_args[0][1]
        assert url.endswith("/subscription/123456789/current")

    async def test_get_current_subscription_none(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, json_data=None)

        result = await client.get_current_subscription(999)
        assert result is None

    async def test_has_used_trial_true(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, {"used": True})

        result = await client.has_used_trial(123456789)
        assert result is True

    async def test_has_used_trial_false(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, {"used": False})

        result = await client.has_used_trial(123456789)
        assert result is False

    async def test_link_subscription(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(204)

        await client.link_subscription(123456789, "token123")

        call_args = mock_http.request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[1]["json"] == {
            "telegram_id": 123456789,
            "subscription_token": "token123",
        }

    async def test_create_trial_subscription(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(204)

        await client.create_trial_subscription(123456789, 1)

        call_args = mock_http.request.call_args
        assert call_args[1]["json"] == {"telegram_id": 123456789, "plan_id": 1}

    async def test_delete_subscription(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(204)

        await client.delete_subscription(123456789, 10)

        call_args = mock_http.request.call_args
        assert call_args[1]["json"] == {"telegram_id": 123456789, "subscription_id": 10}

    async def test_get_subscription_not_found(self):
        client, mock_http = _make_client_with_mock()
        resp = _make_response(404, text="not found")
        resp.json.return_value = {"error": "not found"}
        mock_http.request.return_value = resp

        result = await client.get_subscription(999)
        assert result is None

    async def test_list_all_subscriptions(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, [SAMPLE_SUBSCRIPTION])

        result = await client.list_all_subscriptions()

        assert len(result) == 1
        assert isinstance(result[0], BillingSubscription)


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


class TestTransactions:

    async def test_create_transaction(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_TRANSACTION)

        tx_data = {"plan_id": 42, "gateway_type": "TELEGRAM_STARS"}
        result = await client.create_transaction(123456789, tx_data)

        assert isinstance(result, BillingTransaction)
        call_args = mock_http.request.call_args
        assert call_args[0][0] == "POST"
        body = call_args[1]["json"]
        assert body["telegram_id"] == 123456789
        assert body["plan_id"] == 42

    async def test_list_transactions(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, [SAMPLE_TRANSACTION])

        result = await client.list_transactions(123456789)

        assert len(result) == 1
        assert isinstance(result[0], BillingTransaction)
        url = mock_http.request.call_args[0][1]
        assert url.endswith("/transactions/123456789")

    async def test_get_transaction(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_TRANSACTION)

        payment_id = UUID("550e8400-e29b-41d4-a716-446655440001")
        result = await client.get_transaction(payment_id)

        assert isinstance(result, BillingTransaction)
        assert result.ID == 5
        url = mock_http.request.call_args[0][1]
        assert str(payment_id) in url

    async def test_get_transaction_not_found(self):
        client, mock_http = _make_client_with_mock()
        resp = _make_response(404, text="not found")
        resp.json.return_value = {"error": "not found"}
        mock_http.request.return_value = resp

        result = await client.get_transaction(uuid4())
        assert result is None

    async def test_list_all_transactions(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, [SAMPLE_TRANSACTION])

        result = await client.list_all_transactions()

        assert len(result) == 1
        url = mock_http.request.call_args[0][1]
        assert url.endswith("/transactions/stats")

    async def test_list_all_transactions_non_list(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, {"stats": "something"})

        result = await client.list_all_transactions()
        assert result == []

    async def test_list_transactions_by_status(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, [SAMPLE_TRANSACTION])

        result = await client.list_transactions_by_status("COMPLETED")

        assert len(result) == 1
        call_kwargs = mock_http.request.call_args[1]
        assert call_kwargs["params"] == {"status": "COMPLETED"}

    async def test_transition_transaction_status(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_TRANSACTION)

        payment_id = UUID("550e8400-e29b-41d4-a716-446655440001")
        result = await client.transition_transaction_status(payment_id, "PENDING", "COMPLETED")

        assert isinstance(result, BillingTransaction)
        call_args = mock_http.request.call_args
        assert call_args[0][0] == "PUT"
        assert call_args[1]["json"] == {"from_status": "PENDING", "to_status": "COMPLETED"}

    async def test_transition_transaction_status_conflict(self):
        client, mock_http = _make_client_with_mock()
        resp = _make_response(409, text="conflict")
        resp.json.return_value = {"error": "conflict"}
        mock_http.request.return_value = resp

        result = await client.transition_transaction_status(uuid4(), "PENDING", "COMPLETED")
        assert result is None

    async def test_count_transactions(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, {"pending": 5, "completed": 10})

        result = await client.count_transactions()
        assert result == {"pending": 5, "completed": 10}


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------


class TestPayments:

    async def test_create_payment(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, {"ID": "pay-123", "URL": "https://pay.example.com"})

        result = await client.create_payment(
            telegram_id=123,
            plan_id=42,
            duration_days=30,
            currency="RUB",
            gateway_type="PLATEGA",
            purchase_type="NEW",
        )

        assert isinstance(result, BillingPaymentResult)
        assert result.ID == "pay-123"
        assert result.URL == "https://pay.example.com"
        body = mock_http.request.call_args[1]["json"]
        assert body["telegram_id"] == 123
        assert body["plan_id"] == 42
        assert body["is_test"] is False
        assert "promocode_id" not in body

    async def test_create_payment_with_promocode(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, {"ID": "pay-456", "URL": None})

        result = await client.create_payment(
            telegram_id=123,
            plan_id=42,
            duration_days=30,
            currency="XTR",
            gateway_type="TELEGRAM_STARS",
            purchase_type="RENEW",
            promocode_id=15,
        )

        body = mock_http.request.call_args[1]["json"]
        assert body["promocode_id"] == 15

    async def test_handle_free_payment(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(204)

        payment_id = uuid4()
        await client.handle_free_payment(payment_id)

        body = mock_http.request.call_args[1]["json"]
        assert body["payment_id"] == str(payment_id)


# ---------------------------------------------------------------------------
# Promocodes
# ---------------------------------------------------------------------------


class TestPromocodes:

    async def test_list_promocodes(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, [SAMPLE_PROMOCODE])

        result = await client.list_promocodes()

        assert len(result) == 1
        assert isinstance(result[0], BillingPromocode)
        assert result[0].Code == "WELCOME10"

    async def test_get_promocode(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_PROMOCODE)

        result = await client.get_promocode(15)

        assert isinstance(result, BillingPromocode)
        assert result.ID == 15

    async def test_get_promocode_not_found(self):
        client, mock_http = _make_client_with_mock()
        resp = _make_response(404, text="not found")
        resp.json.return_value = {"error": "not found"}
        mock_http.request.return_value = resp

        result = await client.get_promocode(999)
        assert result is None

    async def test_get_promocode_by_code(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_PROMOCODE)

        result = await client.get_promocode_by_code("WELCOME10")

        assert isinstance(result, BillingPromocode)
        call_kwargs = mock_http.request.call_args[1]
        assert call_kwargs["params"] == {"code": "WELCOME10"}

    async def test_get_promocode_by_code_not_found(self):
        client, mock_http = _make_client_with_mock()
        resp = _make_response(404, text="not found")
        resp.json.return_value = {"error": "not found"}
        mock_http.request.return_value = resp

        result = await client.get_promocode_by_code("INVALID")
        assert result is None

    async def test_create_promocode(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_PROMOCODE)

        promo_data = {"Code": "NEW10", "RewardType": "PERSONAL_DISCOUNT"}
        result = await client.create_promocode(promo_data)

        assert isinstance(result, BillingPromocode)
        assert mock_http.request.call_args[0][0] == "POST"

    async def test_delete_promocode(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(204)

        result = await client.delete_promocode(15)

        assert result is True
        body = mock_http.request.call_args[1]["json"]
        assert body == {"id": 15}

    async def test_activate_promocode(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(204)

        await client.activate_promocode("WELCOME10", 123456789)

        body = mock_http.request.call_args[1]["json"]
        assert body == {"code": "WELCOME10", "telegram_id": 123456789}

    async def test_validate_promocode(self):
        client, mock_http = _make_client_with_mock()
        # validate_promocode uses client.post() directly, not _request
        mock_http.post.return_value = _make_response(200, {"valid": True, "reward": 10})

        result = await client.validate_promocode("WELCOME10")

        assert result == {"valid": True, "reward": 10}
        url = mock_http.post.call_args[0][0]
        assert "/api/v1/promocode/validate" in url

    async def test_validate_promocode_invalid(self):
        client, mock_http = _make_client_with_mock()
        mock_http.post.return_value = _make_response(400, json_data={"error": "invalid"}, text="invalid")

        result = await client.validate_promocode("BAD")
        assert result is None


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class TestSettings:

    async def test_get_settings(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_SETTINGS)

        result = await client.get_settings()

        assert isinstance(result, BillingSettings)
        assert result.RulesRequired is True
        assert result.DefaultCurrency == "XTR"
        url = mock_http.request.call_args[0][1]
        assert url.endswith("/settings")

    async def test_update_settings(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_SETTINGS)

        settings_data = {"RulesRequired": False}
        result = await client.update_settings(settings_data)

        assert isinstance(result, BillingSettings)
        call_args = mock_http.request.call_args
        assert call_args[0][0] == "PUT"
        assert call_args[1]["json"] == settings_data

    async def test_get_default_currency(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, {"currency": "RUB"})

        result = await client.get_default_currency()
        assert result == "RUB"

    async def test_set_default_currency(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(204)

        await client.set_default_currency("USD")

        body = mock_http.request.call_args[1]["json"]
        assert body == {"currency": "USD"}


# ---------------------------------------------------------------------------
# Payment Gateways
# ---------------------------------------------------------------------------


class TestGateways:

    async def test_list_gateways(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, [SAMPLE_GATEWAY])

        result = await client.list_gateways()

        assert len(result) == 1
        assert isinstance(result[0], BillingPaymentGateway)
        assert result[0].Type == "PLATEGA"

    async def test_list_active_gateways(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, [SAMPLE_GATEWAY])

        result = await client.list_active_gateways()

        assert len(result) == 1
        url = mock_http.request.call_args[0][1]
        assert url.endswith("/gateways/active")

    async def test_get_gateway(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_GATEWAY)

        result = await client.get_gateway(3)

        assert isinstance(result, BillingPaymentGateway)
        url = mock_http.request.call_args[0][1]
        assert url.endswith("/gateways/3")

    async def test_get_gateway_not_found(self):
        client, mock_http = _make_client_with_mock()
        resp = _make_response(404, text="not found")
        resp.json.return_value = {"error": "not found"}
        mock_http.request.return_value = resp

        result = await client.get_gateway(999)
        assert result is None

    async def test_get_gateway_by_type(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_GATEWAY)

        result = await client.get_gateway_by_type("PLATEGA")

        assert isinstance(result, BillingPaymentGateway)
        call_kwargs = mock_http.request.call_args[1]
        assert call_kwargs["params"] == {"type": "PLATEGA"}

    async def test_get_gateway_by_type_not_found(self):
        client, mock_http = _make_client_with_mock()
        resp = _make_response(404, text="not found")
        resp.json.return_value = {"error": "not found"}
        mock_http.request.return_value = resp

        result = await client.get_gateway_by_type("UNKNOWN")
        assert result is None

    async def test_create_gateway(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_GATEWAY)

        gw_data = {"Type": "PLATEGA", "Currency": "RUB"}
        result = await client.create_gateway(gw_data)

        assert isinstance(result, BillingPaymentGateway)
        assert mock_http.request.call_args[0][0] == "POST"

    async def test_delete_gateway(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(204)

        result = await client.delete_gateway(3)

        assert result is True
        body = mock_http.request.call_args[1]["json"]
        assert body == {"id": 3}

    async def test_move_gateway_up(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(204)

        result = await client.move_gateway_up(3)

        assert result is True
        url = mock_http.request.call_args[0][1]
        assert url.endswith("/gateways/3/move-up")

    async def test_create_test_payment(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, {"ID": "test-pay", "URL": None})

        result = await client.create_test_payment(123, "PLATEGA")

        assert isinstance(result, BillingPaymentResult)
        body = mock_http.request.call_args[1]["json"]
        assert body == {"telegram_id": 123, "gateway_type": "PLATEGA"}


# ---------------------------------------------------------------------------
# Referrals
# ---------------------------------------------------------------------------


class TestReferrals:

    async def test_link_referral(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(204)

        await client.link_referral("REF123", 222222)

        body = mock_http.request.call_args[1]["json"]
        assert body == {"referrer_code": "REF123", "referred_telegram_id": 222222}

    async def test_get_referral_info(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, {"referral_code": "REF123", "referrals_count": 3})

        result = await client.get_referral_info(111111)

        assert result["referral_code"] == "REF123"
        url = mock_http.request.call_args[0][1]
        assert url.endswith("/referral/111111")

    async def test_create_referral(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_REFERRAL)

        result = await client.create_referral(111111, 222222, "1")

        assert isinstance(result, BillingReferral)
        body = mock_http.request.call_args[1]["json"]
        assert body == {
            "referrer_telegram_id": 111111,
            "referred_telegram_id": 222222,
            "level": "1",
        }

    async def test_get_referral_by_referred(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_REFERRAL)

        result = await client.get_referral_by_referred(222222)

        assert isinstance(result, BillingReferral)
        url = mock_http.request.call_args[0][1]
        assert url.endswith("/referrals/by-referred/222222")

    async def test_get_referrals_by_referrer(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, [SAMPLE_REFERRAL])

        result = await client.get_referrals_by_referrer(111111)

        assert len(result) == 1
        assert isinstance(result[0], BillingReferral)

    async def test_create_referral_reward(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_REFERRAL_REWARD)

        result = await client.create_referral_reward(7, 111111, "EXTRA_DAYS", 5)

        assert isinstance(result, BillingReferralReward)
        body = mock_http.request.call_args[1]["json"]
        assert body["referral_id"] == 7
        assert body["is_issued"] is False

    async def test_update_referral_reward(self):
        client, mock_http = _make_client_with_mock()
        issued_reward = {**SAMPLE_REFERRAL_REWARD, "IsIssued": True}
        mock_http.request.return_value = _make_response(200, issued_reward)

        result = await client.update_referral_reward(9, True)

        assert isinstance(result, BillingReferralReward)
        url = mock_http.request.call_args[0][1]
        assert url.endswith("/referral/reward/9")

    async def test_get_rewards_by_referral(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, [SAMPLE_REFERRAL_REWARD])

        result = await client.get_rewards_by_referral(7)

        assert len(result) == 1
        assert isinstance(result[0], BillingReferralReward)

    async def test_get_referral_stats(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, {"total": 5, "active": 3})

        result = await client.get_referral_stats(111111)

        assert result == {"total": 5, "active": 3}

    async def test_list_referral_rewards(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, [{"id": 1, "amount": 5}])

        result = await client.list_referral_rewards(111111)

        assert len(result) == 1


# ---------------------------------------------------------------------------
# Broadcasts
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Web Orders
# ---------------------------------------------------------------------------


class TestWebOrders:

    async def test_claim_web_order(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, {
            "status": "claimed",
            "order": {"ID": 1, "PaymentID": "abc", "ShortID": "XY12", "Status": "claimed"},
        })

        result = await client.claim_web_order(123, "XY12")

        assert isinstance(result, BillingWebOrderResult)
        assert result.status == "claimed"
        body = mock_http.request.call_args[1]["json"]
        assert body == {"telegram_id": 123, "short_id": "XY12"}

    async def test_get_web_order_by_short_id(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, {
            "ID": 1, "ShortID": "XY12", "Status": "pending",
        })

        result = await client.get_web_order_by_short_id("XY12")

        assert isinstance(result, BillingWebOrder)
        call_kwargs = mock_http.request.call_args[1]
        assert call_kwargs["params"] == {"short_id": "XY12"}

    async def test_get_web_order_not_found(self):
        client, mock_http = _make_client_with_mock()
        resp = _make_response(404, text="not found")
        resp.json.return_value = {"error": "not found"}
        mock_http.request.return_value = resp

        result = await client.get_web_order_by_short_id("NOPE")
        assert result is None

    async def test_exists_claimed_web_order(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, {"exists": True})

        result = await client.exists_claimed_web_order_by_telegram_id(123)

        assert result is True
        call_kwargs = mock_http.request.call_args[1]
        assert call_kwargs["params"] == {"telegram_id": "123"}

    async def test_exists_claimed_web_order_error_returns_false(self):
        client, mock_http = _make_client_with_mock()
        resp = _make_response(500, text="server error")
        resp.json.return_value = {"error": "server error"}
        mock_http.request.return_value = resp

        result = await client.exists_claimed_web_order_by_telegram_id(123)
        assert result is False


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------


class TestCustomers:

    SAMPLE_CUSTOMER = {
        "ID": 1,
        "TelegramID": 123,
        "Email": "test@example.com",
        "RemnaUserUUID": "550e8400-e29b-41d4-a716-446655440000",
        "RemnaUsername": "testuser",
        "SubscriptionURL": "https://example.com/sub",
    }

    async def test_get_customer_by_id(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, self.SAMPLE_CUSTOMER)

        result = await client.get_customer_by_id(1)

        assert isinstance(result, BillingCustomer)
        assert result.Email == "test@example.com"

    async def test_get_customer_by_id_not_found(self):
        client, mock_http = _make_client_with_mock()
        resp = _make_response(404, text="not found")
        resp.json.return_value = {"error": "not found"}
        mock_http.request.return_value = resp

        result = await client.get_customer_by_id(999)
        assert result is None

    async def test_get_customer_by_email(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, self.SAMPLE_CUSTOMER)

        result = await client.get_customer_by_email("test@example.com")

        assert isinstance(result, BillingCustomer)
        call_kwargs = mock_http.request.call_args[1]
        assert call_kwargs["params"] == {"email": "test@example.com"}

    async def test_get_or_create_customer(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, self.SAMPLE_CUSTOMER)

        result = await client.get_or_create_customer_by_telegram_id(123)

        assert isinstance(result, BillingCustomer)
        body = mock_http.request.call_args[1]["json"]
        assert body == {"telegram_id": 123}


# ---------------------------------------------------------------------------
# Statistics & Pricing
# ---------------------------------------------------------------------------


class TestStatisticsAndPricing:

    async def test_get_statistics(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, {
            "total_users": 100,
            "total_subscriptions": 50,
            "total_revenue": "10000",
            "active_subscriptions": 30,
            "trial_users": 10,
            "today_transactions": 5,
        })

        result = await client.get_statistics()

        assert isinstance(result, BillingStatistics)
        assert result.total_users == 100
        assert result.total_revenue == "10000"

    async def test_calculate_price(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, {
            "original_amount": "100",
            "discount_percent": 10,
            "final_amount": "90",
        })

        result = await client.calculate_price(123, 42, 30, "RUB")

        assert isinstance(result, BillingPriceDetails)
        assert result.original_amount == "100"
        assert result.final_amount == "90"
        body = mock_http.request.call_args[1]["json"]
        assert body == {
            "telegram_id": 123,
            "plan_id": 42,
            "duration_days": 30,
            "currency": "RUB",
        }


# ---------------------------------------------------------------------------
# Portal & TG Proxies
# ---------------------------------------------------------------------------


class TestPortalAndProxies:

    async def test_portal_lookup(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, {
            "has_subscription": True,
            "subscription_url": "https://example.com/sub",
            "plan_name": "Pro",
        })

        result = await client.portal_lookup("test@example.com")

        assert isinstance(result, BillingPortalLookup)
        assert result.has_subscription is True

    async def test_portal_lookup_not_found(self):
        client, mock_http = _make_client_with_mock()
        resp = _make_response(404, text="not found")
        resp.json.return_value = {"error": "not found"}
        mock_http.request.return_value = resp

        result = await client.portal_lookup("unknown@example.com")
        assert result is None

    async def test_get_tg_proxies(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, [
            {"id": 1, "server": "1.2.3.4", "port": 443, "secret": "abc", "link": "tg://proxy"},
        ])

        result = await client.get_tg_proxies(42)

        assert len(result) == 1
        assert isinstance(result[0], BillingTGProxy)
        call_kwargs = mock_http.request.call_args[1]
        assert call_kwargs["params"] == {"plan_id": 42}


# ---------------------------------------------------------------------------
# Client lifecycle
# ---------------------------------------------------------------------------


class TestClientLifecycle:

    async def test_close_client(self):
        client, mock_http = _make_client_with_mock()
        mock_http.aclose = AsyncMock()

        await client.close()

        mock_http.aclose.assert_called_once()

    async def test_close_already_closed_client(self):
        client = BillingClient(BASE_URL, SECRET)
        client._client = None
        # Should not raise
        await client.close()

    async def test_get_client_creates_new_if_none(self):
        client = BillingClient(BASE_URL, SECRET)
        assert client._client is None

        http_client = await client._get_client()

        assert http_client is not None
        assert isinstance(http_client, httpx.AsyncClient)
        # Cleanup
        await http_client.aclose()

    async def test_get_client_creates_new_if_closed(self):
        client, mock_http = _make_client_with_mock()
        mock_http.is_closed = True

        # Should create a new client since the mock says it's closed
        http_client = await client._get_client()

        assert http_client is not None
        # Clean up if real client was created
        if isinstance(http_client, httpx.AsyncClient):
            await http_client.aclose()
