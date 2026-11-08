from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.services.stars_invoice import create_stars_invoice_link, stars_amount


def test_stars_amount_requires_whole_positive_stars():
    assert stars_amount(Decimal("119")) == 119
    assert stars_amount(Decimal("119.00")) == 119
    for bad in (Decimal("0"), Decimal("118.5")):
        with pytest.raises(ValueError):
            stars_amount(bad)


@pytest.mark.asyncio
async def test_invoice_link_carries_payment_id_as_payload_and_xtr_price():
    bot = AsyncMock()
    bot.create_invoice_link.return_value = "https://t.me/$abc"
    payment_id = uuid4()
    url = await create_stars_invoice_link(
        bot,
        payment_id=payment_id,
        title="Покупка подписки ⚡️ Старт на 1 месяц, очень длинное название",
        description="Покупка подписки ⚡️ Старт на 1 месяц",
        amount=Decimal("119"),
    )
    assert url == "https://t.me/$abc"
    kwargs = bot.create_invoice_link.await_args.kwargs
    assert kwargs["payload"] == str(payment_id)
    assert kwargs["currency"] == "XTR"
    assert len(kwargs["title"]) <= 32
    assert [(p.label, p.amount) for p in kwargs["prices"]] == [("XTR", 119)]


from unittest.mock import MagicMock  # noqa: E402

from src.bot.routers.subscription.handlers import _create_payment_and_get_data  # noqa: E402
from src.core.constants import USER_KEY  # noqa: E402
from src.core.enums import PaymentGatewayType, PurchaseType  # noqa: E402
from src.models.dto import PlanDto  # noqa: E402
from src.models.dto.plan import PlanDurationDto  # noqa: E402
from tests.conftest import make_dialog_manager, make_user  # noqa: E402


def _stars_billing(url: str | None) -> AsyncMock:
    billing = AsyncMock()
    billing.get_gateway_by_type.return_value = MagicMock(Currency="XTR")
    billing.create_payment.return_value = MagicMock(
        ID="3fa85f64-5717-4562-b3fc-2c963f66afa6", URL=url
    )
    billing.calculate_price.return_value = MagicMock(
        original_amount="119", discount_percent=0, final_amount="119"
    )
    return billing


def _stars_dm() -> tuple[MagicMock, AsyncMock]:
    dm = make_dialog_manager()
    dm.middleware_data[USER_KEY] = make_user(telegram_id=424796490)
    dm.dialog_data["purchase_type"] = PurchaseType.NEW
    bot = AsyncMock()
    bot.create_invoice_link.return_value = "https://t.me/$stars"
    dm.middleware_data["bot"] = bot
    return dm, bot


@pytest.mark.asyncio
async def test_stars_payment_without_billing_url_gets_an_invoice_link():
    plan = PlanDto(id=1, name="⚡️ Старт", durations=[PlanDurationDto(id=1, days=30, prices=[])])
    dm, bot = _stars_dm()
    result = await _create_payment_and_get_data(
        dialog_manager=dm,
        plan=plan,
        duration_days=30,
        gateway_type=PaymentGatewayType.TELEGRAM_STARS,
        billing=_stars_billing(None),
        notification_service=AsyncMock(),
        redis_client=AsyncMock(),
        experiment_service=None,
    )
    assert result is not None
    assert result["payment_url"] == "https://t.me/$stars"
    kwargs = bot.create_invoice_link.await_args.kwargs
    assert kwargs["payload"] == "3fa85f64-5717-4562-b3fc-2c963f66afa6"
    assert [(p.label, p.amount) for p in kwargs["prices"]] == [("XTR", 119)]


@pytest.mark.asyncio
async def test_other_gateways_keep_the_billing_url():
    plan = PlanDto(id=1, name="⚡️ Старт", durations=[PlanDurationDto(id=1, days=30, prices=[])])
    dm, bot = _stars_dm()
    result = await _create_payment_and_get_data(
        dialog_manager=dm,
        plan=plan,
        duration_days=30,
        gateway_type=PaymentGatewayType.PLATEGA,
        billing=_stars_billing("https://pay.example/1"),
        notification_service=AsyncMock(),
        redis_client=AsyncMock(),
        experiment_service=None,
    )
    assert result is not None
    assert result["payment_url"] == "https://pay.example/1"
    bot.create_invoice_link.assert_not_awaited()
