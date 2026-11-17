"""In-memory stand-in for the compono-api/compono-billing internal routes the bot calls.

Only the routes the e2e flows touch are modelled; every other path answers 404 and is recorded in
``unknown`` so a test (or a person reading the transcript) can see what the bot asked for.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any

from aiohttp import web

PREFIX = "/api/v1/internal"
# Real stage responses (plans, trial plan, active gateways with Settings removed), 2026-11-17.
STAGE: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "billing_stage.json").read_text(encoding="utf-8")
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FakeBilling:
    def __init__(self) -> None:
        self.users: dict[int, dict[str, Any]] = {}
        self.transactions: dict[str, dict[str, Any]] = {}
        self.subscriptions: dict[int, dict[str, Any]] = {}
        self.calls: list[tuple[str, str]] = []
        self.unknown: list[tuple[str, str]] = []
        # Gateway rows /gateways/active returns (stage copy; a test may add prod-like rows).
        self.gateways: list[dict[str, Any]] = [dict(g) for g in STAGE["gateways_active"]]
        # Plans sold in the plan list on top of the stage ones, and plans only reachable by id.
        self.extra_plans: list[dict[str, Any]] = []
        self.hidden_plans: list[dict[str, Any]] = []
        self.discounts: dict[int, int] = {}  # telegram_id -> purchase discount percent
        self.promocodes: dict[str, int] = {}  # code -> PURCHASE_DISCOUNT percent
        self.personal_proxies: dict[int, dict[str, Any]] = {}
        self.created: list[dict[str, Any]] = []  # POST /payment/create bodies + the result
        self.completed: list[str] = []  # payment ids sent to /payment/handle-free
        self.completion_delay = 0.7  # seconds until the "consumer" completes a handle-free payment
        # "<METHOD> <path>" -> how many next requests answer 503 (billing restarting).
        self.fail_next: dict[str, int] = {}
        self.port = 0
        self._runner: web.AppRunner | None = None

    # ---------------------------------------------------------------- data

    def add_user(self, telegram_id: int, name: str, role: str = "USER") -> None:
        self.users[telegram_id] = {
            "ID": len(self.users) + 1,
            "TelegramID": telegram_id,
            "Username": None,
            "ReferralCode": f"ref{telegram_id}",
            "Name": name,
            "Role": role,
            "Language": "ru",
            "Source": "e2e",
            "IsRulesAccepted": True,
            "CurrentSubscriptionID": None,
            "CreatedAt": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
            "UpdatedAt": _now(),
        }

    def add_active_subscription(
        self,
        telegram_id: int,
        *,
        plan_id: int = 1,
        plan_name: str = "⚡️ Старт",
        tag: str | None = None,
        days_left: int = 20,
    ) -> None:
        """Paid subscription, shaped like stage GET /subscription/{id}/current."""
        sub_id = 100 + len(self.subscriptions)
        self.subscriptions[telegram_id] = {
            "ID": sub_id,
            "UserRemnaID": str(uuid.UUID(int=telegram_id)),
            "UserTelegramID": telegram_id,
            "Status": "ACTIVE",
            "IsTrial": False,
            "TrafficLimit": 100,
            "DeviceLimit": 2,
            "TrafficLimitStrategy": "MONTH",
            "Tag": tag,
            "InternalSquads": ["683111d4-ab20-4422-a74b-559bb4501dc4"],
            "ExternalSquad": None,
            "ExpireAt": (datetime.now(timezone.utc) + timedelta(days=days_left)).isoformat(),
            "URL": f"https://componovpn.com/api/sub/e2e{telegram_id}",
            "Plan": {
                "id": plan_id,
                "name": plan_name,
                "tag": tag,
                "type": "BOTH",
                "traffic_limit": 100,
                "device_limit": 2,
                "duration": 30,
                "traffic_limit_strategy": "MONTH",
                "internal_squads": ["683111d4-ab20-4422-a74b-559bb4501dc4"],
            },
            "CreatedAt": _now(),
            "UpdatedAt": _now(),
        }
        self.users[telegram_id]["CurrentSubscriptionID"] = sub_id

    def add_transaction(self, payment_id: str, telegram_id: int, gateway: str) -> None:
        self.transactions[payment_id] = {
            "ID": len(self.transactions) + 1,
            "PaymentID": payment_id,
            "UserTelegramID": telegram_id,
            "Status": "CANCELED",
            "PurchaseType": "NEW",
            "GatewayType": gateway,
            "Currency": "RUB",
            "Pricing": {"original_amount": "119", "final_amount": "119"},
            "CreatedAt": _now(),
            "UpdatedAt": _now(),
        }

    # ---------------------------------------------------------------- http

    @staticmethod
    def _settings() -> dict[str, Any]:
        return {
            "ID": 1,
            "RulesRequired": False,
            "ChannelRequired": False,
            "AccessMode": "PUBLIC",
            "PurchasesAllowed": True,
            "RegistrationAllowed": True,
            "DefaultCurrency": "RUB",
            "UserNotifications": {},
            "SystemNotifications": {},
            "Referral": {"enable": False, "level": 1, "accrual_strategy": "ON_FIRST_PAYMENT"},
        }

    def _available(self) -> list[dict[str, Any]]:
        return [*STAGE["plans_available"], *self.extra_plans]

    def _plan(self, plan_id: int) -> dict[str, Any] | None:
        for plan in [*self._available(), *self.hidden_plans, STAGE["plan_trial"]]:
            if plan["ID"] == plan_id:
                return plan
        return None

    def _price(self, body: dict[str, Any]) -> str | None:
        plan = self._plan(int(body.get("plan_id", 0)))
        for duration in (plan or {}).get("Durations", []):
            if duration["Days"] == int(body.get("duration_days", 0)):
                for price in duration["Prices"]:
                    if price["Currency"] == body.get("currency"):
                        return str(price["Price"])
        return None

    def _pricing(self, body: dict[str, Any]) -> dict[str, Any] | None:
        """Like billing: a user's purchase discount, whole stars floored; proxy plans undiscounted."""
        price = self._price(body)
        if price is None:
            return None
        plan = self._plan(int(body.get("plan_id", 0))) or {}
        discount = (
            0
            if plan.get("Type") == "PROXY"
            else self.discounts.get(int(body.get("telegram_id", 0)), 0)
        )
        original = Decimal(price)
        final = original * (100 - discount) / 100
        if body.get("currency") in ("XTR", "RUB"):
            final = final.to_integral_value(rounding=ROUND_FLOOR)
        return {
            "original_amount": str(original.normalize()),
            "discount_percent": discount,
            "final_amount": str(final.normalize()),
        }

    def _gateway_by_type(self, gateway_type: str) -> dict[str, Any] | None:
        rows = [g for g in self.gateways if g["Type"] == gateway_type and g["IsActive"]]
        rows.sort(key=lambda g: g["Channel"] != "BOT")
        return rows[0] if rows else None

    def _create_payment(self, body: dict[str, Any]) -> dict[str, Any]:
        payment_id = str(uuid.uuid4())
        gateway = body.get("gateway_type", "")
        pricing = self._pricing(body) or {"original_amount": "0", "final_amount": "0"}
        plan = self._plan(int(body.get("plan_id", 0))) or {}
        self.transactions[payment_id] = {
            "ID": len(self.transactions) + 1,
            "PaymentID": payment_id,
            "UserTelegramID": int(body.get("telegram_id", 0)),
            "Status": "PENDING",
            "PurchaseType": body.get("purchase_type", "NEW"),
            "GatewayType": gateway,
            "Currency": body.get("currency", ""),
            "Pricing": pricing,
            "Plan": {
                "id": plan.get("ID", 0),
                "name": plan.get("Name", ""),
                "tag": plan.get("Tag"),
                "type": plan.get("Type", "BOTH"),
                "duration": int(body.get("duration_days", 0)),
            },
            "CreatedAt": _now(),
            "UpdatedAt": _now(),
        }
        # Billing returns no URL for Stars (the bot makes the invoice link itself).
        url = None if gateway == "TELEGRAM_STARS" else f"https://pay.platega.io/{payment_id}"
        result = {"ID": payment_id, "URL": url}
        self.created.append({**body, **result})
        return result

    @staticmethod
    def _not_found() -> web.Response:
        return web.json_response({"error": "not found"}, status=404)

    async def _handle(self, request: web.Request) -> web.Response:  # noqa: C901
        path = request.path
        method = request.method
        self.calls.append((method, request.path_qs))
        failing = f"{method} {path[len(PREFIX) :]}"
        if self.fail_next.get(failing, 0) > 0:
            self.fail_next[failing] -= 1
            return web.json_response({"error": "unavailable"}, status=503)
        if not path.startswith(PREFIX):
            # Remnawave and anything else is not available in the e2e.
            self.unknown.append((method, request.path_qs))
            return self._not_found()
        route = path[len(PREFIX) :]
        body: Any = None
        if request.can_read_body:
            try:
                body = await request.json()
            except json.JSONDecodeError:
                body = None

        if method == "GET" and route == "/settings":
            return web.json_response(self._settings())
        if method == "GET" and route == "/settings/default-currency":
            return web.json_response({"currency": "RUB"})
        if m := re.fullmatch(r"/users/(\d+)", route):
            tid = int(m.group(1))
            if method == "GET":
                return (
                    web.json_response(self.users[tid]) if tid in self.users else self._not_found()
                )
            if method == "PUT" and tid in self.users:
                return web.json_response(self.users[tid])
        if method == "GET" and route == "/users":
            role = request.query.get("role")
            if role:
                return web.json_response([u for u in self.users.values() if u["Role"] == role])
            return web.json_response({"count": len(self.users)})
        if m := re.fullmatch(r"/transactions/detail/([0-9a-f-]+)", route):
            tx = self.transactions.get(m.group(1))
            return web.json_response(tx) if tx else self._not_found()
        if m := re.fullmatch(r"/transactions/(\d+)", route):
            tid = int(m.group(1))
            return web.json_response(
                [t for t in self.transactions.values() if t["UserTelegramID"] == tid]
            )
        # Billing answers 200 null when the user has no subscription.
        if m := re.fullmatch(r"/subscription/(\d+)/current", route):
            return web.json_response(self.subscriptions.get(int(m.group(1))))
        if re.fullmatch(r"/subscription/\d+/trial-used", route):
            return web.json_response({"used": True})
        if route in ("/plans", "/plans/allowed", "/plans/available"):
            return web.json_response(self._available())
        if m := re.fullmatch(r"/plans/(\d+)", route):
            plan = self._plan(int(m.group(1)))
            return web.json_response(plan) if plan else self._not_found()
        if route == "/plans/trial":
            return web.json_response(STAGE["plan_trial"])
        if route == "/gateways/active":
            return web.json_response([g for g in self.gateways if g["IsActive"]])
        if route == "/gateways/by-type":
            row = self._gateway_by_type(request.query.get("type", ""))
            return web.json_response(row) if row else self._not_found()
        if route == "/tg-proxies":
            return web.json_response([])
        if m := re.fullmatch(r"/tg-proxies/personal/(\d+)", route):
            return web.json_response(
                self.personal_proxies.get(int(m.group(1)), {"entitled": False, "proxies": []})
            )
        if method == "POST" and route == "/pricing/calculate":
            pricing = self._pricing(body or {})
            return web.json_response(pricing) if pricing else self._not_found()
        if method == "POST" and route == "/payment/create":
            return web.json_response(self._create_payment(body or {}))
        if method == "POST" and route == "/payment/handle-free":
            payment_id = (body or {}).get("payment_id", "")

            # Like billing: handle-free only queues a Kafka event and the consumer completes the
            # payment a moment later (PaymentUseCase.HandleFreePayment). Like TransitionStatus, only
            # a PENDING payment completes; others are skipped.
            def _complete() -> None:
                tx = self.transactions.get(payment_id)
                if tx is not None and tx.get("Status") == "PENDING":
                    tx["Status"] = "COMPLETED"

            asyncio.get_running_loop().call_later(self.completion_delay, _complete)
            self.completed.append(payment_id)
            return web.json_response({})
        if method == "POST" and route == "/promocode/activate":
            code = str((body or {}).get("code", "")).upper()
            if code not in self.promocodes:
                return self._not_found()
            self.discounts[int((body or {}).get("telegram_id", 0))] = self.promocodes[code]
            return web.json_response({})
        if re.fullmatch(r"/user-reminders/\d+", route):
            return web.json_response([])
        if method == "POST" and route == "/user-reminders/claim":
            return web.json_response({"claimed": True})

        self.unknown.append((method, request.path_qs))
        return self._not_found()

    async def start(self) -> None:
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self._handle)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"
