"""HTTP client for compono-api internal endpoints.

Calls the API-owned internal endpoints for user provisioning
and identity management. Protected by X-Internal-Secret header.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import httpx
from loguru import logger

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
            "telegram_id": telegram_id,
            "name": name,
            "plan": {
                "name": plan.name,
                "traffic_limit": plan.traffic_limit,
                "device_limit": plan.device_limit,
                "traffic_limit_strategy": str(plan.traffic_limit_strategy.value)
                if hasattr(plan.traffic_limit_strategy, "value")
                else str(plan.traffic_limit_strategy),
                "duration_days": plan.duration,
                "tag": plan.tag,
                "internal_squads": [str(s) for s in plan.internal_squads],
                "external_squad": str(plan.external_squad) if plan.external_squad else None,
            },
        }
        if username is not None:
            payload["username"] = username
        if language is not None:
            payload["language"] = language

        data = await self._request("POST", "/provision-user", json=payload)

        return ProvisionResult(
            compono_user_id=data["compono_user_id"],
            remnawave_user_id=data["remnawave_user_id"],
            remnawave_username=data["remnawave_username"],
            subscription_url=data["subscription_url"],
            status=data["status"],
            expire_at=data["expire_at"],
        )
