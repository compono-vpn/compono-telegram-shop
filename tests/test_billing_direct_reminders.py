"""Reminder endpoints go straight to billing (compono-api does not proxy them)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx

from src.infrastructure.billing import BillingClient
from src.infrastructure.billing.client import BillingClientError
from src.infrastructure.billing.models import BillingSubscription

API = "http://compono-api-prod:8080"
BILLING = "http://compono-billing-prod:8080"


def _response(payload, status: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.text = "x"
    resp.json.return_value = payload
    return resp


def _client(direct: bool = True):
    client = BillingClient(
        API,
        "api-secret",
        direct_base_url=BILLING if direct else "",
        direct_internal_secret="billing-secret" if direct else "",
    )
    api_http = AsyncMock(spec=httpx.AsyncClient)
    api_http.is_closed = False
    direct_http = AsyncMock(spec=httpx.AsyncClient)
    direct_http.is_closed = False
    client._client = api_http
    client._direct_client = direct_http
    return client, api_http, direct_http


async def test_claim_goes_to_billing_directly_not_through_the_api():
    client, api_http, direct_http = _client()
    direct_http.request.return_value = _response({"claimed": True})

    assert await client.claim_user_reminder(7, "SETUP_24H", "sub-5") is True

    method, url = direct_http.request.call_args[0]
    assert (method, url) == ("POST", f"{BILLING}/api/v1/internal/user-reminders/claim")
    assert direct_http.request.call_args[1]["json"] == {
        "telegram_id": 7,
        "kind": "SETUP_24H",
        "dedup_key": "sub-5",
    }
    api_http.request.assert_not_called()


async def test_second_claim_reports_false():
    client, _, direct_http = _client()
    direct_http.request.return_value = _response({"claimed": False})

    assert await client.claim_user_reminder(7, "SETUP_24H", "sub-5") is False


async def test_answer_release_and_list_use_the_direct_route():
    client, api_http, direct_http = _client()
    direct_http.request.return_value = _response({"updated": True})
    assert await client.answer_user_reminder(7, "SETUP_CHECKIN", "first", "CONNECTED") is True
    direct_http.request.return_value = _response({"released": True})
    assert await client.release_user_reminder(7, "SETUP_24H", "sub-5") is True
    direct_http.request.return_value = _response(
        [{"telegram_id": 7, "kind": "SETUP_CHECKIN", "dedup_key": "first", "answer": "CONNECTED"}]
    )
    rows = await client.list_user_reminders(7, "SETUP_CHECKIN")

    assert rows[0].answer == "CONNECTED"
    urls = [call[0][1] for call in direct_http.request.call_args_list]
    assert urls == [
        f"{BILLING}/api/v1/internal/user-reminders/answer",
        f"{BILLING}/api/v1/internal/user-reminders/release",
        f"{BILLING}/api/v1/internal/user-reminders/7",
    ]
    api_http.request.assert_not_called()


async def test_without_a_direct_address_the_normal_api_path_is_used():
    client, api_http, direct_http = _client(direct=False)
    api_http.request.return_value = _response({"claimed": True})

    assert await client.claim_user_reminder(7, "SETUP_24H", "sub-5") is True

    assert api_http.request.call_args[0][1] == f"{API}/api/v1/internal/user-reminders/claim"
    direct_http.request.assert_not_called()


async def test_expiring_window_is_sent_as_utc_rfc3339():
    client, _, direct_http = _client()
    direct_http.request.return_value = _response(
        [{"ID": 3, "UserTelegramID": 7, "Status": "ACTIVE", "IsTrial": True}]
    )

    rows = await client.list_expiring_subscriptions(
        datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc),
        datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc),
    )

    assert isinstance(rows[0], BillingSubscription)
    assert direct_http.request.call_args[0][1] == f"{BILLING}/api/v1/internal/subscriptions/expiring"
    assert direct_http.request.call_args[1]["params"] == {
        "from": "2026-10-11T10:00:00+00:00",
        "to": "2026-10-11T12:00:00+00:00",
    }


async def test_direct_failures_raise_the_billing_error():
    client, _, direct_http = _client()
    direct_http.request.side_effect = httpx.ConnectError("down")

    try:
        await client.claim_user_reminder(7, "SETUP_24H", "sub-5")
    except BillingClientError as error:
        assert error.status_code == 0
    else:  # pragma: no cover
        raise AssertionError("expected BillingClientError")
