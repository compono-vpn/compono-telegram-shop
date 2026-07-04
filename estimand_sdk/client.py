from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .assignment import assign
from .evaluator import (
    EvaluationResult,
    evaluate_feature_from_payload,
    evaluate_features,
)
from .models import ConfigPayload, EventBatchResponse, EventPayload


EVENT_TYPES = ("exposure", "conversion", "custom")


class EstimandSDKError(Exception):
    """Base SDK exception."""


class EstimandSDKConfigError(EstimandSDKError):
    """Raised when config payloads are unavailable or malformed."""


class ConfigCacheMissError(EstimandSDKConfigError):
    """Raised when a 304 response arrives without a cached config."""


class EstimandSDKHTTPError(EstimandSDKError):
    """HTTP response did not indicate success."""

    def __init__(self, status: int, body: Mapping[str, Any] | str | None = None, headers: Mapping[str, str] | None = None):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.body = body
        self.headers = headers or {}


class EstimandSDKRequestError(EstimandSDKError):
    """Unable to complete an HTTP request."""


@dataclass(frozen=True)
class EstimandClientConfig:
    """Configuration for the Estimand Python SDK HTTP client."""

    base_url: str
    api_key: str
    request_timeout: float = 3.0
    retries: int = 2
    retry_backoff_seconds: float = 0.2
    retry_statuses: tuple[int, ...] = (429, 500, 502, 503, 504)


