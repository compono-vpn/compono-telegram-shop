"""Every payment link the bot creates is queued for the 5-minute nudge."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.routers.subscription.handlers import _create_payment_and_get_data
from src.core.constants import USER_KEY
from src.core.enums import PaymentGatewayType, PurchaseType
from src.core.storage.keys import PaymentNudgeDataKey, PendingPaymentNudgesKey
from src.models.dto import PlanDto
from src.models.dto.plan import PlanDurationDto
from tests.conftest import make_dialog_manager, make_user

PAYMENT_ID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"


class _Redis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.zsets: dict[str, dict[str, float]] = {}

    async def set(self, key, value, nx=False, ex=None):
        self.values[key] = value
        return True

    async def zadd(self, key, mapping, nx=False):
        self.zsets.setdefault(key, {}).update(mapping)
        return len(mapping)


def _plan() -> PlanDto:
    return PlanDto(id=7, name="⚡️ Старт", durations=[PlanDurationDto(id=1, days=30, prices=[])])


def _dm() -> MagicMock:
    dm = make_dialog_manager()
    dm.middleware_data[USER_KEY] = make_user(telegram_id=777)
    dm.middleware_data["bot"] = MagicMock()
    dm.dialog_data["purchase_type"] = PurchaseType.NEW
    return dm


def _billing(url="", currency="XTR", final="119") -> AsyncMock:
    billing = AsyncMock()
    billing.get_gateway_by_type.return_value = MagicMock(Currency=currency)
    billing.create_payment.return_value = MagicMock(ID=PAYMENT_ID, URL=url)
    billing.calculate_price.return_value = MagicMock(
        original_amount="119", discount_percent=0, final_amount=final
    )
    return billing


@pytest.fixture(autouse=True)
def _invoice(monkeypatch):
    link = AsyncMock(return_value="https://t.me/$invoice")
    monkeypatch.setattr("src.bot.routers.subscription.handlers.create_stars_invoice_link", link)
    return link


async def _create(redis, billing, gateway=PaymentGatewayType.TELEGRAM_STARS):
    return await _create_payment_and_get_data(
        dialog_manager=_dm(),
        plan=_plan(),
        duration_days=30,
        gateway_type=gateway,
        billing=billing,
        notification_service=AsyncMock(),
        redis_client=redis,
        experiment_service=None,
    )


async def test_stars_payment_is_queued_with_the_invoice_link():
    redis = _Redis()

    result = await _create(redis, _billing())

    assert result is not None
    queue = redis.zsets[PendingPaymentNudgesKey().pack()]
    assert list(queue) == [f"{PAYMENT_ID}:777"]
    stored = redis.values[PaymentNudgeDataKey(payment_id=PAYMENT_ID).pack()]
    assert "https://t.me/$invoice" in stored
    assert "119 ★" in stored


async def test_a_redis_failure_does_not_break_payment_creation():
    redis = AsyncMock()
    redis.zadd.side_effect = [1, RuntimeError("redis down")]
    redis.set.return_value = True

    result = await _create(redis, _billing())

    assert result is not None
    assert result["payment_url"] == "https://t.me/$invoice"


@pytest.mark.parametrize(
    "gateway",
    [
        PaymentGatewayType.PLATEGA,
        PaymentGatewayType.PLATEGA_CRYPTO,
        PaymentGatewayType.YOOKASSA,
        PaymentGatewayType.TON,
        PaymentGatewayType.PLAIDLY,
        "PLATEGA",
    ],
)
async def test_a_non_stars_gateway_never_reaches_billing_or_the_nudge(gateway):
    redis = _Redis()
    billing = _billing(url="https://pay.platega.io/x", currency="RUB")

    result = await _create(redis, billing, gateway)

    assert result is None
    billing.create_payment.assert_not_awaited()
    assert redis.zsets == {}
