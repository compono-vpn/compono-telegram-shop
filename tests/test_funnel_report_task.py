"""Tests for the daily funnel report scheduled task (09:00 MSK / cron 0 6 * * *).

Covers:
1. compute_msk_previous_day_window -- pure helper, boundary cases (midday,
   just-after-midnight MSK, naive vs aware `now`, correct fixed UTC+3 offset
   without hand-rolled DST assumptions).
2. BillingClient.get_funnel_stats / ApiClient.get_connected_stats -- request
   shape (URL, query params) and response parsing, via the same injected-mock
   httpx.AsyncClient pattern as test_billing_client.py / test_api_client.py.
3. _build_funnel_report_text / send_daily_funnel_report -- the task's core
   logic tested as plain functions (not through @broker.task/@inject), success
   and failure paths, mocking the two API clients.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import httpx
import pytest

from src.core.utils.time import MSK, compute_msk_previous_day_window, to_rfc3339_utc
from src.infrastructure.api.client import (
    ApiClient,
    ConnectedActivityStats,
    ConnectedStats,
    ProfileRequesterStats,
)
from src.infrastructure.billing.client import BillingClient
from src.infrastructure.billing.models import BillingFunnelStats
from src.infrastructure.taskiq.tasks.funnel_report import (
    _build_funnel_report_text,
    send_daily_funnel_report,
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


def _make_billing_client_with_mock() -> tuple[BillingClient, AsyncMock]:
    client = BillingClient(BASE_URL, SECRET)
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.is_closed = False
    client._client = mock_http
    return client, mock_http


def _make_api_client_with_mock() -> tuple[ApiClient, AsyncMock]:
    client = ApiClient(BASE_URL, SECRET)
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.is_closed = False
    client._client = mock_http
    return client, mock_http


# ---------------------------------------------------------------------------
# 1. compute_msk_previous_day_window
# ---------------------------------------------------------------------------


class TestComputeMskPreviousDayWindow:
    def test_midday_msk_reports_previous_calendar_day(self):
        now = datetime(2026, 7, 24, 14, 30, tzinfo=MSK)

        start, end = compute_msk_previous_day_window(now)

        assert start == datetime(2026, 7, 22, 21, 0, tzinfo=timezone.utc)
        assert end == datetime(2026, 7, 23, 21, 0, tzinfo=timezone.utc)

    def test_just_after_midnight_msk_still_reports_previous_full_day(self):
        # 00:01 MSK on the 24th -- the previous *full* day is the 23rd, not
        # the tiny sliver of the 24th that has already elapsed.
        now = datetime(2026, 7, 24, 0, 1, tzinfo=MSK)

        start, end = compute_msk_previous_day_window(now)

        assert start == datetime(2026, 7, 22, 21, 0, tzinfo=timezone.utc)
        assert end == datetime(2026, 7, 23, 21, 0, tzinfo=timezone.utc)

    def test_exact_9am_msk_fire_time_reports_yesterday(self):
        now = datetime(2026, 7, 24, 9, 0, tzinfo=MSK)

        start, end = compute_msk_previous_day_window(now)

        assert start.astimezone(MSK).date().isoformat() == "2026-07-23"
        assert end.astimezone(MSK).date().isoformat() == "2026-07-24"

    def test_window_is_exactly_24_hours(self):
        now = datetime(2026, 7, 24, 9, 0, tzinfo=MSK)

        start, end = compute_msk_previous_day_window(now)

        assert end - start == timedelta(hours=24)

    def test_bounds_are_utc(self):
        now = datetime(2026, 7, 24, 9, 0, tzinfo=MSK)

        start, end = compute_msk_previous_day_window(now)

        assert start.tzinfo == timezone.utc
        assert end.tzinfo == timezone.utc

    def test_naive_now_is_treated_as_already_msk(self):
        naive_now = datetime(2026, 7, 24, 9, 0)  # noqa: DTZ001 - intentional naive-input test
        aware_now = datetime(2026, 7, 24, 9, 0, tzinfo=MSK)

        assert compute_msk_previous_day_window(naive_now) == compute_msk_previous_day_window(
            aware_now
        )

    def test_aware_now_in_other_timezone_is_converted_to_msk(self):
        # 23:30 UTC on the 23rd is 02:30 MSK on the 24th -- previous full
        # MSK day must be the 23rd, not the 22nd.
        now_utc = datetime(2026, 7, 23, 23, 30, tzinfo=timezone.utc)

        start, end = compute_msk_previous_day_window(now_utc)

        assert start.astimezone(MSK).date().isoformat() == "2026-07-23"
        assert end.astimezone(MSK).date().isoformat() == "2026-07-24"

    def test_no_dst_offset_stays_utc_plus_3_year_round(self):
        # MSK has had no DST since 2014 -- a hand-rolled fixed UTC+3 offset
        # would happen to "work" for MSK specifically, but this asserts the
        # real ZoneInfo-derived offset is used and is stable across a summer
        # and a winter date (would differ for a DST-observing zone).
        summer = compute_msk_previous_day_window(datetime(2026, 7, 24, 9, 0, tzinfo=MSK))
        winter = compute_msk_previous_day_window(datetime(2026, 1, 24, 9, 0, tzinfo=MSK))

        for start, end in (summer, winter):
            msk_start = start.astimezone(MSK)
            msk_end = end.astimezone(MSK)
            assert msk_start.utcoffset() == timedelta(hours=3)
            assert msk_end.utcoffset() == timedelta(hours=3)
            assert msk_start.time().isoformat() == "00:00:00"
            assert msk_end.time().isoformat() == "00:00:00"

    def test_defaults_to_real_now_when_omitted(self):
        before = datetime.now(tz=MSK)
        start, end = compute_msk_previous_day_window()
        after = datetime.now(tz=MSK)

        assert end - start == timedelta(hours=24)
        # The window's end must be "today at 00:00 MSK" relative to whenever
        # the call actually ran.
        assert end.astimezone(MSK).date() in {before.date(), after.date()}

    def test_zoneinfo_is_actually_europe_moscow(self):
        assert isinstance(MSK, ZoneInfo)
        assert str(MSK) == "Europe/Moscow"


class TestToRfc3339Utc:
    def test_formats_utc_datetime(self):
        dt = datetime(2026, 7, 23, 0, 0, tzinfo=timezone.utc)
        assert to_rfc3339_utc(dt) == "2026-07-23T00:00:00+00:00"

    def test_converts_non_utc_aware_datetime(self):
        dt = datetime(2026, 7, 23, 3, 0, tzinfo=MSK)
        assert to_rfc3339_utc(dt) == "2026-07-23T00:00:00+00:00"

    def test_naive_datetime_is_assumed_utc(self):
        dt = datetime(2026, 7, 23, 0, 0)  # noqa: DTZ001 - intentional naive-input test
        assert to_rfc3339_utc(dt) == "2026-07-23T00:00:00+00:00"


# ---------------------------------------------------------------------------
# 2. BillingClient.get_funnel_stats / ApiClient.get_connected_stats
# ---------------------------------------------------------------------------


class TestBillingClientGetFunnelStats:
    async def test_sends_correct_url_and_params(self):
        client, mock_http = _make_billing_client_with_mock()
        mock_http.request.return_value = _make_response(
            200, {"new_users": 5, "used_trial": 3, "bought_sub": 1}
        )
        date_from = datetime(2026, 7, 23, tzinfo=timezone.utc)
        date_to = datetime(2026, 7, 24, tzinfo=timezone.utc)

        await client.get_funnel_stats(date_from, date_to)

        call_args = mock_http.request.call_args
        assert call_args[0] == ("GET", f"{BASE_URL}/api/v1/internal/stats/funnel")
        assert call_args[1]["params"] == {
            "from": "2026-07-23T00:00:00+00:00",
            "to": "2026-07-24T00:00:00+00:00",
        }

    async def test_parses_response(self):
        client, mock_http = _make_billing_client_with_mock()
        mock_http.request.return_value = _make_response(
            200, {"new_users": 5, "used_trial": 3, "bought_sub": 1}
        )

        result = await client.get_funnel_stats(
            datetime(2026, 7, 23, tzinfo=timezone.utc),
            datetime(2026, 7, 24, tzinfo=timezone.utc),
        )

        assert isinstance(result, BillingFunnelStats)
        assert result.new_users == 5
        assert result.used_trial == 3
        assert result.bought_sub == 1


class TestApiClientGetConnectedStats:
    async def test_sends_correct_url_and_params(self):
        client, mock_http = _make_api_client_with_mock()
        mock_http.request.return_value = _make_response(200, {"connected": 7})
        date_from = datetime(2026, 7, 23, tzinfo=timezone.utc)
        date_to = datetime(2026, 7, 24, tzinfo=timezone.utc)

        await client.get_connected_stats(date_from, date_to)

        call_args = mock_http.request.call_args
        assert call_args[0] == ("GET", f"{BASE_URL}/api/v1/internal/stats/connected")
        assert call_args[1]["params"] == {
            "from": "2026-07-23T00:00:00+00:00",
            "to": "2026-07-24T00:00:00+00:00",
        }

    async def test_parses_response(self):
        client, mock_http = _make_api_client_with_mock()
        mock_http.request.return_value = _make_response(200, {"connected": 7})

        result = await client.get_connected_stats(
            datetime(2026, 7, 23, tzinfo=timezone.utc),
            datetime(2026, 7, 24, tzinfo=timezone.utc),
        )

        assert isinstance(result, ConnectedStats)
        assert result.connected == 7


# ---------------------------------------------------------------------------
# 3. Task logic: _build_funnel_report_text / send_daily_funnel_report
# ---------------------------------------------------------------------------


def _make_billing(funnel_stats: BillingFunnelStats | None = None, error: Exception | None = None):
    billing = AsyncMock()
    if error:
        billing.get_funnel_stats.side_effect = error
    else:
        billing.get_funnel_stats.return_value = funnel_stats or BillingFunnelStats(
            new_users=10, used_trial=4, bought_sub=2
        )
    return billing


def _activity(**overrides) -> ConnectedActivityStats:
    values = dict(
        connected_users=5,
        scope="exit_attributable",
        not_observed=("relay_whitelist",),
        since=datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc),
        covers_range=True,
        fresh=True,
        nodes_total=8,
        nodes_fresh=8,
        oldest_apply_ok_at=datetime(2026, 10, 10, 5, 59, 40, tzinfo=timezone.utc),
    )
    values.update(overrides)
    return ConnectedActivityStats(**values)


def _make_api_client(connected: ConnectedStats | None = None, error: Exception | None = None):
    api_client = AsyncMock()
    if error:
        api_client.get_connected_stats.side_effect = error
    else:
        api_client.get_connected_stats.return_value = connected or ConnectedStats(connected=6)
    api_client.get_profile_requester_stats.return_value = ProfileRequesterStats(
        profile_requesters=8
    )
    api_client.get_connected_activity.return_value = _activity()
    return api_client


class TestBuildFunnelReportText:
    async def test_builds_expected_plain_text_report(self):
        billing = _make_billing(BillingFunnelStats(new_users=10, used_trial=4, bought_sub=2))
        api_client = _make_api_client(ConnectedStats(connected=6))
        now = datetime(2026, 7, 24, 9, 0, tzinfo=MSK)

        text = await _build_funnel_report_text(billing, api_client, now)

        assert "📊 Daily activity — 2026-07-23" in text
        assert "New users: 10" in text
        assert "Used trial: 4" in text
        assert "Last seen on VPN that day: 6" in text
        assert "Paid purchases: 2" in text
        assert "Profile requesters: 8" in text
        assert "not a signup cohort" in text
        assert "refreshes and failures" in text
        assert "can decrease after later activity" in text

    async def test_queries_both_apis_with_the_same_previous_day_window(self):
        billing = _make_billing()
        api_client = _make_api_client()
        now = datetime(2026, 7, 24, 9, 0, tzinfo=MSK)

        await _build_funnel_report_text(billing, api_client, now)

        expected_start, expected_end = compute_msk_previous_day_window(now)
        billing.get_funnel_stats.assert_awaited_once_with(expected_start, expected_end)
        api_client.get_connected_stats.assert_awaited_once_with(expected_start, expected_end)
        api_client.get_profile_requester_stats.assert_awaited_once_with(
            expected_start, expected_end
        )


class TestSendDailyFunnelReport:
    async def test_success_sends_plain_text_to_dev_chat(self):
        config = MagicMock()
        config.bot.dev_id = 1750352084
        billing = _make_billing(BillingFunnelStats(new_users=10, used_trial=4, bought_sub=2))
        api_client = _make_api_client(ConnectedStats(connected=6))
        notification_service = AsyncMock()
        now = datetime(2026, 7, 24, 9, 0, tzinfo=MSK)

        await send_daily_funnel_report(config, billing, api_client, notification_service, now)

        notification_service.bot.send_message.assert_awaited_once()
        call_kwargs = notification_service.bot.send_message.await_args.kwargs
        assert call_kwargs["chat_id"] == 1750352084
        assert "New users: 10" in call_kwargs["text"]
        assert "Used trial: 4" in call_kwargs["text"]
        assert "Last seen on VPN that day: 6" in call_kwargs["text"]
        assert "Paid purchases: 2" in call_kwargs["text"]

        notification_service.error_notify.assert_not_awaited()

    async def test_billing_failure_routes_through_error_notify_not_silently_dropped(self):
        config = MagicMock()
        config.bot.dev_id = 1750352084
        billing = _make_billing(error=RuntimeError("billing unreachable"))
        api_client = _make_api_client()
        notification_service = AsyncMock()
        now = datetime(2026, 7, 24, 9, 0, tzinfo=MSK)

        await send_daily_funnel_report(config, billing, api_client, notification_service, now)

        notification_service.error_notify.assert_awaited_once()
        error_call = notification_service.error_notify.await_args
        assert "billing unreachable" in error_call.kwargs["traceback_str"]
        payload = error_call.kwargs["payload"]
        assert payload.i18n_key == "ntf-event-error"

        notification_service.bot.send_message.assert_not_awaited()

    async def test_api_client_failure_routes_through_error_notify_not_silently_dropped(self):
        config = MagicMock()
        config.bot.dev_id = 1750352084
        billing = _make_billing()
        api_client = _make_api_client(error=RuntimeError("compono-api unreachable"))
        notification_service = AsyncMock()
        now = datetime(2026, 7, 24, 9, 0, tzinfo=MSK)

        await send_daily_funnel_report(config, billing, api_client, notification_service, now)

        notification_service.error_notify.assert_awaited_once()
        error_call = notification_service.error_notify.await_args
        assert "compono-api unreachable" in error_call.kwargs["traceback_str"]

        notification_service.bot.send_message.assert_not_awaited()


class TestProfileRequesterStats:
    async def test_request_and_count(self):
        client, transport = _make_api_client_with_mock()
        transport.request.return_value = _make_response(200, {"profile_requesters": 8})
        start = datetime(2026, 10, 9, tzinfo=MSK)
        end = start + timedelta(days=1)
        stats = await client.get_profile_requester_stats(start, end)
        assert stats.profile_requesters == 8
        args = transport.request.call_args
        assert args.args == ("GET", f"{BASE_URL}/api/v1/internal/stats/profile-requesters")
        assert args.kwargs["params"] == {
            "from": "2026-10-08T21:00:00+00:00",
            "to": "2026-10-09T21:00:00+00:00",
        }

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            None,
            {"profile_requesters": -1},
            {"profile_requesters": "8"},
            {"profile_requesters": True},
        ],
    )
    async def test_malformed_counter_is_not_silent_zero(self, payload):
        client, transport = _make_api_client_with_mock()
        transport.request.return_value = _make_response(200, payload)
        now = datetime(2026, 10, 9, tzinfo=timezone.utc)
        with pytest.raises(ValueError):
            await client.get_profile_requester_stats(now, now + timedelta(days=1))

    async def test_unavailable_requester_endpoint_uses_existing_error_path(self):
        api_client = _make_api_client()
        api_client.get_profile_requester_stats.side_effect = RuntimeError(
            "profile count unavailable"
        )
        notifications = AsyncMock()
        await send_daily_funnel_report(MagicMock(), _make_billing(), api_client, notifications)
        notifications.error_notify.assert_awaited_once()
        notifications.bot.send_message.assert_not_awaited()


class TestConnectedActivityClient:
    async def test_request_shape_and_parsing(self):
        client, transport = _make_api_client_with_mock()
        transport.request.return_value = _make_response(
            200,
            {
                "connected_users": 5,
                "scope": "exit_attributable",
                "not_observed": ["relay_whitelist"],
                "collection": {
                    "since": "2026-10-09T20:00:00Z",
                    "covers_range": True,
                    "fresh": True,
                    "nodes_total": 8,
                    "nodes_fresh": 8,
                    "oldest_apply_ok_at": "2026-10-10T05:59:40Z",
                },
            },
        )
        start = datetime(2026, 10, 9, tzinfo=MSK)
        stats = await client.get_connected_activity(start, start + timedelta(days=1))
        assert stats.connected_users == 5
        assert stats.not_observed == ("relay_whitelist",)
        assert stats.since == datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc)
        assert stats.covers_range is True and stats.fresh is True
        assert (stats.nodes_total, stats.nodes_fresh) == (8, 8)
        args = transport.request.call_args
        assert args.args == ("GET", f"{BASE_URL}/api/v1/internal/stats/connected-activity")
        assert args.kwargs["params"] == {
            "from": "2026-10-08T21:00:00+00:00",
            "to": "2026-10-09T21:00:00+00:00",
        }

    async def test_null_timestamps_are_none(self):
        client, transport = _make_api_client_with_mock()
        transport.request.return_value = _make_response(
            200,
            {
                "connected_users": 0,
                "scope": "exit_attributable",
                "not_observed": ["relay_whitelist"],
                "collection": {
                    "since": None,
                    "covers_range": False,
                    "fresh": False,
                    "nodes_total": 8,
                    "nodes_fresh": 0,
                    "oldest_apply_ok_at": None,
                },
            },
        )
        now = datetime(2026, 10, 9, tzinfo=timezone.utc)
        stats = await client.get_connected_activity(now, now + timedelta(days=1))
        assert stats.since is None and stats.oldest_apply_ok_at is None

    @pytest.mark.parametrize(
        "payload",
        [
            None,
            {},
            {"connected_users": -1, "collection": {}},
            {"connected_users": "5", "collection": {}},
            {"connected_users": True, "collection": {}},
            {"connected_users": 1},
            {"connected_users": 1, "collection": {"covers_range": "yes"}},
        ],
    )
    async def test_malformed_payload_is_not_silent_zero(self, payload):
        client, transport = _make_api_client_with_mock()
        transport.request.return_value = _make_response(200, payload)
        now = datetime(2026, 10, 9, tzinfo=timezone.utc)
        with pytest.raises(ValueError):
            await client.get_connected_activity(now, now + timedelta(days=1))


class TestReportConnectedActivityLines:
    NOW = datetime(2026, 10, 10, 9, 0, tzinfo=MSK)

    async def _text(self, activity=None, error=None):
        api_client = _make_api_client()
        if error:
            api_client.get_connected_activity.side_effect = error
        elif activity is not None:
            api_client.get_connected_activity.return_value = activity
        return await _build_funnel_report_text(_make_billing(), api_client, self.NOW)

    async def test_queries_the_same_moscow_day_window(self):
        api_client = _make_api_client()
        await _build_funnel_report_text(_make_billing(), api_client, self.NOW)
        start, end = compute_msk_previous_day_window(self.NOW)
        api_client.get_connected_activity.assert_awaited_once_with(start, end)
        assert start == datetime(2026, 10, 8, 21, 0, tzinfo=timezone.utc)

    async def test_complete_and_fresh_names_scope_and_what_is_missing(self):
        text = await self._text()
        assert "Connected users (observed on exit nodes): 5" in text
        assert "Direct and per-user routes only" in text
        assert "Relay (whitelist) users are not observable and are not counted" in text
        assert "Collector: covers the whole day; current (8/8 nodes)" in text
        assert "PARTIAL" not in text and "STALE" not in text

    async def test_collection_started_mid_day_is_labelled_partial_in_moscow_time(self):
        since = datetime(2026, 10, 9, 15, 30, tzinfo=timezone.utc)  # 18:30 MSK
        text = await self._text(_activity(covers_range=False, since=since))
        assert "PARTIAL: collection only started 2026-10-09 18:30 MSK" in text

    async def test_never_collected_says_no_data_not_zero_people(self):
        text = await self._text(
            _activity(connected_users=0, covers_range=False, since=None, fresh=False, nodes_fresh=0)
        )
        assert "NO DATA: collector has not covered every exit node yet" in text

    async def test_stale_collector_is_flagged_with_node_counts(self):
        oldest = datetime(2026, 10, 10, 2, 0, tzinfo=timezone.utc)  # 05:00 MSK
        text = await self._text(_activity(fresh=False, nodes_fresh=5, oldest_apply_ok_at=oldest))
        assert "STALE: only 5/8 nodes current, oldest ok 2026-10-10 05:00 MSK" in text

    async def test_stale_with_no_success_ever_says_never(self):
        text = await self._text(_activity(fresh=False, nodes_fresh=0, oldest_apply_ok_at=None))
        assert "STALE: only 0/8 nodes current, never completed" in text

    async def test_endpoint_failure_does_not_hide_the_rest_of_the_report(self):
        text = await self._text(error=RuntimeError("boom"))
        assert "Connected users (observed on exit nodes): unavailable" in text
        assert "New users: 10" in text
        assert "Profile requesters: 8" in text

    async def test_latest_seen_line_stays_but_is_labelled_as_not_history(self):
        text = await self._text()
        assert "Last seen on VPN that day: 6" in text
