"""Tests for ApiIdentityClient -- verifies HTTP calls, URL paths, and error handling.

These tests would have caught the original outage where a missing proxy route
caused 404 errors. They verify:
1. Correct URL path construction
2. Correct payload serialization
3. Fail-fast on 404 (not silent failure)
4. Integration with trial and purchase flows
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest

from src.infrastructure.api.identity_client import ApiIdentityClient, ApiIdentityClientError
from src.infrastructure.taskiq.tasks.subscriptions import (
    _handle_new_purchase,
    trial_subscription_task,
)
from tests.conftest import make_plan_snapshot, make_user

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_URL = "http://api.test:8080"
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


def _make_client_with_mock() -> tuple[ApiIdentityClient, AsyncMock]:
    """Return an ApiIdentityClient with a mocked httpx.AsyncClient injected."""
    client = ApiIdentityClient(BASE_URL, SECRET)
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.is_closed = False
    client._client = mock_http
    return client, mock_http


SAMPLE_COMPONO_USER = {
    "id": 1,
    "telegram_id": 123456789,
    "remnawave_user_id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "Test User",
    "username": "testuser",
    "language": "en",
    "created_at": "2025-01-01T00:00:00Z",
    "updated_at": "2025-06-01T00:00:00Z",
}


# ---------------------------------------------------------------------------
# _request internals
# ---------------------------------------------------------------------------


class TestRequestInternals:
    """Tests for the _request method: URL construction, headers, error handling."""

    async def test_constructs_correct_url(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, {"ok": True})

        await client._request("POST", "/compono-users/ensure-with-linkage")

        call_args = mock_http.request.call_args
        assert call_args[0] == (
            "POST",
            f"{BASE_URL}/api/v1/internal/compono-users/ensure-with-linkage",
        )

    async def test_passes_json_body(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_COMPONO_USER)

        body = {"telegram_id": 123, "remnawave_user_id": "uuid-string"}
        await client._request("POST", "/compono-users/ensure-with-linkage", json=body)

        call_args = mock_http.request.call_args
        assert call_args[1]["json"] == body

    async def test_returns_none_on_204(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(204)

        result = await client._request("POST", "/some-path")
        assert result is None

    async def test_raises_error_on_4xx(self):
        client, mock_http = _make_client_with_mock()
        resp = _make_response(400, json_data={"error": "invalid input"}, text="bad request")
        mock_http.request.return_value = resp

        with pytest.raises(ApiIdentityClientError) as exc_info:
            await client._request("POST", "/compono-users/ensure-with-linkage")
        assert exc_info.value.status_code == 400
        assert "invalid input" in exc_info.value.message

    async def test_raises_error_on_500(self):
        client, mock_http = _make_client_with_mock()
        resp = _make_response(500, text="internal error")
        resp.json.side_effect = Exception("not json")
        mock_http.request.return_value = resp

        with pytest.raises(ApiIdentityClientError) as exc_info:
            await client._request("POST", "/compono-users/ensure-with-linkage")
        assert exc_info.value.status_code == 500

    async def test_raises_error_on_http_error(self):
        client, mock_http = _make_client_with_mock()
        mock_http.request.side_effect = httpx.ConnectError("connection refused")

        with pytest.raises(ApiIdentityClientError) as exc_info:
            await client._request("POST", "/compono-users/ensure-with-linkage")
        assert exc_info.value.status_code == 0
        assert "connection refused" in exc_info.value.message

    async def test_headers_include_internal_secret(self):
        client = ApiIdentityClient(BASE_URL, SECRET)
        headers = client._headers()
        assert headers["X-Internal-Secret"] == SECRET
        assert headers["Content-Type"] == "application/json"

    async def test_base_path(self):
        client = ApiIdentityClient(BASE_URL, SECRET)
        assert client._base_path == f"{BASE_URL}/api/v1/internal"

    async def test_base_url_trailing_slash_stripped(self):
        client = ApiIdentityClient(f"{BASE_URL}/", SECRET)
        assert client._base_path == f"{BASE_URL}/api/v1/internal"


# ---------------------------------------------------------------------------
# ensure_with_linkage -- contract-level tests
# ---------------------------------------------------------------------------


class TestEnsureWithLinkage:
    """Tests for the ensure_with_linkage method."""

    async def test_calls_correct_endpoint(self):
        """Contract test: verify the exact URL path is correct."""
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_COMPONO_USER)

        await client.ensure_with_linkage(
            telegram_id=123456789,
            remnawave_user_id="550e8400-e29b-41d4-a716-446655440000",
        )

        call_args = mock_http.request.call_args
        assert call_args[0] == (
            "POST",
            f"{BASE_URL}/api/v1/internal/compono-users/ensure-with-linkage",
        )

    async def test_sends_required_fields(self):
        """Verify minimal required payload is sent correctly."""
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_COMPONO_USER)

        await client.ensure_with_linkage(
            telegram_id=123456789,
            remnawave_user_id="uuid-string",
        )

        call_args = mock_http.request.call_args
        assert call_args[1]["json"] == {
            "telegram_id": 123456789,
            "remnawave_user_id": "uuid-string",
        }

    async def test_sends_optional_fields_when_provided(self):
        """Verify optional fields are included when set."""
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_COMPONO_USER)

        await client.ensure_with_linkage(
            telegram_id=123456789,
            remnawave_user_id="uuid-string",
            name="Test User",
            username="testuser",
            language="en",
        )

        call_args = mock_http.request.call_args
        assert call_args[1]["json"] == {
            "telegram_id": 123456789,
            "remnawave_user_id": "uuid-string",
            "name": "Test User",
            "username": "testuser",
            "language": "en",
        }

    async def test_omits_optional_fields_when_none(self):
        """Verify None optional fields are not sent."""
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_COMPONO_USER)

        await client.ensure_with_linkage(
            telegram_id=123456789,
            remnawave_user_id="uuid-string",
        )

        payload = mock_http.request.call_args[1]["json"]
        assert "name" not in payload
        assert "username" not in payload
        assert "language" not in payload

    async def test_returns_compono_user_data(self):
        """Verify the response is returned as dict."""
        client, mock_http = _make_client_with_mock()
        mock_http.request.return_value = _make_response(200, SAMPLE_COMPONO_USER)

        result = await client.ensure_with_linkage(
            telegram_id=123456789,
            remnawave_user_id="uuid-string",
        )

        assert result == SAMPLE_COMPONO_USER


# ---------------------------------------------------------------------------
# Fail-fast on 404 -- catches missing proxy route
# ---------------------------------------------------------------------------


class TestFailFastOn404:
    """Test that the client raises a clear error on 404, not a silent failure.

    This test class specifically catches the outage scenario where the API
    endpoint doesn't exist (missing proxy route).
    """

    async def test_404_raises_with_clear_error(self):
        """A 404 must raise ApiIdentityClientError, not return None or silently fail."""
        client, mock_http = _make_client_with_mock()
        resp = _make_response(404, json_data={"error": "Not Found"}, text="Not Found")
        mock_http.request.return_value = resp

        with pytest.raises(ApiIdentityClientError) as exc_info:
            await client.ensure_with_linkage(
                telegram_id=123456789,
                remnawave_user_id="uuid-string",
            )

        assert exc_info.value.status_code == 404
        assert "Not Found" in exc_info.value.message

    async def test_404_error_message_is_descriptive(self):
        """Error string should include status code for debugging."""
        client, mock_http = _make_client_with_mock()
        resp = _make_response(404, text="page not found")
        resp.json.side_effect = Exception("not json")
        mock_http.request.return_value = resp

        with pytest.raises(ApiIdentityClientError) as exc_info:
            await client.ensure_with_linkage(
                telegram_id=123456789,
                remnawave_user_id="uuid-string",
            )

        error = exc_info.value
        assert error.status_code == 404
        assert "404" in str(error)
        assert "page not found" in error.message


# ---------------------------------------------------------------------------
# Integration: trial flow calls ensure_with_linkage correctly
# ---------------------------------------------------------------------------


def _unwrap_taskiq_inject(task):
    """Extract the real async function from @broker.task + @inject wrappers.

    taskiq wraps with AsyncTaskiqDecoratedTask (has .original_func).
    dishka @inject wraps the original function in a closure. The real function
    lives in the closure with its __module__ pointing to the original source module
    (not dishka.integrations.base).
    """
    fn = task.original_func  # dishka-wrapped function
    if fn.__closure__:
        for cell in reversed(fn.__closure__):
            try:
                val = cell.cell_contents
                if (
                    callable(val)
                    and hasattr(val, "__module__")
                    and val.__module__ != fn.__module__
                ):
                    return val
            except ValueError:
                pass
    return fn


class TestTrialFlowIntegration:
    """Verify the trial flow calls ensure_with_linkage with correct args.

    Since trial_subscription_task is wrapped by both @broker.task and @inject,
    we unwrap through both layers to call the real function directly.
    """

    async def test_trial_task_calls_ensure_with_linkage(self):
        """Mock the full trial task flow and verify ensure_with_linkage is called."""
        user = make_user(telegram_id=777888999)
        plan = make_plan_snapshot()
        remna_uuid = uuid4()

        # Mock dependencies
        api_identity = AsyncMock(spec=ApiIdentityClient)
        api_identity.ensure_with_linkage.return_value = SAMPLE_COMPONO_USER

        remnawave_service = AsyncMock()
        created_user = MagicMock()
        created_user.uuid = remna_uuid
        created_user.username = "remna_user"
        created_user.subscription_url = "https://panel.example.com/sub/abc"
        created_user.status = "ACTIVE"
        created_user.expire_at = "2026-12-01T00:00:00Z"
        remnawave_service.create_user.return_value = created_user

        subscription_service = AsyncMock()
        notification_service = AsyncMock()
        redis_client = AsyncMock()
        config = MagicMock()
        config.remnawave.sub_public_domain = "componovpn.com"

        fn = _unwrap_taskiq_inject(trial_subscription_task)
        await fn(
            user,
            plan,
            True,  # skip_redirect
            config,
            api_identity,
            remnawave_service,
            subscription_service,
            notification_service,
            redis_client,
        )

        # Verify ensure_with_linkage was called with correct args
        api_identity.ensure_with_linkage.assert_called_once_with(
            telegram_id=777888999,
            remnawave_user_id=str(remna_uuid),
        )

    async def test_trial_task_does_not_call_billing_customer_bridge(self):
        """Ensure the old billing customer bridge calls are no longer made.

        The api_identity mock is created with spec=ApiIdentityClient which
        means it only has methods defined on ApiIdentityClient. Calling
        billing-specific methods would raise AttributeError.
        """
        user = make_user(telegram_id=777888999)
        plan = make_plan_snapshot()
        remna_uuid = uuid4()

        api_identity = AsyncMock(spec=ApiIdentityClient)
        api_identity.ensure_with_linkage.return_value = SAMPLE_COMPONO_USER

        remnawave_service = AsyncMock()
        created_user = MagicMock()
        created_user.uuid = remna_uuid
        created_user.username = "remna_user"
        created_user.subscription_url = "https://panel.example.com/sub/abc"
        created_user.status = "ACTIVE"
        created_user.expire_at = "2026-12-01T00:00:00Z"
        remnawave_service.create_user.return_value = created_user

        subscription_service = AsyncMock()
        notification_service = AsyncMock()
        redis_client = AsyncMock()
        config = MagicMock()
        config.remnawave.sub_public_domain = "componovpn.com"

        fn = _unwrap_taskiq_inject(trial_subscription_task)
        await fn(
            user,
            plan,
            True,
            config,
            api_identity,
            remnawave_service,
            subscription_service,
            notification_service,
            redis_client,
        )

        # These old billing methods must NOT exist on the api_identity mock (spec enforced)
        assert not hasattr(api_identity, "get_or_create_customer_by_telegram_id")
        assert not hasattr(api_identity, "update_customer")
        assert not hasattr(api_identity, "update_user")


# ---------------------------------------------------------------------------
# Integration: purchase flow calls ensure_with_linkage correctly
# ---------------------------------------------------------------------------


class TestPurchaseFlowIntegration:
    """Verify _handle_new_purchase calls ensure_with_linkage with correct args."""

    async def test_new_purchase_calls_ensure_with_linkage(self):
        """Mock the new purchase flow and verify ensure_with_linkage is called."""
        user = make_user(telegram_id=111222333)
        plan = make_plan_snapshot()
        remna_uuid = uuid4()

        api_identity = AsyncMock(spec=ApiIdentityClient)
        api_identity.ensure_with_linkage.return_value = SAMPLE_COMPONO_USER

        remnawave_service = AsyncMock()
        created_user = MagicMock()
        created_user.uuid = remna_uuid
        created_user.username = "remna_user"
        created_user.subscription_url = "https://panel.example.com/sub/def"
        created_user.status = "ACTIVE"
        created_user.expire_at = "2026-12-01T00:00:00Z"
        remnawave_service.create_user.return_value = created_user

        subscription_service = AsyncMock()

        await _handle_new_purchase(
            user,
            plan,
            api_identity,
            remnawave_service,
            subscription_service,
        )

        # Verify ensure_with_linkage was called with correct args
        api_identity.ensure_with_linkage.assert_called_once_with(
            telegram_id=111222333,
            remnawave_user_id=str(remna_uuid),
        )

    async def test_new_purchase_creates_subscription_after_linkage(self):
        """Verify subscription is created after identity linkage succeeds."""
        user = make_user(telegram_id=111222333)
        plan = make_plan_snapshot()
        remna_uuid = uuid4()

        api_identity = AsyncMock(spec=ApiIdentityClient)
        api_identity.ensure_with_linkage.return_value = SAMPLE_COMPONO_USER

        remnawave_service = AsyncMock()
        created_user = MagicMock()
        created_user.uuid = remna_uuid
        created_user.username = "remna_user"
        created_user.subscription_url = "https://panel.example.com/sub/def"
        created_user.status = "ACTIVE"
        created_user.expire_at = "2026-12-01T00:00:00Z"
        remnawave_service.create_user.return_value = created_user

        subscription_service = AsyncMock()

        await _handle_new_purchase(
            user,
            plan,
            api_identity,
            remnawave_service,
            subscription_service,
        )

        # Subscription must be created
        subscription_service.create.assert_called_once()

    async def test_new_purchase_propagates_linkage_error(self):
        """If ensure_with_linkage fails, the error must propagate (fail-fast)."""
        user = make_user(telegram_id=111222333)
        plan = make_plan_snapshot()

        api_identity = AsyncMock(spec=ApiIdentityClient)
        api_identity.ensure_with_linkage.side_effect = ApiIdentityClientError(
            404, "Not Found"
        )

        remnawave_service = AsyncMock()
        created_user = MagicMock()
        created_user.uuid = uuid4()
        created_user.username = "remna_user"
        created_user.subscription_url = "https://panel.example.com/sub/def"
        created_user.status = "ACTIVE"
        created_user.expire_at = "2026-12-01T00:00:00Z"
        remnawave_service.create_user.return_value = created_user

        subscription_service = AsyncMock()

        with pytest.raises(ApiIdentityClientError) as exc_info:
            await _handle_new_purchase(
                user,
                plan,
                api_identity,
                remnawave_service,
                subscription_service,
            )

        assert exc_info.value.status_code == 404
        # Subscription must NOT be created if linkage failed
        subscription_service.create.assert_not_called()
