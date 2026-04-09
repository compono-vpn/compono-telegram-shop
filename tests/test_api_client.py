"""Tests for ApiClient and the provisioning orchestration flows.

Verifies:
1. ApiClient.provision_user sends correct request body and parses response
2. Trial flow calls provision_user (not remnawave_service.create_user)
3. New-purchase flow calls provision_user (not remnawave_service.create_user)
4. Failure handling -- API errors propagate correctly, no partial state
5. Contract test -- URL path validation and 404 detection
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import httpx
import pytest

from src.infrastructure.api.client import ApiClient, ApiClientError, ProvisionResult
from src.infrastructure.taskiq.tasks.subscriptions import (
    _handle_new_purchase,
    trial_subscription_task,
)
from tests.conftest import make_plan_snapshot, make_user, unwrap_inject


def unwrap_task(fn):
    """Extract the original async function from taskiq + dishka wrappers.

    taskiq wraps with @broker.task -> AsyncTaskiqDecoratedTask (has .original_func)
    dishka wraps with @inject -> closure containing the real function

    The dishka inject closure's cell contents include the original function,
    but its __name__ differs from the wrapper's __name__ (taskiq appends
    __taskiq_original), so we scan all closure cells for a coroutine function
    that matches the base name.
    """
    # First unwrap taskiq layer
    if hasattr(fn, "original_func"):
        fn = fn.original_func
    # Unwrap dishka inject layer: find the real async function in the closure
    if hasattr(fn, "__closure__") and fn.__closure__:
        import asyncio
        import inspect

        # The base name without taskiq suffix
        base_name = fn.__name__.replace("__taskiq_original", "")
        for cell in fn.__closure__:
            try:
                val = cell.cell_contents
                if (
                    callable(val)
                    and inspect.iscoroutinefunction(val)
                    and getattr(val, "__name__", "") == base_name
                ):
                    return val
            except ValueError:
                pass
    return fn

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_URL = "http://api.test:8080"
SECRET = "test-internal-secret"

_SENTINEL = object()

REMNAWAVE_USER_ID = str(uuid4())
COMPONO_USER_ID = "42"
REMNAWAVE_USERNAME = "shop_1750352084"
SUBSCRIPTION_URL = "https://panel.example.com/sub/abc123"
EXPIRE_AT = "2026-05-07T00:00:00+00:00"


def _make_response(status_code: int = 200, json_data=_SENTINEL, text: str = "") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text or ""
    if json_data is not _SENTINEL:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = Exception("No JSON body")
    return resp


def _make_client_with_mock() -> tuple[ApiClient, AsyncMock]:
    """Return an ApiClient with a mocked httpx.AsyncClient injected."""
    client = ApiClient(BASE_URL, SECRET)
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.is_closed = False
    client._client = mock_http
    return client, mock_http


SAMPLE_PROVISION_RESPONSE = {
    "componoUserId": COMPONO_USER_ID,
    "remnawaveUserId": REMNAWAVE_USER_ID,
    "remnawaveUsername": REMNAWAVE_USERNAME,
    "subscriptionUrl": SUBSCRIPTION_URL,
    "status": "ACTIVE",
    "expireAt": EXPIRE_AT,
}


def _make_provision_result() -> ProvisionResult:
    return ProvisionResult(
        compono_user_id=COMPONO_USER_ID,
        remnawave_user_id=REMNAWAVE_USER_ID,
        remnawave_username=REMNAWAVE_USERNAME,
        subscription_url=SUBSCRIPTION_URL,
        status="ACTIVE",
        expire_at=EXPIRE_AT,
    )


# ---------------------------------------------------------------------------
# 1. ApiClient unit tests
# ---------------------------------------------------------------------------


class TestApiClientProvisionUser:
    """Tests for ApiClient.provision_user: request building and response parsing."""

    async def test_sends_correct_url(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_PROVISION_RESPONSE)
        plan = make_plan_snapshot()

        await client.provision_user(telegram_id=123, plan=plan, name="Test")

        call_args = mock_http.request.call_args
        assert call_args[0] == (
            "POST",
            f"{BASE_URL}/api/v1/internal/provision-user",
        )

    async def test_sends_correct_payload(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_PROVISION_RESPONSE)
        plan = make_plan_snapshot()

        await client.provision_user(
            telegram_id=123,
            plan=plan,
            name="Test User",
            username="testuser",
            language="ru",
        )

        call_args = mock_http.request.call_args
        body = call_args[1]["json"]
        assert body["telegramId"] == 123
        assert body["name"] == "Test User"
        assert body["username"] == "testuser"
        assert body["language"] == "ru"
        assert body["plan"]["name"] == plan.name
        assert body["plan"]["trafficLimit"] == plan.traffic_limit
        assert body["plan"]["deviceLimit"] == plan.device_limit
        assert body["plan"]["durationDays"] == plan.duration
        assert body["plan"]["tag"] == plan.tag
        assert body["plan"]["internalSquads"] == []
        assert body["plan"]["externalSquad"] is None

    async def test_omits_optional_fields_when_none(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_PROVISION_RESPONSE)
        plan = make_plan_snapshot()

        await client.provision_user(telegram_id=123, plan=plan, name="Test")

        call_args = mock_http.request.call_args
        body = call_args[1]["json"]
        assert "username" not in body
        assert "language" not in body

    async def test_parses_response_correctly(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_PROVISION_RESPONSE)
        plan = make_plan_snapshot()

        result = await client.provision_user(telegram_id=123, plan=plan, name="Test")

        assert isinstance(result, ProvisionResult)
        assert result.compono_user_id == COMPONO_USER_ID
        assert result.remnawave_user_id == REMNAWAVE_USER_ID
        assert result.remnawave_username == REMNAWAVE_USERNAME
        assert result.subscription_url == SUBSCRIPTION_URL
        assert result.status == "ACTIVE"
        assert result.expire_at == EXPIRE_AT

    async def test_raises_on_400_error(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(
            400, {"error": "invalid telegram_id"}, text="invalid telegram_id"
        )
        plan = make_plan_snapshot()

        with pytest.raises(ApiClientError) as exc_info:
            await client.provision_user(telegram_id=-1, plan=plan, name="Test")
        assert exc_info.value.status_code == 400

    async def test_raises_on_500_error(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(
            500, {"error": "internal server error"}, text="internal server error"
        )
        plan = make_plan_snapshot()

        with pytest.raises(ApiClientError) as exc_info:
            await client.provision_user(telegram_id=123, plan=plan, name="Test")
        assert exc_info.value.status_code == 500

    async def test_raises_on_network_error(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.side_effect = httpx.ConnectError("Connection refused")
        plan = make_plan_snapshot()

        with pytest.raises(ApiClientError) as exc_info:
            await client.provision_user(telegram_id=123, plan=plan, name="Test")
        assert exc_info.value.status_code == 0

    async def test_uses_internal_secret_header(self):
        client, mock_http = _make_client_with_mock()
        # Verify the client was created with correct headers
        assert client._internal_secret == SECRET
        headers = client._headers()
        assert headers["X-Internal-Secret"] == SECRET


# ---------------------------------------------------------------------------
# 2. Trial flow integration test
# ---------------------------------------------------------------------------


class TestTrialSubscriptionTask:
    """Verify trial_subscription_task uses provision_user, not remnawave_service."""

    async def test_calls_provision_user_not_remnawave(self):
        user = make_user()
        plan = make_plan_snapshot()

        api_client = AsyncMock()
        api_client.provision_user.return_value = _make_provision_result()

        subscription_service = AsyncMock()
        notification_service = AsyncMock()
        redis_client = AsyncMock()
        config = MagicMock()
        config.remnawave.sub_public_domain = "componovpn.com"

        raw_fn = unwrap_task(trial_subscription_task)

        with patch(
            "src.infrastructure.taskiq.tasks.subscriptions.schedule_not_connected_reminder",
            new_callable=AsyncMock,
        ), patch(
            "src.infrastructure.taskiq.tasks.subscriptions.redirect_to_successed_trial_task",
        ) as mock_redirect:
            mock_redirect.kiq = AsyncMock()
            await raw_fn(
                user=user,
                plan=plan,
                skip_redirect=False,
                config=config,
                api_client=api_client,
                subscription_service=subscription_service,
                notification_service=notification_service,
                redis_client=redis_client,
            )

        # provision_user was called exactly once
        api_client.provision_user.assert_called_once()
        call_kwargs = api_client.provision_user.call_args
        assert call_kwargs[1].get("telegram_id") or call_kwargs[0][0] == user.telegram_id

        # subscription_service.create was called
        subscription_service.create.assert_called_once()

    async def test_trial_passes_correct_plan_to_provision(self):
        user = make_user()
        plan = make_plan_snapshot(name="Trial Plan", traffic_limit=50, device_limit=1)

        api_client = AsyncMock()
        api_client.provision_user.return_value = _make_provision_result()

        subscription_service = AsyncMock()
        notification_service = AsyncMock()
        redis_client = AsyncMock()
        config = MagicMock()
        config.remnawave.sub_public_domain = "componovpn.com"

        raw_fn = unwrap_task(trial_subscription_task)

        with patch(
            "src.infrastructure.taskiq.tasks.subscriptions.schedule_not_connected_reminder",
            new_callable=AsyncMock,
        ), patch(
            "src.infrastructure.taskiq.tasks.subscriptions.redirect_to_successed_trial_task",
        ) as mock_redirect:
            mock_redirect.kiq = AsyncMock()
            await raw_fn(
                user=user,
                plan=plan,
                skip_redirect=False,
                config=config,
                api_client=api_client,
                subscription_service=subscription_service,
                notification_service=notification_service,
                redis_client=redis_client,
            )

        call_kwargs = api_client.provision_user.call_args[1]
        assert call_kwargs["telegram_id"] == user.telegram_id
        assert call_kwargs["plan"] is plan
        assert call_kwargs["name"] == user.name

    async def test_trial_builds_subscription_dto_from_result(self):
        user = make_user()
        plan = make_plan_snapshot()

        api_client = AsyncMock()
        api_client.provision_user.return_value = _make_provision_result()

        subscription_service = AsyncMock()
        notification_service = AsyncMock()
        redis_client = AsyncMock()
        config = MagicMock()
        config.remnawave.sub_public_domain = "componovpn.com"

        raw_fn = unwrap_task(trial_subscription_task)

        with patch(
            "src.infrastructure.taskiq.tasks.subscriptions.schedule_not_connected_reminder",
            new_callable=AsyncMock,
        ), patch(
            "src.infrastructure.taskiq.tasks.subscriptions.redirect_to_successed_trial_task",
        ) as mock_redirect:
            mock_redirect.kiq = AsyncMock()
            await raw_fn(
                user=user,
                plan=plan,
                skip_redirect=False,
                config=config,
                api_client=api_client,
                subscription_service=subscription_service,
                notification_service=notification_service,
                redis_client=redis_client,
            )

        created_sub = subscription_service.create.call_args[0][1]
        assert created_sub.user_remna_id == UUID(REMNAWAVE_USER_ID)
        assert created_sub.url == SUBSCRIPTION_URL
        assert created_sub.is_trial is True
        assert created_sub.plan is plan


# ---------------------------------------------------------------------------
# 3. New-purchase flow integration test
# ---------------------------------------------------------------------------


class TestHandleNewPurchase:
    """Verify _handle_new_purchase uses provision_user, not remnawave_service."""

    async def test_calls_provision_user_not_remnawave(self):
        user = make_user()
        plan = make_plan_snapshot()

        api_client = AsyncMock()
        api_client.provision_user.return_value = _make_provision_result()

        subscription_service = AsyncMock()

        await _handle_new_purchase(
            user=user,
            plan=plan,
            api_client=api_client,
            subscription_service=subscription_service,
        )

        api_client.provision_user.assert_called_once()
        subscription_service.create.assert_called_once()

    async def test_builds_subscription_dto_from_result(self):
        user = make_user()
        plan = make_plan_snapshot()

        api_client = AsyncMock()
        api_client.provision_user.return_value = _make_provision_result()

        subscription_service = AsyncMock()

        await _handle_new_purchase(
            user=user,
            plan=plan,
            api_client=api_client,
            subscription_service=subscription_service,
        )

        created_sub = subscription_service.create.call_args[0][1]
        assert created_sub.user_remna_id == UUID(REMNAWAVE_USER_ID)
        assert created_sub.url == SUBSCRIPTION_URL
        assert created_sub.is_trial is False
        assert created_sub.plan is plan

    async def test_propagates_api_error(self):
        user = make_user()
        plan = make_plan_snapshot()

        api_client = AsyncMock()
        api_client.provision_user.side_effect = ApiClientError(500, "internal error")

        subscription_service = AsyncMock()

        with pytest.raises(ApiClientError):
            await _handle_new_purchase(
                user=user,
                plan=plan,
                api_client=api_client,
                subscription_service=subscription_service,
            )

        # No subscription created on failure
        subscription_service.create.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Failure handling test
# ---------------------------------------------------------------------------


class TestFailureHandling:
    """Verify errors propagate correctly with no partial state."""

    async def test_trial_api_error_triggers_error_notify(self):
        user = make_user()
        plan = make_plan_snapshot()

        api_client = AsyncMock()
        api_client.provision_user.side_effect = ApiClientError(500, "internal error")

        subscription_service = AsyncMock()
        notification_service = AsyncMock()
        redis_client = AsyncMock()
        config = MagicMock()

        raw_fn = unwrap_task(trial_subscription_task)

        with patch(
            "src.infrastructure.taskiq.tasks.subscriptions.redirect_to_failed_subscription_task",
        ) as mock_redirect:
            mock_redirect.kiq = AsyncMock()
            await raw_fn(
                user=user,
                plan=plan,
                skip_redirect=False,
                config=config,
                api_client=api_client,
                subscription_service=subscription_service,
                notification_service=notification_service,
                redis_client=redis_client,
            )

        # No subscription created
        subscription_service.create.assert_not_called()

        # Error notification sent
        notification_service.error_notify.assert_called_once()

        # Redirect to failed task
        mock_redirect.kiq.assert_called_once()

    async def test_trial_api_error_skips_redirect_when_flagged(self):
        user = make_user()
        plan = make_plan_snapshot()

        api_client = AsyncMock()
        api_client.provision_user.side_effect = ApiClientError(500, "internal error")

        subscription_service = AsyncMock()
        notification_service = AsyncMock()
        redis_client = AsyncMock()
        config = MagicMock()

        raw_fn = unwrap_task(trial_subscription_task)

        with patch(
            "src.infrastructure.taskiq.tasks.subscriptions.redirect_to_failed_subscription_task",
        ) as mock_redirect:
            mock_redirect.kiq = AsyncMock()
            await raw_fn(
                user=user,
                plan=plan,
                skip_redirect=True,
                config=config,
                api_client=api_client,
                subscription_service=subscription_service,
                notification_service=notification_service,
                redis_client=redis_client,
            )

        # Error notification sent
        notification_service.error_notify.assert_called_once()

        # No redirect to failed when skip_redirect=True
        mock_redirect.kiq.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Contract test -- URL path validation
# ---------------------------------------------------------------------------


class TestContractValidation:
    """Verify the expected API path is hit and 404 is detected."""

    async def test_provision_user_url_path(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_PROVISION_RESPONSE)
        plan = make_plan_snapshot()

        await client.provision_user(telegram_id=123, plan=plan, name="Test")

        url = mock_http.request.call_args[0][1]
        assert url == f"{BASE_URL}/api/v1/internal/provision-user"

    async def test_404_raises_client_error(self):
        """If the API returns 404, the client must fail-fast (not silently ignore)."""
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(
            404, {"error": "Not Found"}, text="Not Found"
        )
        plan = make_plan_snapshot()

        with pytest.raises(ApiClientError) as exc_info:
            await client.provision_user(telegram_id=123, plan=plan, name="Test")

        assert exc_info.value.status_code == 404
        assert "Not Found" in exc_info.value.message

    async def test_409_conflict_raises_client_error(self):
        """If the API returns 409 (user already exists), it should raise."""
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(
            409, {"error": "user already exists"}, text="user already exists"
        )
        plan = make_plan_snapshot()

        with pytest.raises(ApiClientError) as exc_info:
            await client.provision_user(telegram_id=123, plan=plan, name="Test")

        assert exc_info.value.status_code == 409

    async def test_base_path_construction(self):
        """Verify base URL trailing slash handling."""
        client1 = ApiClient("http://api.test:8080/", SECRET)
        assert client1._base_path == "http://api.test:8080/api/v1/internal"

        client2 = ApiClient("http://api.test:8080", SECRET)
        assert client2._base_path == "http://api.test:8080/api/v1/internal"
