"""Run the real shop bot (uvicorn, webhook mode) against tgmock's fake Bot API.

Pieces started per session:
- ``redis-server`` on a free port (the bot's FSM, dialog stacks, taskiq stream),
- tgmock's ``TelegramMockServer`` with failure injection for chosen Bot API methods
  and a catch-all for methods tgmock does not model,
- ``FakeBilling`` for the compono-api internal routes,
- the shop itself: ``uvicorn src.__main__:application --factory``.

Nothing here talks to the real Telegram, billing or Remnawave.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, web
from redis.asyncio import Redis
from tgmock.server import TelegramMockServer, read_telegram_request

from .fake_billing import FakeBilling

REPO_ROOT = Path(__file__).resolve().parents[2]
BOT_ID = 424242
BOT_TOKEN = f"{BOT_ID}:e2e-local-only"
SECRET = "e2e-webhook-secret"
DEV_ID = 111000111


def redis_server_binary() -> str | None:
    """A redis-server that runs here (an x86 build on Apple silicon without Rosetta does not)."""
    for candidate in (os.environ.get("SHOP_E2E_REDIS_SERVER"), shutil.which("redis-server")):
        if not candidate:
            continue
        try:
            if subprocess.run([candidate, "--version"], capture_output=True).returncode == 0:
                return candidate
        except OSError:
            continue
    return None


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class FailingTelegram(TelegramMockServer):
    """tgmock server that records every Bot API call and can fail chosen methods."""

    def __init__(self, token: str, port: int) -> None:
        super().__init__(token=token, port=port)
        self.calls: list[dict[str, Any]] = []
        # method -> (error_code, description); applied to every call of that method
        self.failures: dict[str, tuple[int, str]] = {}
        # createInvoiceLink requests (Telegram Stars invoices) in order
        self.invoices: list[dict[str, Any]] = []

    def build_app(self) -> web.Application:
        app = super().build_app()
        app.router.add_post("/bot{token}/createInvoiceLink", self._create_invoice_link)
        # Catch-all for methods tgmock does not implement (setMyCommands variants, etc.).
        app.router.add_post("/bot{token}/{method}", self._catch_all)

        @web.middleware
        async def _record_and_fail(request: web.Request, handler: Any) -> web.StreamResponse:
            if request.path.startswith("/bot"):
                method = request.path.rsplit("/", 1)[-1]
                try:
                    data = await read_telegram_request(request)
                except Exception:
                    data = {}
                self.calls.append({"method": method, "data": data, "at": time.time()})
                if method in self.failures:
                    code, description = self.failures[method]
                    return web.json_response(
                        {"ok": False, "error_code": code, "description": description},
                        status=code,
                    )
            return await handler(request)

        app.middlewares.append(_record_and_fail)
        return app

    def _record_response(self, chat_id: int, record: dict) -> None:
        record["_at"] = time.time()
        super()._record_response(chat_id, record)

    async def _handle_send_media(
        self, request: web.Request, method: str, media_key: str
    ) -> web.Response:
        # tgmock echoes an uploaded file as {"file_id": "attach://..."}; aiogram needs
        # file_unique_id (and photo as a list of sizes) to parse the returned Message.
        response = await super()._handle_send_media(request, method, media_key)
        body = json.loads(response.body)  # type: ignore[arg-type]
        media = dict(body["result"].get(media_key) or {})
        media["file_id"] = f"mock_{media_key}_{body['result']['message_id']}"
        media.setdefault("file_unique_id", media["file_id"])
        if media_key == "photo":
            media.update(width=1, height=1)
            body["result"][media_key] = [media]
        else:
            body["result"][media_key] = media
        return web.json_response(body)

    async def _create_invoice_link(self, request: web.Request) -> web.Response:
        data = await read_telegram_request(request)
        prices = data.get("prices")
        if isinstance(prices, str):
            prices = json.loads(prices)
        invoice = {**data, "prices": prices, "link": f"https://t.me/$e2e-{len(self.invoices) + 1}"}
        self.invoices.append(invoice)
        return web.json_response({"ok": True, "result": invoice["link"]})

    async def _catch_all(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "result": True})

    def calls_of(self, method: str, since: float = 0.0) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["method"] == method and c["at"] >= since]


class ShopE2E:
    def __init__(self) -> None:
        self.tg_port = free_port()
        self.redis_port = free_port()
        self.shop_port = free_port()
        self.tg = FailingTelegram(token=BOT_TOKEN, port=self.tg_port)
        self.billing = FakeBilling()
        self._tg_runner: web.AppRunner | None = None
        self._redis: subprocess.Popen[bytes] | None = None
        self._shop: subprocess.Popen[bytes] | None = None
        self._tmp = Path(tempfile.mkdtemp(prefix="shop-e2e-"))
        self.log_path = self._tmp / "shop.log"
        self._log_file: Any = None

    # ------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        self._start_redis()
        self._tg_runner = await self.tg.start()
        await self.billing.start()
        await self._wait_redis()

        env = {
            **{k: v for k, v in os.environ.items() if not k.startswith(("APP_", "BOT_", "REDIS_"))},
            "PYTHONUNBUFFERED": "1",
            "APP_DOMAIN": "shop.e2e.example.com",
            "APP_HOST": "127.0.0.1",
            "APP_PORT": str(self.shop_port),
            "APP_LOCALES": "ru",
            "APP_DEFAULT_LOCALE": "ru",
            "APP_CRYPT_KEY": "2cSMJmhhV37jeWxudf22CBBz9MDL5zu8vYAKQAReAUc=",
            "APP_API_URL": self.billing.url,
            "APP_API_INTERNAL_SECRET": "e2e",
            "APP_BILLING_URL": self.billing.url,
            "APP_KAFKA_BROKERS": f"127.0.0.1:{free_port()}",
            "APP_KAFKA_TOPIC_ENV": "e2e",
            "APP_WIDGETS_ENABLED": "false",
            "BOT_TOKEN": BOT_TOKEN,
            "BOT_SECRET_TOKEN": SECRET,
            "BOT_DEV_ID": str(DEV_ID),
            "BOT_SUPPORT_USERNAME": "e2e_support",
            "BOT_SUPPORT_CHAT_ID": str(DEV_ID),
            "BOT_API_SERVER": f"http://localhost:{self.tg_port}",
            "BOT_USE_BANNERS": "false",
            "BOT_SETUP_COMMANDS": "false",
            "REMNAWAVE_HOST": f"{self.billing.url}/remnawave",
            "REMNAWAVE_TOKEN": "e2e",
            "REMNAWAVE_WEBHOOK_SECRET": "e2e",
            "REDIS_HOST": "127.0.0.1",
            "REDIS_PORT": str(self.redis_port),
            "REDIS_PASSWORD": "e2e",
            "REDIS_NAME": "0",
        }
        self._log_file = open(self.log_path, "wb")
        self._shop = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "src.__main__:application",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.shop_port),
            ],
            cwd=REPO_ROOT,
            env=env,
            stdout=self._log_file,
            stderr=subprocess.STDOUT,
        )
        await self._wait_ready()
        # The bot registers https://APP_DOMAIN/...; point tgmock at the local uvicorn instead.
        async with ClientSession() as s:
            await s.post(
                f"http://localhost:{self.tg_port}/test/set-webhook",
                json={
                    "url": f"http://127.0.0.1:{self.shop_port}/api/v1/telegram",
                    "secret_token": SECRET,
                },
            )

    def _start_redis(self) -> None:
        """A local redis-server (``SHOP_E2E_REDIS_SERVER`` or the one on PATH), no persistence."""
        self._redis = subprocess.Popen(
            [
                redis_server_binary(),
                "--port",
                str(self.redis_port),
                "--bind",
                "127.0.0.1",
                "--save",
                "",
                "--appendonly",
                "no",
                "--requirepass",
                "e2e",
                "--dir",
                str(self._tmp),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    async def stop(self) -> None:
        if self._shop and self._shop.poll() is None:
            self._shop.terminate()
            try:
                self._shop.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self._shop.kill()
        if self._log_file:
            self._log_file.close()
        await self.billing.stop()
        if self._tg_runner:
            await self._tg_runner.cleanup()
        if self._redis and self._redis.poll() is None:
            self._redis.terminate()
            self._redis.wait(timeout=10)

    async def _wait_port(self, port: int, timeout: float = 10) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                _, w = await asyncio.open_connection("127.0.0.1", port)
                w.close()
                return
            except OSError:
                await asyncio.sleep(0.1)
        raise RuntimeError(f"port {port} did not open")

    async def _wait_redis(self, timeout: float = 30) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if await self.redis("PING"):
                    return
            except Exception:
                await asyncio.sleep(0.2)
        raise RuntimeError("redis did not come up")

    async def _wait_ready(self, timeout: float = 60) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._shop and self._shop.poll() is not None:
                raise RuntimeError(f"shop exited early:\n{self.log()[-4000:]}")
            if "Application startup complete" in self.log():
                return
            await asyncio.sleep(0.2)
        raise RuntimeError(f"shop did not start:\n{self.log()[-4000:]}")

    # ------------------------------------------------------------- helpers

    def log(self) -> str:
        try:
            return self.log_path.read_text(errors="replace")
        except FileNotFoundError:
            return ""

    async def send_update(self, update: dict[str, Any]) -> int:
        """POST one update straight to the bot's webhook, like Telegram does."""
        async with ClientSession() as s:
            async with s.post(
                f"http://127.0.0.1:{self.shop_port}/api/v1/telegram",
                json=update,
                headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
            ) as resp:
                return resp.status

    async def redis(self, *args: str) -> Any:
        client = Redis(
            host="127.0.0.1", port=self.redis_port, password="e2e", decode_responses=True
        )
        try:
            return await client.execute_command(*args)
        finally:
            await client.aclose()

    async def wait_for(self, predicate: Any, timeout: float = 15, interval: float = 0.2) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            await asyncio.sleep(interval)
        return bool(predicate())
