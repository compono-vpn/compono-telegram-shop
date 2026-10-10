"""HTTP client for compono-api internal endpoints.

Calls the API-owned internal endpoints for user provisioning
and identity management. Protected by X-Internal-Secret header.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import httpx
from loguru import logger

from src.core.utils.time import to_rfc3339_utc
from src.models.dto import PlanSnapshotDto


class ApiClientError(Exception):
    """Raised when the compono-api endpoint returns an error."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"API error {status_code}: {message}")


@dataclass(frozen=True)
class ProvisionResult:
    """Response from POST /api/v1/internal/provision-user."""

    compono_user_id: str
    remnawave_user_id: str
    remnawave_username: str
    subscription_url: str
    status: str
    expire_at: str


@dataclass(frozen=True)
class ConnectedStats:
    """Response from GET /api/v1/internal/stats/connected."""

    connected: int


@dataclass(frozen=True)
class ProfileRequesterStats:
    """Distinct accounts requesting profiles, including refreshes and failures."""

    profile_requesters: int


@dataclass(frozen=True)
class ConnectedActivityStats:
    """Users observed with traffic in a range, with coverage and collector freshness.

    Counts only users identifiable per account on exit nodes; users listed in
    ``not_observed`` (relay/whitelist) are never part of the count.
    """

    connected_users: int
    scope: str
    not_observed: tuple[str, ...]
    since: Optional[datetime]
    covers_range: bool
    fresh: bool
    nodes_total: int
    nodes_fresh: int
    oldest_apply_ok_at: Optional[datetime]


def _count(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"Invalid {name}")
    return value


def _flag(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"Invalid {name}")
    return value


def _utc_or_none(value: Any, name: str) -> Optional[datetime]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Invalid {name}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exception:
        raise ValueError(f"Invalid {name}") from exception
    if parsed.tzinfo is None:
        raise ValueError(f"Invalid {name}")
    return parsed


class ApiClient:
    """Async HTTP client for compono-api internal endpoints."""

    def __init__(self, base_url: str, internal_secret: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._internal_secret = internal_secret
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def _base_path(self) -> str:
        return f"{self.base_url}/api/v1/internal"

    def _headers(self) -> dict[str, str]:
        return {
            "X-Internal-Secret": self._internal_secret,
            "Content-Type": "application/json",
        }

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers=self._headers(),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Optional[dict[str, Any]] = None,
    ) -> Any:
        client = await self._get_client()
        url = f"{self._base_path}{path}"

        try:
            response = await client.request(method, url, json=json, params=params)
        except httpx.HTTPError as e:
            logger.error(f"API request failed: {method} {path} - {e}")
            raise ApiClientError(0, str(e)) from e

        if response.status_code >= 400:
            error_body = response.text
            try:
                error_data = response.json()
                error_body = error_data.get("error", error_body)
            except Exception:
                pass
            logger.error(f"API error: {method} {path} -> {response.status_code}: {error_body}")
            raise ApiClientError(response.status_code, error_body)

        if response.status_code == 204:
            return None

        return response.json()

    async def provision_user(
        self,
        telegram_id: int,
        plan: PlanSnapshotDto,
        *,
        name: str = "",
        username: Optional[str] = None,
        language: Optional[str] = None,
    ) -> ProvisionResult:
        """Provision a new Remnawave user via compono-api.

        Calls POST /api/v1/internal/provision-user which atomically:
        1. Ensures the compono identity exists
        2. Creates the Remnawave user
        3. Persists the linkage

        Returns a ProvisionResult with all fields needed to build a SubscriptionDto.
        """
        payload: dict[str, Any] = {
            "telegramId": telegram_id,
            "name": name,
            "plan": {
                "name": plan.name,
                "trafficLimit": plan.traffic_limit,
                "deviceLimit": plan.device_limit,
                "trafficLimitStrategy": str(plan.traffic_limit_strategy.value)
                if hasattr(plan.traffic_limit_strategy, "value")
                else str(plan.traffic_limit_strategy),
                "durationDays": plan.duration,
                "tag": plan.tag,
                "internalSquads": [str(s) for s in plan.internal_squads],
                "externalSquad": str(plan.external_squad) if plan.external_squad else None,
            },
        }
        if username is not None:
            payload["username"] = username
        if language is not None:
            payload["language"] = language

        data = await self._request("POST", "/provision-user", json=payload)

        return ProvisionResult(
            compono_user_id=data["componoUserId"],
            remnawave_user_id=data["remnawaveUserId"],
            remnawave_username=data["remnawaveUsername"],
            subscription_url=data["subscriptionUrl"],
            status=data["status"],
            expire_at=data["expireAt"],
        )

    async def get_connected_stats(self, date_from: datetime, date_to: datetime) -> ConnectedStats:
        """Fetch users whose latest recorded VPN activity falls in a UTC range.

        Calls GET /api/v1/internal/stats/connected?from=<RFC3339 UTC>&to=<RFC3339 UTC>.
        """
        data = await self._request(
            "GET",
            "/stats/connected",
            params={
                "from": to_rfc3339_utc(date_from),
                "to": to_rfc3339_utc(date_to),
            },
        )
        return ConnectedStats(connected=data.get("connected", 0) if data else 0)

    async def get_profile_requester_stats(
        self, date_from: datetime, date_to: datetime
    ) -> ProfileRequesterStats:
        data = await self._request(
            "GET",
            "/stats/profile-requesters",
            params={
                "from": to_rfc3339_utc(date_from),
                "to": to_rfc3339_utc(date_to),
            },
        )
        count = data.get("profile_requesters") if isinstance(data, dict) else None
        if type(count) is not int or count < 0:
            raise ValueError("Invalid profile requester count")
        return ProfileRequesterStats(profile_requesters=count)

    async def get_connected_activity(
        self, date_from: datetime, date_to: datetime
    ) -> ConnectedActivityStats:
        """Fetch distinct users observed with traffic in a UTC range, with coverage labels.

        Calls GET /api/v1/internal/stats/connected-activity?from=...&to=....
        Raises ValueError on a malformed body instead of reporting a silent zero.
        """
        data = await self._request(
            "GET",
            "/stats/connected-activity",
            params={
                "from": to_rfc3339_utc(date_from),
                "to": to_rfc3339_utc(date_to),
            },
        )
        if not isinstance(data, dict) or not isinstance(data.get("collection"), dict):
            raise ValueError("Invalid connected activity response")
        collection = data["collection"]
        not_observed = data.get("not_observed")
        if not isinstance(not_observed, list) or not all(isinstance(i, str) for i in not_observed):
            not_observed = []
        return ConnectedActivityStats(
            connected_users=_count(data.get("connected_users"), "connected_users"),
            scope=str(data.get("scope", "")),
            not_observed=tuple(not_observed),
            since=_utc_or_none(collection.get("since"), "since"),
            covers_range=_flag(collection.get("covers_range"), "covers_range"),
            fresh=_flag(collection.get("fresh"), "fresh"),
            nodes_total=_count(collection.get("nodes_total"), "nodes_total"),
            nodes_fresh=_count(collection.get("nodes_fresh"), "nodes_fresh"),
            oldest_apply_ok_at=_utc_or_none(
                collection.get("oldest_apply_ok_at"), "oldest_apply_ok_at"
            ),
        )
