"""In-memory stand-in for the compono-api/compono-billing internal routes the bot calls.

Only the routes the e2e flows touch are modelled; every other path answers 404 and is recorded in
``unknown`` so a test (or a person reading the transcript) can see what the bot asked for.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, web

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
        # JSON bodies of POST/PUT calls, in order: (method, path, body).
        self.bodies: list[tuple[str, str, Any]] = []
        # TV pairing (compono-api internal claim). With ``tv_pair_api`` set, the claim
        # is forwarded to a real compono-api; otherwise an in-memory model of the
        # contract answers it from ``tv_codes`` (code -> {"tg": id or None}).
        self.tv_pair_api: str | None = None
        self.tv_codes: dict[str, dict[str, Any]] = {}
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

    def add_active_subscription(self, telegram_id: int) -> None:
        """Paid Старт subscription, shaped like stage GET /subscription/{id}/current."""
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
            "Tag": None,
            "InternalSquads": ["683111d4-ab20-4422-a74b-559bb4501dc4"],
            "ExternalSquad": None,
            "ExpireAt": (datetime.now(timezone.utc) + timedelta(days=20)).isoformat(),
            "URL": f"https://componovpn.com/api/sub/e2e{telegram_id}",
            "Plan": {
                "id": 1,
                "name": "⚡️ Старт",
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

    @staticmethod
    def _plan(plan_id: int) -> dict[str, Any] | None:
        for plan in [*STAGE["plans_available"], STAGE["plan_trial"]]:
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

    @staticmethod
    def _not_found() -> web.Response:
        return web.json_response({"error": "not found"}, status=404)

    async def _handle(self, request: web.Request) -> web.Response:  # noqa: C901
        path = request.path
        method = request.method
        self.calls.append((method, request.path_qs))
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
        if method in ("POST", "PUT"):
            self.bodies.append((method, route, body))

        if method == "POST" and route == "/tv-pair/claim":
            return await self._tv_pair_claim(request, body or {})
        if method == "GET" and route == "/settings":
            return web.json_response(self._settings())
        if method == "GET" and route == "/settings/default-currency":
            return web.json_response({"currency": "RUB"})
        if m := re.fullmatch(r"/users/(\d+)", route):
            tid = int(m.group(1))
            if method == "GET":
                # Real billing answers 200 null for an unknown user (InternalHandler.GetUser).
                return web.json_response(self.users.get(tid))
            if method == "PUT" and tid in self.users:
                return web.json_response(self.users[tid])
        if method == "POST" and route == "/users" and isinstance(body, dict):
            # New bot user (UserService.create, then the middleware's sync call).
            tid = int(body["telegram_id"])
            if tid not in self.users:
                self.add_user(tid, str(body.get("name") or tid), role=body.get("role") or "USER")
                self.users[tid]["Source"] = body.get("source")
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
            return web.json_response(STAGE["plans_available"])
        if m := re.fullmatch(r"/plans/(\d+)", route):
            plan = self._plan(int(m.group(1)))
            return web.json_response(plan) if plan else self._not_found()
        if route == "/plans/trial":
            return web.json_response(STAGE["plan_trial"])
        if route == "/gateways/active":
            return web.json_response(STAGE["gateways_active"])
        if route == "/tg-proxies":
            return web.json_response([])
        if re.fullmatch(r"/tg-proxies/personal/\d+", route):
            return web.json_response({"entitled": False, "proxies": []})
        if method == "POST" and route == "/pricing/calculate":
            price = self._price(body or {})
            if price is None:
                return self._not_found()
            return web.json_response(
                {"original_amount": price, "discount_percent": 0, "final_amount": price}
            )

        self.unknown.append((method, request.path_qs))
        return self._not_found()

    def _eligible(self, telegram_id: int) -> bool:
        sub = self.subscriptions.get(telegram_id)
        if not sub or sub.get("Status") != "ACTIVE" or not sub.get("URL"):
            return False
        return datetime.fromisoformat(sub["ExpireAt"]) > datetime.now(timezone.utc)

    async def _tv_pair_claim(self, request: web.Request, body: dict[str, Any]) -> web.Response:
        if self.tv_pair_api:
            async with ClientSession() as s:
                async with s.post(
                    f"{self.tv_pair_api}{PREFIX}/tv-pair/claim",
                    json=body,
                    headers={"X-Internal-Secret": request.headers.get("X-Internal-Secret", "")},
                ) as resp:
                    return web.Response(
                        status=resp.status,
                        body=await resp.read(),
                        content_type="application/json",
                    )
        # In-memory model of TV pairing contract v1 (claim side only).
        code = str(body.get("code", "")).upper().replace("-", "")
        tg = body.get("telegramId")
        entry = self.tv_codes.get(code)
        if entry is None:
            return web.json_response({"error": "code_not_found"}, status=404)
        if entry["tg"] is not None:
            if entry["tg"] == tg:
                return web.json_response({"status": "attached", "expiresAt": entry["expiresAt"]})
            return web.json_response({"error": "code_already_claimed"}, status=409)
        if not self._eligible(int(tg)):
            return web.json_response({"error": "no_active_subscription"}, status=422)
        entry["tg"] = tg
        return web.json_response({"status": "attached", "expiresAt": entry["expiresAt"]})

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
