"""HTTP client for compono-api identity endpoints.

Calls the API-owned identity endpoints (not billing proxied routes).
Protected by X-Internal-Secret header authentication.
"""

from typing import Any, Optional

import httpx
from loguru import logger


class ApiIdentityClientError(Exception):
    """Raised when the compono-api identity endpoint returns an error."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"API identity error {status_code}: {message}")


class ApiIdentityClient:
    """Async HTTP client for compono-api identity endpoints."""

    def __init__(self, base_url: str, internal_secret: str, timeout: float = 10.0) -> None:
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
            logger.error(f"API identity request failed: {method} {path} - {e}")
            raise ApiIdentityClientError(0, str(e)) from e

        if response.status_code >= 400:
            error_body = response.text
            try:
                error_data = response.json()
                error_body = error_data.get("error", error_body)
            except Exception:
                pass
            logger.error(
                f"API identity error: {method} {path} -> {response.status_code}: {error_body}"
            )
            raise ApiIdentityClientError(response.status_code, error_body)

        if response.status_code == 204:
            return None

        return response.json()

    async def ensure_with_linkage(
        self,
        telegram_id: int,
        remnawave_user_id: str,
        *,
        name: Optional[str] = None,
        username: Optional[str] = None,
        language: Optional[str] = None,
    ) -> dict[str, Any]:
        """Ensure a compono user exists and set Remnawave linkage.

        Calls POST /api/v1/internal/compono-users/ensure-with-linkage.
        This replaces the deprecated billing customer bridge:
        - billing.get_or_create_customer_by_telegram_id
        - billing.update_customer(id, remna_user_uuid=...)
        - billing.update_user(telegram_id, {"customer_id": ...})
        """
        payload: dict[str, Any] = {
            "telegram_id": telegram_id,
            "remnawave_user_id": remnawave_user_id,
        }
        if name is not None:
            payload["name"] = name
        if username is not None:
            payload["username"] = username
        if language is not None:
            payload["language"] = language

        return await self._request(
            "POST",
            "/compono-users/ensure-with-linkage",
            json=payload,
        )
