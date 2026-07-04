from __future__ import annotations

import io
import json
from typing import Any
from unittest import TestCase
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

from estimand_sdk import (
    ConfigCacheMissError,
    EstimandClient,
    EstimandClientConfig,
    EstimandSDKHTTPError,
)
from estimand_sdk.models import EventPayload


class _FakeResponse:
    def __init__(self, status: int, body: dict[str, Any] | str | None = None, headers: dict[str, str] | None = None) -> None:
        self._status = status
        self._body = body if isinstance(body, str) else (json.dumps(body) if body is not None else "")
        self.headers = headers or {}

    def getcode(self) -> int:
        return self._status

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_tb) -> None:
        return None


class ClientTestCase(TestCase):
    def setUp(self) -> None:
        self.client = EstimandClient(
            EstimandClientConfig(
                base_url="https://estimand.app",
                api_key="esk_test",
                request_timeout=1.0,
                retries=1,
                retry_backoff_seconds=0,
            )
        )
        self.scope = {
            "organization_id": "org-1",
            "project_id": "proj-1",
            "environment_id": "env-1",
        }

    def test_fetch_config_uses_etag_cache(self) -> None:
        request_count = 0
        captured_requests: list[Request] = []

        def fake_urlopen(request: Request, *_args: Any, **_kwargs: Any):
            nonlocal request_count
            request_count += 1
            captured_requests.append(request)
            if request.get_method() == "GET":
                if request.headers.get("If-None-Match"):
                    return _FakeResponse(304, headers={"ETag": 'W/"rev-1"'})
                return _FakeResponse(
                    200,
                    {
                        "revision": "rev-1",
                        "features": {},
                    },
                    headers={"ETag": 'W/"rev-1"'},
                )
            raise AssertionError("Unexpected request method")

        with patch("estimand_sdk.client.urlopen", side_effect=fake_urlopen):
            first = self.client.fetch_config(**self.scope)
            second = self.client.fetch_config(**self.scope)

        self.assertEqual(first.revision, "rev-1")
        self.assertEqual(second.revision, "rev-1")
        self.assertEqual(request_count, 2)
        second_request_headers = dict(captured_requests[1].headers)
        self.assertEqual(second_request_headers.get("If-none-match"), 'W/"rev-1"')

    def test_304_without_cache_fails_fast(self) -> None:
        def fake_urlopen(request: Request, *_args: Any, **_kwargs: Any):
            return _FakeResponse(304, headers={"ETag": 'W/"rev-1"'})

        no_cache_client = EstimandClient("https://estimand.app", api_key="esk_test")
        with patch("estimand_sdk.client.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(ConfigCacheMissError):
                no_cache_client.fetch_config(**self.scope)

    def test_send_events_retries_and_parses_response(self) -> None:
        def retryable_error():
            return HTTPError(
                url="https://estimand.app/api/v1/events",
                code=503,
                msg="unavailable",
                hdrs={},
                fp=io.BytesIO(json.dumps({"status": "error", "code": "temporary"}).encode("utf-8")),
            )

        response = {
            "status": "accepted",
            "code": "events_accepted",
            "ingested": 1,
            "deduplicated": 0,
        }

        with patch("estimand_sdk.client.time.sleep", lambda _seconds: None):
            with patch("estimand_sdk.client.urlopen", side_effect=[retryable_error(), _FakeResponse(202, response)]) as mock_urlopen:
                sent = self.client.send_events(
                    [
                        EventPayload(
                            event_id="ev-1",
                            project_id="p",
                            environment_id="e",
                            feature_id="f",
                            unit_id="u",
                            event_type="exposure",
                            event_name="exposure",
                        )
                    ]
                )

        self.assertEqual(sent.code, "events_accepted")
        self.assertEqual(sent.ingested, 1)
        self.assertEqual(mock_urlopen.call_count, 2)

    def test_raises_http_error_after_exhausted_retries(self) -> None:
        def retryable_error():
            return HTTPError(
                url="https://estimand.app/api/v1/config",
                code=503,
                msg="unavailable",
                hdrs={},
                fp=io.BytesIO(json.dumps({"status": "error", "code": "temporary"}).encode("utf-8")),
            )

        with patch("estimand_sdk.client.time.sleep", lambda _seconds: None):
            with patch("estimand_sdk.client.urlopen", side_effect=retryable_error()):
                with self.assertRaises(EstimandSDKHTTPError):
                    self.client.fetch_config(**self.scope)
