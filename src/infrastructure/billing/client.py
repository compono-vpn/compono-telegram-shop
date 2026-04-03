"""HTTP client for the compono-billing Go service.

Calls the internal API endpoints that are protected by X-Internal-Secret
header authentication. All methods are async and use httpx.AsyncClient.
"""

from typing import Any, Optional
from uuid import UUID

import httpx
from loguru import logger

from .models import (
    BillingPaymentGateway,
    BillingPaymentResult,
    BillingPlan,
    BillingPriceDetails,
    BillingPromocode,
    BillingReferral,
    BillingReferralReward,
    BillingSettings,
    BillingStatistics,
    BillingSubscription,
    BillingTGProxy,
    BillingTransaction,
    BillingUser,
    BillingWebOrderResult,
)


class BillingClientError(Exception):
    """Raised when the billing API returns an error."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"Billing API error {status_code}: {message}")


class BillingClient:
    """Async HTTP client for the compono-billing internal API."""

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
            logger.error(f"Billing API request failed: {method} {path} - {e}")
            raise BillingClientError(0, str(e)) from e

        if response.status_code >= 400:
            error_body = response.text
            try:
                error_data = response.json()
                error_body = error_data.get("error", error_body)
            except Exception:
                pass
            logger.error(f"Billing API error: {method} {path} -> {response.status_code}: {error_body}")
            raise BillingClientError(response.status_code, error_body)

        if response.status_code == 204:
            return None

        return response.json()

    async def _get(self, path: str, **kwargs: Any) -> Any:
        return await self._request("GET", path, **kwargs)

    async def _post(self, path: str, **kwargs: Any) -> Any:
        return await self._request("POST", path, **kwargs)

    async def _put(self, path: str, **kwargs: Any) -> Any:
        return await self._request("PUT", path, **kwargs)

    async def _delete(self, path: str, **kwargs: Any) -> Any:
        return await self._request("DELETE", path, **kwargs)

    # ------------------------------------------------------------------ #
    # Plans
    # ------------------------------------------------------------------ #

    async def list_plans(self) -> list[BillingPlan]:
        data = await self._get("/plans")
        return [BillingPlan.model_validate(p) for p in (data or [])]

    async def get_plan(self, plan_id: int) -> Optional[BillingPlan]:
        data = await self._get(f"/plans/{plan_id}")
        return BillingPlan.model_validate(data) if data else None

    async def get_plan_by_name(self, name: str) -> Optional[BillingPlan]:
        try:
            data = await self._get("/plans/by-name", params={"name": name})
            return BillingPlan.model_validate(data) if data else None
        except BillingClientError as e:
            if e.status_code == 404:
                return None
            raise

    async def get_trial_plan(self) -> Optional[BillingPlan]:
        data = await self._get("/plans/trial")
        return BillingPlan.model_validate(data) if data else None

    async def get_available_plans(self, telegram_id: int) -> list[BillingPlan]:
        data = await self._get("/plans/available", params={"telegram_id": str(telegram_id)})
        return [BillingPlan.model_validate(p) for p in (data or [])]

    async def get_allowed_plans(self) -> list[BillingPlan]:
        data = await self._get("/plans/allowed")
        return [BillingPlan.model_validate(p) for p in (data or [])]

    async def create_plan(self, plan_data: dict[str, Any]) -> BillingPlan:
        data = await self._post("/plans", json=plan_data)
        return BillingPlan.model_validate(data)

    async def update_plan(self, plan_data: dict[str, Any]) -> BillingPlan:
        data = await self._put("/plans", json=plan_data)
        return BillingPlan.model_validate(data)

    async def delete_plan(self, plan_id: int) -> bool:
        await self._delete(f"/plans/{plan_id}")
        return True

    async def move_plan_up(self, plan_id: int) -> bool:
        await self._post(f"/plans/{plan_id}/move-up")
        return True

    # ------------------------------------------------------------------ #
    # Subscriptions
    # ------------------------------------------------------------------ #

    async def get_current_subscription(self, telegram_id: int) -> Optional[BillingSubscription]:
        data = await self._get(f"/subscription/{telegram_id}/current")
        return BillingSubscription.model_validate(data) if data else None

    async def has_used_trial(self, telegram_id: int) -> bool:
        data = await self._get(f"/subscription/{telegram_id}/trial-used")
        return data.get("used", False) if data else False

    async def link_subscription(self, telegram_id: int, subscription_token: str) -> None:
        await self._post("/subscription/link", json={
            "telegram_id": telegram_id,
            "subscription_token": subscription_token,
        })

    async def create_trial_subscription(self, telegram_id: int, plan_id: int) -> None:
        await self._post("/subscription/create-trial", json={
            "telegram_id": telegram_id,
            "plan_id": plan_id,
        })

    async def delete_subscription(self, telegram_id: int, subscription_id: int) -> None:
        await self._post("/subscription/delete", json={
            "telegram_id": telegram_id,
            "subscription_id": subscription_id,
        })

    # ------------------------------------------------------------------ #
    # Transactions
    # ------------------------------------------------------------------ #

    async def create_transaction(
        self, telegram_id: int, transaction_data: dict[str, Any]
    ) -> BillingTransaction:
        data = await self._post("/transactions", json={
            "telegram_id": telegram_id,
            **transaction_data,
        })
        return BillingTransaction.model_validate(data)

    async def list_transactions(self, telegram_id: int) -> list[BillingTransaction]:
        data = await self._get(f"/transactions/{telegram_id}")
        return [BillingTransaction.model_validate(t) for t in (data or [])]

    async def get_transaction(self, payment_id: UUID) -> Optional[BillingTransaction]:
        try:
            data = await self._get(f"/transactions/detail/{payment_id}")
            return BillingTransaction.model_validate(data) if data else None
        except BillingClientError as e:
            if e.status_code == 404:
                return None
            raise

    async def list_all_transactions(self) -> list[BillingTransaction]:
        data = await self._get("/transactions/stats")
        if isinstance(data, list):
            return [BillingTransaction.model_validate(t) for t in data]
        return []

    async def list_transactions_by_status(self, status: str) -> list[BillingTransaction]:
        data = await self._get("/transactions/by-status", params={"status": status})
        return [BillingTransaction.model_validate(t) for t in (data or [])]

    async def transition_transaction_status(
        self, payment_id: UUID, from_status: str, to_status: str
    ) -> Optional[BillingTransaction]:
        try:
            data = await self._put(f"/transactions/{payment_id}/transition", json={
                "from_status": from_status,
                "to_status": to_status,
            })
            return BillingTransaction.model_validate(data) if data else None
        except BillingClientError as e:
            if e.status_code == 404 or e.status_code == 409:
                return None
            raise

    async def count_transactions(self) -> dict[str, Any]:
        data = await self._get("/transactions/count")
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------ #
    # Payments
    # ------------------------------------------------------------------ #

    async def create_payment(
        self,
        telegram_id: int,
        plan_id: int,
        duration_days: int,
        currency: str,
        gateway_type: str,
        purchase_type: str,
        is_test: bool = False,
        promocode_id: Optional[int] = None,
    ) -> BillingPaymentResult:
        payload: dict[str, Any] = {
            "telegram_id": telegram_id,
            "plan_id": plan_id,
            "duration_days": duration_days,
            "currency": currency,
            "gateway_type": gateway_type,
            "purchase_type": purchase_type,
            "is_test": is_test,
        }
        if promocode_id is not None:
            payload["promocode_id"] = promocode_id

        data = await self._post("/payment/create", json=payload)
        return BillingPaymentResult.model_validate(data)

    async def handle_free_payment(self, payment_id: UUID) -> None:
        await self._post("/payment/handle-free", json={"payment_id": str(payment_id)})

    # ------------------------------------------------------------------ #
    # Promocodes
    # ------------------------------------------------------------------ #

    async def list_promocodes(self) -> list[BillingPromocode]:
        data = await self._get("/promocodes")
        return [BillingPromocode.model_validate(p) for p in (data or [])]

    async def get_promocode(self, promocode_id: int) -> Optional[BillingPromocode]:
        try:
            data = await self._get(f"/promocodes/{promocode_id}")
            return BillingPromocode.model_validate(data) if data else None
        except BillingClientError as e:
            if e.status_code == 404:
                return None
            raise

    async def get_promocode_by_code(self, code: str) -> Optional[BillingPromocode]:
        try:
            data = await self._get("/promocodes/by-code", params={"code": code})
            return BillingPromocode.model_validate(data) if data else None
        except BillingClientError as e:
            if e.status_code == 404:
                return None
            raise

    async def create_promocode(self, promo_data: dict[str, Any]) -> BillingPromocode:
        data = await self._post("/promocodes", json=promo_data)
        return BillingPromocode.model_validate(data)

    async def update_promocode(self, promo_data: dict[str, Any]) -> BillingPromocode:
        data = await self._put("/promocodes", json=promo_data)
        return BillingPromocode.model_validate(data)

    async def delete_promocode(self, promocode_id: int) -> bool:
        await self._delete("/promocodes", json={"id": promocode_id})
        return True

    async def activate_promocode(self, code: str, telegram_id: int) -> None:
        await self._post("/promocode/activate", json={
            "code": code,
            "telegram_id": telegram_id,
        })

    async def validate_promocode(self, code: str) -> Optional[dict[str, Any]]:
        """Validate a promocode via the public endpoint."""
        client = await self._get_client()
        url = f"{self.base_url}/api/v1/promocode/validate"
        response = await client.post(url, json={"code": code})
        if response.status_code >= 400:
            return None
        return response.json()

    # ------------------------------------------------------------------ #
    # Users
    # ------------------------------------------------------------------ #

    async def get_user(self, telegram_id: int) -> Optional[BillingUser]:
        data = await self._get(f"/users/{telegram_id}")
        return BillingUser.model_validate(data) if data else None

    async def create_user(self, user_data: dict[str, Any]) -> BillingUser:
        data = await self._post("/users", json=user_data)
        return BillingUser.model_validate(data)

    async def update_user(self, telegram_id: int, user_data: dict[str, Any]) -> BillingUser:
        data = await self._put(f"/users/{telegram_id}", json=user_data)
        return BillingUser.model_validate(data)

    async def delete_user(self, telegram_id: int) -> None:
        await self._delete(f"/users/{telegram_id}")

    async def list_users_by_role(self, role: str) -> list[BillingUser]:
        data = await self._get(f"/users?role={role}")
        if isinstance(data, list):
            return [BillingUser.model_validate(u) for u in data]
        return []

    async def count_users(self) -> int:
        data = await self._get("/users")
        if isinstance(data, dict):
            return data.get("count", 0)
        return 0

    async def get_user_by_referral_code(self, code: str) -> Optional[BillingUser]:
        data = await self._get(f"/users/by-referral-code?code={code}")
        return BillingUser.model_validate(data) if data else None

    # ------------------------------------------------------------------ #
    # Transactions (extended)
    # ------------------------------------------------------------------ #

    async def get_transaction_stats(self) -> dict[str, int]:
        data = await self._get("/transactions/stats")
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------ #
    # Subscriptions (extended)
    # ------------------------------------------------------------------ #

    async def list_subscriptions_by_user(self, telegram_id: int) -> list[BillingSubscription]:
        data = await self._get(f"/subscriptions?telegram_id={telegram_id}")
        if isinstance(data, list):
            return [BillingSubscription.model_validate(s) for s in data]
        return []

    async def create_subscription(self, subscription_data: dict[str, Any]) -> BillingSubscription:
        data = await self._post("/subscriptions", json=subscription_data)
        return BillingSubscription.model_validate(data)

    async def update_subscription(
        self, subscription_id: int, subscription_data: dict[str, Any],
    ) -> BillingSubscription:
        data = await self._put(f"/subscriptions/{subscription_id}", json=subscription_data)
        return BillingSubscription.model_validate(data)

    async def get_subscription(self, subscription_id: int) -> Optional[BillingSubscription]:
        try:
            data = await self._get(f"/subscriptions/{subscription_id}")
            return BillingSubscription.model_validate(data) if data else None
        except BillingClientError as e:
            if e.status_code == 404:
                return None
            raise

    async def list_all_subscriptions(self) -> list[BillingSubscription]:
        data = await self._get("/subscriptions")
        if isinstance(data, list):
            return [BillingSubscription.model_validate(s) for s in data]
        return []

    # ------------------------------------------------------------------ #
    # Referrals (extended)
    # ------------------------------------------------------------------ #

    async def get_referral_stats(self, telegram_id: int) -> dict[str, Any]:
        data = await self._get(f"/referral/{telegram_id}/stats")
        return data if isinstance(data, dict) else {}

    async def list_referral_rewards(self, telegram_id: int) -> list[dict[str, Any]]:
        data = await self._get(f"/referral/{telegram_id}/rewards")
        return data if isinstance(data, list) else []

    # ------------------------------------------------------------------ #
    # Web Orders
    # ------------------------------------------------------------------ #

    async def claim_web_order(self, telegram_id: int, short_id: str) -> BillingWebOrderResult:
        data = await self._post("/web-order/claim", json={
            "telegram_id": telegram_id,
            "short_id": short_id,
        })
        return BillingWebOrderResult.model_validate(data)

    # ------------------------------------------------------------------ #
    # Settings
    # ------------------------------------------------------------------ #

    async def get_settings(self) -> BillingSettings:
        data = await self._get("/settings")
        return BillingSettings.model_validate(data)

    async def update_settings(self, settings_data: dict[str, Any]) -> BillingSettings:
        data = await self._put("/settings", json=settings_data)
        return BillingSettings.model_validate(data)

    async def get_default_currency(self) -> str:
        data = await self._get("/settings/default-currency")
        return data.get("currency", "") if data else ""

    async def set_default_currency(self, currency: str) -> None:
        await self._put("/settings/default-currency", json={"currency": currency})

    # ------------------------------------------------------------------ #
    # Statistics
    # ------------------------------------------------------------------ #

    async def get_statistics(self) -> BillingStatistics:
        data = await self._get("/statistics")
        return BillingStatistics.model_validate(data)

    # ------------------------------------------------------------------ #
    # Payment Gateways
    # ------------------------------------------------------------------ #

    async def list_gateways(self) -> list[BillingPaymentGateway]:
        data = await self._get("/gateways")
        return [BillingPaymentGateway.model_validate(g) for g in (data or [])]

    async def list_active_gateways(self) -> list[BillingPaymentGateway]:
        data = await self._get("/gateways/active")
        return [BillingPaymentGateway.model_validate(g) for g in (data or [])]

    async def get_gateway(self, gateway_id: int) -> Optional[BillingPaymentGateway]:
        try:
            data = await self._get(f"/gateways/{gateway_id}")
            return BillingPaymentGateway.model_validate(data) if data else None
        except BillingClientError as e:
            if e.status_code == 404:
                return None
            raise

    async def get_gateway_by_type(self, gateway_type: str) -> Optional[BillingPaymentGateway]:
        try:
            data = await self._get("/gateways/by-type", params={"type": gateway_type})
            return BillingPaymentGateway.model_validate(data) if data else None
        except BillingClientError as e:
            if e.status_code == 404:
                return None
            raise

    async def create_gateway(self, gateway_data: dict[str, Any]) -> BillingPaymentGateway:
        data = await self._post("/gateways", json=gateway_data)
        return BillingPaymentGateway.model_validate(data)

    async def update_gateway(self, gateway_data: dict[str, Any]) -> BillingPaymentGateway:
        data = await self._put("/gateways", json=gateway_data)
        return BillingPaymentGateway.model_validate(data)

    async def delete_gateway(self, gateway_id: int) -> bool:
        await self._delete("/gateways", json={"id": gateway_id})
        return True

    async def move_gateway_up(self, gateway_id: int) -> bool:
        await self._post(f"/gateways/{gateway_id}/move-up")
        return True

    async def create_test_payment(
        self, telegram_id: int, gateway_type: str
    ) -> BillingPaymentResult:
        data = await self._post("/gateways/test-payment", json={
            "telegram_id": telegram_id,
            "gateway_type": gateway_type,
        })
        return BillingPaymentResult.model_validate(data)

    # ------------------------------------------------------------------ #
    # Pricing
    # ------------------------------------------------------------------ #

    async def calculate_price(
        self,
        telegram_id: int,
        plan_id: int,
        duration_days: int,
        currency: str,
    ) -> BillingPriceDetails:
        data = await self._post("/pricing/calculate", json={
            "telegram_id": telegram_id,
            "plan_id": plan_id,
            "duration_days": duration_days,
            "currency": currency,
        })
        return BillingPriceDetails.model_validate(data)

    # ------------------------------------------------------------------ #
    # Referrals
    # ------------------------------------------------------------------ #

    async def link_referral(self, referrer_code: str, referred_telegram_id: int) -> None:
        await self._post("/referral/link", json={
            "referrer_code": referrer_code,
            "referred_telegram_id": referred_telegram_id,
        })

    async def get_referral_info(self, telegram_id: int) -> dict[str, Any]:
        data = await self._get(f"/referral/{telegram_id}")
        return data if data else {}

    async def create_referral(
        self,
        referrer_telegram_id: int,
        referred_telegram_id: int,
        level: str,
    ) -> BillingReferral:
        data = await self._post("/referrals", json={
            "referrer_telegram_id": referrer_telegram_id,
            "referred_telegram_id": referred_telegram_id,
            "level": level,
        })
        return BillingReferral.model_validate(data)

    async def get_referral_by_referred(self, telegram_id: int) -> Optional[BillingReferral]:
        data = await self._get(f"/referrals/by-referred/{telegram_id}")
        return BillingReferral.model_validate(data) if data else None

    async def get_referrals_by_referrer(self, telegram_id: int) -> list[BillingReferral]:
        data = await self._get(f"/referrals/by-referrer/{telegram_id}")
        return [BillingReferral.model_validate(r) for r in (data or [])]

    async def create_referral_reward(
        self,
        referral_id: int,
        user_telegram_id: int,
        type: str,
        amount: int,
    ) -> BillingReferralReward:
        data = await self._post("/referral/reward", json={
            "referral_id": referral_id,
            "user_telegram_id": user_telegram_id,
            "type": type,
            "amount": amount,
            "is_issued": False,
        })
        return BillingReferralReward.model_validate(data)

    async def update_referral_reward(self, reward_id: int, is_issued: bool) -> BillingReferralReward:
        data = await self._put(f"/referral/reward/{reward_id}", json={
            "is_issued": is_issued,
        })
        return BillingReferralReward.model_validate(data)

    async def get_rewards_by_referral(self, referral_id: int) -> list[BillingReferralReward]:
        data = await self._get(f"/referral/rewards-by-referral/{referral_id}")
        return [BillingReferralReward.model_validate(r) for r in (data or [])]

    # ------------------------------------------------------------------ #
    # TG Proxies
    # ------------------------------------------------------------------ #

    async def get_tg_proxies(self, plan_id: int) -> list[BillingTGProxy]:
        data = await self._get("/tg-proxies", params={"plan_id": plan_id})
        return [BillingTGProxy.model_validate(p) for p in (data or [])]
