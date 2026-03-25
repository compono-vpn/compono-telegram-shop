"""HTTP client for compono-billing service."""

import re

import httpx

from src.core.config.app import AppConfig


def _pascal_to_snake(name: str) -> str:
    """Convert PascalCase to snake_case: OrderIndex -> order_index, ID -> id."""
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()


def _convert_keys(obj):
    """Recursively convert dict keys from PascalCase to snake_case."""
    if isinstance(obj, dict):
        return {_pascal_to_snake(k): _convert_keys(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_convert_keys(item) for item in obj]
    return obj


class BillingClient:
    """Async HTTP client for the billing service internal API."""

    def __init__(self, config: AppConfig):
        self._base_url = config.billing_url
        self._client = httpx.AsyncClient(
            base_url=config.billing_url,
            headers={"X-Internal-Secret": config.billing_secret},
            timeout=30.0,
        )

    async def close(self):
        await self._client.aclose()

    # --- Plans ---

    async def get_plans(self, active_only: bool = True) -> list[dict]:
        endpoint = "/api/v1/internal/plans" if not active_only else "/api/v1/plans"
        resp = await self._client.get(endpoint)
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def get_plan(self, plan_id: int) -> dict | None:
        resp = await self._client.get(f"/api/v1/internal/plans/{plan_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def get_trial_plan(self) -> dict | None:
        resp = await self._client.get("/api/v1/internal/plans/trial")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def get_plan_by_name(self, plan_name: str) -> dict | None:
        resp = await self._client.get("/api/v1/internal/plans/by-name", params={"name": plan_name})
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def create_plan(self, data: dict) -> dict:
        resp = await self._client.post("/api/v1/internal/plans", json=data)
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def update_plan(self, data: dict) -> dict:
        resp = await self._client.put("/api/v1/internal/plans", json=data)
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def delete_plan(self, plan_id: int) -> None:
        resp = await self._client.delete(f"/api/v1/internal/plans/{plan_id}")
        resp.raise_for_status()

    async def move_plan_up(self, plan_id: int) -> bool:
        resp = await self._client.post(f"/api/v1/internal/plans/{plan_id}/move-up")
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        return True

    async def get_available_plans(self, telegram_id: int) -> list[dict]:
        resp = await self._client.get(
            "/api/v1/internal/plans/available", params={"telegram_id": telegram_id}
        )
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def get_allowed_plans(self) -> list[dict]:
        resp = await self._client.get("/api/v1/internal/plans/allowed")
        resp.raise_for_status()
        return _convert_keys(resp.json())

    # --- Payments ---

    async def create_payment(
        self,
        telegram_id: int,
        plan_id: int,
        duration_days: int,
        currency: str,
        gateway_type: str,
        purchase_type: str = "NEW",
        is_test: bool = False,
        promocode_id: int | None = None,
    ) -> dict:
        resp = await self._client.post(
            "/api/v1/internal/payment/create",
            json={
                "telegram_id": telegram_id,
                "plan_id": plan_id,
                "duration_days": duration_days,
                "currency": currency,
                "gateway_type": gateway_type,
                "purchase_type": purchase_type,
                "is_test": is_test,
                "promocode_id": promocode_id,
            },
        )
        resp.raise_for_status()
        return _convert_keys(resp.json())

    # --- Subscriptions ---

    async def get_current_subscription(self, telegram_id: int) -> dict | None:
        resp = await self._client.get(f"/api/v1/internal/subscription/{telegram_id}/current")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def has_used_trial(self, telegram_id: int) -> bool:
        resp = await self._client.get(f"/api/v1/internal/subscription/{telegram_id}/trial-used")
        resp.raise_for_status()
        return _convert_keys(resp.json()).get("used", False)

    # --- Transactions ---

    async def get_transactions(self, telegram_id: int) -> list[dict]:
        resp = await self._client.get(f"/api/v1/internal/transactions/{telegram_id}")
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def get_transaction(self, transaction_id: str) -> dict | None:
        resp = await self._client.get(f"/api/v1/internal/transactions/detail/{transaction_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _convert_keys(resp.json())

    # --- Promocodes ---

    async def activate_promocode(self, code: str, telegram_id: int) -> dict:
        resp = await self._client.post(
            "/api/v1/internal/promocode/activate",
            json={"code": code, "telegram_id": telegram_id},
        )
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def get_promocode(self, promocode_id: int) -> dict | None:
        resp = await self._client.get(f"/api/v1/internal/promocodes/{promocode_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def get_promocode_by_code(self, code: str) -> dict | None:
        resp = await self._client.get("/api/v1/internal/promocodes/by-code", params={"code": code})
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def list_promocodes(self) -> list[dict]:
        resp = await self._client.get("/api/v1/internal/promocodes")
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def create_promocode(self, data: dict) -> dict:
        resp = await self._client.post("/api/v1/internal/promocodes", json=data)
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def update_promocode(self, data: dict) -> dict:
        resp = await self._client.put("/api/v1/internal/promocodes", json=data)
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def delete_promocode(self, promocode_id: int) -> None:
        resp = await self._client.delete("/api/v1/internal/promocodes", params={"id": promocode_id})
        resp.raise_for_status()

    # --- Web Orders ---

    async def claim_web_order(self, telegram_id: int, short_id: str) -> dict:
        resp = await self._client.post(
            "/api/v1/internal/web-order/claim",
            json={"telegram_id": telegram_id, "short_id": short_id},
        )
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def link_subscription_url(self, telegram_id: int, subscription_token: str) -> dict:
        """Link a subscription URL (by token/shortUuid) to a telegram user."""
        resp = await self._client.post(
            "/api/v1/internal/subscription/link",
            json={"telegram_id": telegram_id, "subscription_token": subscription_token},
        )
        resp.raise_for_status()
        return _convert_keys(resp.json())

    # --- Users ---

    async def get_user(self, telegram_id: int) -> dict | None:
        resp = await self._client.get(f"/api/v1/internal/users/{telegram_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def create_user(self, data: dict) -> dict:
        resp = await self._client.post("/api/v1/internal/users", json=data)
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def update_user(self, telegram_id: int, data: dict) -> dict:
        resp = await self._client.put(f"/api/v1/internal/users/{telegram_id}", json=data)
        resp.raise_for_status()
        return _convert_keys(resp.json())

    # --- Settings ---

    async def get_settings(self) -> dict:
        resp = await self._client.get("/api/v1/internal/settings")
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def update_settings(self, data: dict) -> dict:
        resp = await self._client.put("/api/v1/internal/settings", json=data)
        resp.raise_for_status()
        return _convert_keys(resp.json())

    # --- Statistics ---

    async def get_statistics(self) -> dict:
        resp = await self._client.get("/api/v1/internal/statistics")
        resp.raise_for_status()
        return _convert_keys(resp.json())

    # --- Gateways ---

    async def get_gateway(self, gateway_id: int) -> dict | None:
        resp = await self._client.get(f"/api/v1/internal/gateways/{gateway_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def get_gateway_by_type(self, gateway_type: str) -> dict | None:
        resp = await self._client.get(
            "/api/v1/internal/gateways/by-type", params={"type": gateway_type}
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def filter_active_gateways(self) -> list[dict]:
        resp = await self._client.get("/api/v1/internal/gateways/active")
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def move_gateway_up(self, gateway_id: int) -> bool:
        resp = await self._client.post(f"/api/v1/internal/gateways/{gateway_id}/move-up")
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        return True

    async def create_test_payment(self, telegram_id: int, gateway_type: str) -> dict:
        resp = await self._client.post(
            "/api/v1/internal/gateways/test-payment",
            json={"telegram_id": telegram_id, "gateway_type": gateway_type},
        )
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def calculate_price(
        self,
        telegram_id: int,
        plan_id: int,
        duration_days: int,
        currency: str,
    ) -> dict:
        resp = await self._client.post(
            "/api/v1/internal/pricing/calculate",
            json={
                "telegram_id": telegram_id,
                "plan_id": plan_id,
                "duration_days": duration_days,
                "currency": currency,
            },
        )
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def get_default_currency(self) -> str:
        resp = await self._client.get("/api/v1/internal/settings/default-currency")
        resp.raise_for_status()
        return _convert_keys(resp.json()).get("currency", "XTR")

    async def set_default_currency(self, currency: str) -> None:
        resp = await self._client.put(
            "/api/v1/internal/settings/default-currency",
            json={"currency": currency},
        )
        resp.raise_for_status()

    async def handle_free_payment(self, payment_id: str) -> dict:
        resp = await self._client.post(
            "/api/v1/internal/payment/handle-free",
            json={"payment_id": payment_id},
        )
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def list_gateways(self) -> list[dict]:
        resp = await self._client.get("/api/v1/internal/gateways")
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def create_gateway(self, data: dict) -> dict:
        resp = await self._client.post("/api/v1/internal/gateways", json=data)
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def update_gateway(self, data: dict) -> dict:
        resp = await self._client.put("/api/v1/internal/gateways", json=data)
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def delete_gateway(self, gateway_id: int) -> None:
        resp = await self._client.delete("/api/v1/internal/gateways", params={"id": gateway_id})
        resp.raise_for_status()

    # --- Referrals ---

    async def link_referral(self, referrer_code: str, referred_telegram_id: int) -> dict:
        resp = await self._client.post(
            "/api/v1/internal/referral/link",
            json={"referrer_code": referrer_code, "referred_telegram_id": referred_telegram_id},
        )
        resp.raise_for_status()
        return _convert_keys(resp.json())

    async def get_referral_info(self, telegram_id: int) -> dict:
        resp = await self._client.get(f"/api/v1/internal/referral/{telegram_id}")
        resp.raise_for_status()
        return _convert_keys(resp.json())

    # --- Trial ---

    async def create_trial(self, telegram_id: int, plan_id: int) -> dict:
        """Create trial subscription via billing service."""
        resp = await self._client.post(
            "/api/v1/internal/payment/create",
            json={
                "telegram_id": telegram_id,
                "plan_id": plan_id,
                "duration_days": 0,
                "currency": "XTR",
                "gateway_type": "TELEGRAM_STARS",
                "purchase_type": "NEW",
                "is_test": False,
            },
        )
        resp.raise_for_status()
        return _convert_keys(resp.json())
