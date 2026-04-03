"""Shared test fixtures for compono-telegram-shop.

Imports are kept minimal to avoid triggering AppConfig.get() which
requires real environment variables.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


# Provide minimal env vars so AppConfig.get() doesn't crash on import
_TEST_ENV = {
    "APP_DOMAIN": "test.example.com",
    "APP_CRYPT_KEY": "2cSMJmhhV37jeWxudf22CBBz9MDL5zu8vYAKQAReAUc=",
    "BOT_TOKEN": "123456:ABC-TEST",
    "BOT_SECRET_TOKEN": "testsecrettoken",
    "BOT_DEV_ID": "1",
    "BOT_SUPPORT_USERNAME": "test_support",
    "REMNAWAVE_TOKEN": "testtoken",
    "REMNAWAVE_WEBHOOK_SECRET": "testwebhooksecret",
    "DATABASE_HOST": "localhost",
    "DATABASE_PORT": "5432",
    "DATABASE_NAME": "test",
    "DATABASE_USER": "test",
    "DATABASE_PASSWORD": "test",
    "REDIS_HOST": "localhost",
    "REDIS_PORT": "6379",
    "REDIS_PASSWORD": "test",
    "APP_BILLING_API_URL": "http://localhost:8080",
    "APP_BILLING_INTERNAL_SECRET": "testsecret",
    "APP_LOCALES": "en",
    "APP_HYDRA_DOMAINS": "test.example.com",
}

for k, v in _TEST_ENV.items():
    os.environ.setdefault(k, v)


# Now safe to import app modules
from src.core.enums import PlanType, SubscriptionStatus, UserRole, Locale
from src.infrastructure.billing.models import BillingPlan, BillingSettings, BillingTGProxy
from src.models.dto.plan import PlanSnapshotDto
from src.models.dto.subscription import BaseSubscriptionDto
from src.models.dto.user import UserDto

from remnapy.enums import TrafficLimitStrategy


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def make_plan_snapshot(
    plan_id: int = 2,
    name: str = "🚀 Про",
    traffic_limit: int = 300,
    device_limit: int = 6,
) -> PlanSnapshotDto:
    return PlanSnapshotDto(
        id=plan_id,
        name=name,
        type=PlanType.BOTH,
        traffic_limit=traffic_limit,
        device_limit=device_limit,
        duration=30,
        traffic_limit_strategy=TrafficLimitStrategy.MONTH,
        internal_squads=[],
        external_squad=None,
    )


def make_subscription(
    plan_id: int = 2,
    plan_name: str = "🚀 Про",
    active: bool = True,
    traffic_limit: int = 300,
    device_limit: int = 6,
) -> BaseSubscriptionDto:
    expire_at = datetime.now(tz=timezone.utc) + timedelta(days=30) if active else datetime.now(tz=timezone.utc) - timedelta(days=1)
    return BaseSubscriptionDto(
        user_remna_id=uuid4(),
        status=SubscriptionStatus.ACTIVE if active else SubscriptionStatus.EXPIRED,
        is_trial=False,
        traffic_limit=traffic_limit,
        device_limit=device_limit,
        traffic_limit_strategy=TrafficLimitStrategy.MONTH,
        internal_squads=[],
        external_squad=None,
        expire_at=expire_at,
        url="https://panel.example.com/sub/abc123",
        plan=make_plan_snapshot(plan_id=plan_id, name=plan_name, traffic_limit=traffic_limit, device_limit=device_limit),
    )


def make_user(
    telegram_id: int = 1750352084,
    name: str = "Anton",
    subscription: Optional[BaseSubscriptionDto] = None,
) -> UserDto:
    return UserDto(
        telegram_id=telegram_id,
        name=name,
        role=UserRole.USER,
        language=Locale.RU,
        referral_code="abc123",
        current_subscription=subscription,
    )


# ---------------------------------------------------------------------------
# Mock billing client
# ---------------------------------------------------------------------------

def make_billing_client(
    trial_plan: Optional[BillingPlan] = None,
    has_used_trial: bool = True,
    settings: Optional[BillingSettings] = None,
    tg_proxies: Optional[list[BillingTGProxy]] = None,
    tg_proxies_error: Optional[Exception] = None,
) -> AsyncMock:
    billing = AsyncMock()
    billing.get_trial_plan.return_value = trial_plan
    billing.has_used_trial.return_value = has_used_trial
    billing.get_settings.return_value = settings or BillingSettings()

    if tg_proxies_error:
        billing.get_tg_proxies.side_effect = tg_proxies_error
    else:
        billing.get_tg_proxies.return_value = tg_proxies or []

    return billing


def make_referral_service() -> AsyncMock:
    svc = AsyncMock()
    svc.get_ref_link.return_value = "https://t.me/compono_bot?start=REF_abc123"
    return svc


def make_config() -> MagicMock:
    config = MagicMock()
    config.bot.support_username.get_secret_value.return_value = "compono_support"
    config.bot.is_mini_app = False
    config.remnawave.sub_public_domain = "componovpn.com"
    config.hydra_primary_domain = "componovpn.com"
    return config


def make_i18n() -> MagicMock:
    i18n = MagicMock()
    i18n.get.side_effect = lambda key, **kwargs: f"[{key}]"
    return i18n


def unwrap_inject(fn):
    """Extract the original function from dishka's @inject wrapper."""
    if fn.__closure__:
        for cell in fn.__closure__:
            try:
                val = cell.cell_contents
                if callable(val) and getattr(val, '__name__', None) == fn.__name__:
                    return val
            except ValueError:
                pass
    return fn


def make_dialog_manager() -> MagicMock:
    dm = MagicMock()
    dm.dialog_data = {}
    dm.middleware_data = {}
    return dm