class EstimandClient:
    """Typed client for Estimand config + event ingestion endpoints."""

    def __init__(self, config: EstimandClientConfig | str, *, api_key: str | None = None):
        if isinstance(config, str):
            if not api_key:
                raise ValueError("api_key is required when passing base_url")
            config = EstimandClientConfig(base_url=config, api_key=api_key)

        self._config = config
        if not self._config.api_key:
            raise ValueError("X-API-Key is required")

        self._config_cache: dict[tuple[str, str, str], ConfigPayload] = {}
        self._etag_cache: dict[tuple[str, str, str], str] = {}
        self._scope_cache_key: tuple[str, str, str] | None = None

    @property
    def base_url(self) -> str:
        """Base URL without trailing slash."""
        return self._config.base_url.rstrip("/")

    def fetch_config(
        self,
        *,
        organization_id: str,
        project_id: str,
        environment_id: str,
        force_refresh: bool = False,
    ) -> ConfigPayload:
        scope = self._scope_key(organization_id, project_id, environment_id)
        headers = {"X-API-Key": self._config.api_key}
        if not force_refresh and scope in self._etag_cache:
            headers["If-None-Match"] = self._etag_cache[scope]

        response = self._request(
            "GET",
            "/api/v1/config",
            headers=headers,
            params={
                "organization_id": organization_id,
                "project_id": project_id,
                "environment_id": environment_id,
            },
            include_json=False,
        )

        status = response["status"]
        body = response["body"]
        response_headers = response["headers"]

        if status == 304:
            cached = self._config_cache.get(scope)
            if cached is None:
                raise ConfigCacheMissError("No cached config available for ETag response")
            self._scope_cache_key = scope
            return cached

        parsed = _parse_json(body)
        if not isinstance(parsed, Mapping):
            raise EstimandSDKConfigError("Config response must be a JSON object")
        config_payload = ConfigPayload.from_mapping(parsed)

        self._config_cache[scope] = config_payload
        self._etag_cache[scope] = _extract_etag(response_headers, config_payload.revision)
        self._scope_cache_key = scope
        return config_payload

    def send_events(self, events: Sequence[EventPayload]) -> EventBatchResponse:
        if not events:
            raise ValueError("events payload cannot be empty")

        payload = {"events": [event.to_mapping() for event in events]}
        response = self._request(
            "POST",
            "/api/v1/events",
            headers={"X-API-Key": self._config.api_key},
            json_body=payload,
        )

        parsed = _parse_json(response["body"])
        if not isinstance(parsed, Mapping):
            raise EstimandSDKRequestError("Event API response must be JSON")
        return EventBatchResponse.from_mapping(parsed)

    def track_exposure(
        self,
        *,
        event_id: str | None = None,
        project_id: str,
        environment_id: str,
        feature_id: str,
        unit_id: str,
        variant_key: str | None = None,
        variation_id: str | None = None,
        value: float = 1.0,
        timestamp: datetime | None = None,
        properties: dict[str, Any] | None = None,
    ) -> EventBatchResponse:
        return self.send_events(
            [
                EventPayload(
                    event_id=event_id or str(uuid.uuid4()),
                    project_id=project_id,
                    environment_id=environment_id,
                    feature_id=feature_id,
                    unit_id=unit_id,
                    event_type="exposure",
                    event_name="exposure",
                    variant_key=variant_key,
                    variation_id=variation_id,
                    value=value,
                    timestamp=(timestamp or datetime.now(timezone.utc)).isoformat(),
                    properties=properties,
                )
            ]
        )

    def track_conversion(
        self,
        *,
        event_id: str | None = None,
        project_id: str,
        environment_id: str,
        feature_id: str,
        unit_id: str,
        event_name: str,
        variant_key: str | None = None,
        variation_id: str | None = None,
        value: float = 1.0,
        timestamp: datetime | None = None,
        properties: dict[str, Any] | None = None,
    ) -> EventBatchResponse:
        if not event_name:
            raise ValueError("event_name is required for conversion events")
        return self.send_events(
            [
                EventPayload(
                    event_id=event_id or str(uuid.uuid4()),
                    project_id=project_id,
                    environment_id=environment_id,
                    feature_id=feature_id,
                    unit_id=unit_id,
                    event_type="conversion",
                    event_name=event_name,
                    variant_key=variant_key,
                    variation_id=variation_id,
                    value=value,
                    timestamp=(timestamp or datetime.now(timezone.utc)).isoformat(),
                    properties=properties,
                )
            ]
        )

    def track_custom(
        self,
        *,
        event_id: str | None = None,
        project_id: str,
        environment_id: str,
        feature_id: str,
        unit_id: str,
        event_name: str,
        variant_key: str | None = None,
        variation_id: str | None = None,
        value: float = 1.0,
        timestamp: datetime | None = None,
        properties: dict[str, Any] | None = None,
    ) -> EventBatchResponse:
        if not event_name:
            raise ValueError("event_name is required for custom events")
        return self.send_events(
            [
                EventPayload(
                    event_id=event_id or str(uuid.uuid4()),
                    project_id=project_id,
                    environment_id=environment_id,
                    feature_id=feature_id,
                    unit_id=unit_id,
                    event_type="custom",
                    event_name=event_name,
                    variant_key=variant_key,
                    variation_id=variation_id,
                    value=value,
                    timestamp=(timestamp or datetime.now(timezone.utc)).isoformat(),
                    properties=properties,
                )
            ]
        )

    def evaluate_feature(
        self,
        *,
        feature_key: str,
        unit_id: str,
        context: Mapping[str, Any] | None = None,
        config: ConfigPayload | None = None,
    ) -> EvaluationResult:
        payload = config or self._latest_config()
        return evaluate_feature_from_payload(
            config=payload,
            feature_key=feature_key,
            unit_id=unit_id,
            context=context,
        )

    def evaluate_all(
        self,
        *,
        unit_id: str,
        context: Mapping[str, Any] | None = None,
        config: ConfigPayload | None = None,
    ) -> dict[str, EvaluationResult]:
        payload = config or self._latest_config()
        return evaluate_features(config=payload, unit_id=unit_id, context=context)

    def deterministic_assignment(
        self,
        *,
        seed: str,
        unit_id: str,
        num_variations: int,
        coverage: float = 1,
        weights: Sequence[float] | None = None,
        hash_version: int = 2,
    ) -> tuple[float, int, list[tuple[float, float]]]:
        result = assign(
            seed=seed,
            unit=unit_id,
            num_variations=num_variations,
            coverage=coverage,
            weights=weights,
            hash_version=hash_version,
        )
        return result.bucket, result.variation_index, result.ranges

    def _latest_config(self) -> ConfigPayload:
        if self._scope_cache_key is None:
            raise ConfigCacheMissError("No config loaded yet")
        cached = self._config_cache.get(self._scope_cache_key)
        if cached is None:
            raise ConfigCacheMissError("Cached config was removed")
        return cached

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
        include_json: bool = True,
    ) -> dict[str, Any]:
        full_headers = {
            "Accept": "application/json",
            "User-Agent": "estimand-python-sdk/0.1",
        }
        if headers:
            full_headers.update(headers)

        url = self.base_url + path
        if params:
            url = f"{url}?{urlencode({key: value for key, value in params.items() if value is not None})}"

        attempts = self._config.retries + 1
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                body = json.dumps(json_body).encode("utf-8") if include_json and json_body is not None else None
                if body is not None:
                    full_headers["Content-Type"] = "application/json"
                request = Request(url, data=body, headers=full_headers, method=method.upper())
                with urlopen(request, timeout=self._config.request_timeout) as response:
                    return {
                        "status": response.getcode(),
                        "body": response.read().decode("utf-8"),
                        "headers": _normalize_headers(response.headers),  # type: ignore[arg-type]
                    }
            except HTTPError as exc:
                status = exc.code
                response_body = exc.read().decode("utf-8", errors="replace")
                if status == 304:
                    return {
                        "status": status,
                        "body": response_body,
                        "headers": _normalize_headers(exc.headers or {}),
                    }

                if status in self._config.retry_statuses and attempt < attempts - 1:
                    last_error = EstimandSDKHTTPError(status=status, body=_parse_json(response_body), headers=_normalize_headers(exc.headers or {}))
                    time.sleep(self._config.retry_backoff_seconds * (2**attempt))
                    continue

                raise EstimandSDKHTTPError(
                    status=status,
                    body=_parse_json(response_body),
                    headers=_normalize_headers(exc.headers or {}),
                ) from last_error
            except (URLError, TimeoutError) as exc:
                if attempt < attempts - 1:
                    last_error = exc
                    time.sleep(self._config.retry_backoff_seconds * (2**attempt))
                    continue
                raise EstimandSDKRequestError("Request failed after retries") from exc

        raise EstimandSDKRequestError("Request failed after retries") from last_error

    def _scope_key(self, organization_id: str, project_id: str, environment_id: str) -> tuple[str, str, str]:
        return (str(organization_id), str(project_id), str(environment_id))


def _normalize_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    if headers is None:
        return {}
    return {str(key).lower(): str(value) for key, value in headers.items()}


def _extract_etag(headers: Mapping[str, str], revision: str) -> str:
    etag = headers.get("etag")
    if etag:
        return etag
    return f'W/"{revision}"'
def _parse_json(payload: str) -> Any:
    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None
