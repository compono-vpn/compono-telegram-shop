"""Regression tests for the legacy `/api/v1/app/*` web-buyer portal surface.

PR #10 split the web purchase flow out of the Telegram shop. The portal API
now lives on `app.componovpn.com` (served by compono-billing/compono-api). The
old in-process router previously exposed:

  - POST /api/v1/app/auth/send
  - POST /api/v1/app/auth/verify
  - GET  /api/v1/app/me

These were the only consumers of `BillingPortalLookup` and the `EmailService`
OTP helpers. Removing them keeps the bot Telegram-native only and prevents the
stale `has_subscription` field from drifting against billing's current
`/portal/lookup` response shape (which is now just `{subscription_url}`).

Reviewer audit confirmed (PR #10 P2 follow-up):

  - `/api/v1/app/*` had no Telegram-native WebApp consumer in this repo.
  - The bot's optional WebApp button (`BOT_MINI_APP`) is unset in prod and
    points to an external URL when set; it does not call these endpoints.
  - `compono-landing` (`app.componovpn.com`) talks to a different host
    (`stage-api.componovpn.com` / billing) and uses `/api/v1/auth/...` and
    `/api/v1/me`, not `/api/v1/app/*`.

These tests guard against accidental reintroduction.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_app_endpoint_module_is_gone() -> None:
    """The `src.api.endpoints.app` module must not exist anymore."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("src.api.endpoints.app")


def test_endpoints_package_does_not_export_app_router() -> None:
    """The endpoints package must not re-export the legacy `app_router`."""
    endpoints_pkg = importlib.import_module("src.api.endpoints")
    assert not hasattr(endpoints_pkg, "app_router")
    assert "app_router" not in getattr(endpoints_pkg, "__all__", [])


def test_email_service_module_is_gone() -> None:
    """The `src.services.email` module (OTP/welcome emails) must be removed."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("src.services.email")


def test_billing_models_no_longer_export_portal_lookup() -> None:
    """`BillingPortalLookup` was the response model for the legacy /me path.

    Billing's current /portal/lookup returns only `{subscription_url}`; rather
    than aligning a now-unused model, we remove it together with its only
    caller (`BillingClient.portal_lookup`).
    """
    models = importlib.import_module("src.infrastructure.billing.models")
    assert not hasattr(models, "BillingPortalLookup")


def test_billing_client_no_longer_exposes_portal_lookup() -> None:
    client_mod = importlib.import_module("src.infrastructure.billing.client")
    assert not hasattr(client_mod.BillingClient, "portal_lookup")


def test_no_module_under_src_imports_pyjwt() -> None:
    """We removed the only consumer of PyJWT (`/api/v1/app/auth/verify`).

    Catch any sneaky reintroduction at the import-graph level rather than
    waiting for runtime ImportError.
    """
    src_pkg = importlib.import_module("src")
    offenders: list[str] = []
    for module_info in pkgutil.walk_packages(src_pkg.__path__, prefix="src."):
        try:
            mod = importlib.import_module(module_info.name)
        except Exception:  # noqa: BLE001 -- we only care about successful imports
            continue
        source = getattr(mod, "__file__", None)
        if not source:
            continue
        try:
            with open(source, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        # Guard against `import jwt` and `from jwt import ...`.
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("import jwt") or stripped.startswith("from jwt"):
                offenders.append(module_info.name)
                break
    assert offenders == [], f"Unexpected pyjwt imports found in: {offenders}"


def test_legacy_app_routes_return_404_on_minimal_fastapi_app() -> None:
    """End-to-end safety net: spin up the only routers we still ship and
    confirm none of the legacy `/api/v1/app/*` paths are reachable."""
    from src.api.endpoints import health_router

    app = FastAPI()
    app.include_router(health_router)

    client = TestClient(app)

    # POST endpoints first (auth/send, auth/verify) -> 404 (route absent).
    for path in ("/api/v1/app/auth/send", "/api/v1/app/auth/verify"):
        resp = client.post(path, json={"email": "x@example.com"})
        assert resp.status_code == 404, (path, resp.status_code, resp.text)

    # GET /api/v1/app/me -> 404 (route absent).
    resp = client.get("/api/v1/app/me")
    assert resp.status_code == 404, resp.text
