from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from aiogram import Bot
from aiogram_dialog import BgManagerFactory

from src.core.enums import PurchaseType
from src.infrastructure.billing import BillingClient
from src.infrastructure.taskiq.tasks.redirects import redirect_to_successed_payment_task
from src.services.notification import NotificationService
from tests.conftest import make_user


def _setup():
    order: list[str] = []
    bg = MagicMock()

    async def started(*args, **kwargs):
        order.append("payment_message")

    bg.start = AsyncMock(side_effect=started)
    factory = MagicMock()
    factory.bg.return_value = bg
    billing = AsyncMock()
    billing.get_referral_by_referred.return_value = None
    billing.claim_user_reminder.return_value = True
    ntf = AsyncMock()

    async def sent(*args, **kwargs):
        order.append("survey")
        return MagicMock()

    ntf.notify_user.side_effect = sent
    return order, factory, billing, ntf


async def _run(user, purchase_type, factory, billing, ntf):
    deps = {
        Bot: MagicMock(),
        BgManagerFactory: factory,
        BillingClient: billing,
        NotificationService: ntf,
    }
    container = AsyncMock()
    container.get.side_effect = lambda dependency, **kwargs: deps[dependency]
    await redirect_to_successed_payment_task.original_func(
        user=user, purchase_type=purchase_type, dishka_container=container
    )


class TestPaymentSuccessAsksTheSource:
    async def test_survey_follows_the_success_message(self):
        order, factory, billing, ntf = _setup()
        await _run(make_user(), PurchaseType.NEW, factory, billing, ntf)

        assert order == ["payment_message", "survey"]
        billing.claim_user_reminder.assert_awaited_once_with(1750352084, "SOURCE_SURVEY", "v1")
        assert ntf.notify_user.await_args.kwargs["payload"].i18n_key == "ntf-source-survey-prompt"

    async def test_user_with_a_source_tag_is_not_asked(self):
        order, factory, billing, ntf = _setup()
        user = make_user()
        object.__setattr__(user, "source", "home-hero")
        await _run(user, PurchaseType.NEW, factory, billing, ntf)

        assert order == ["payment_message"]
        billing.claim_user_reminder.assert_not_called()

    async def test_referred_user_is_not_asked(self):
        order, factory, billing, ntf = _setup()
        billing.get_referral_by_referred.return_value = MagicMock(ReferrerTelegramID=7)
        await _run(make_user(), PurchaseType.NEW, factory, billing, ntf)

        assert order == ["payment_message"]
        billing.claim_user_reminder.assert_not_called()

    async def test_failing_survey_never_breaks_the_success_message(self):
        order, factory, billing, ntf = _setup()
        ntf.notify_user.side_effect = RuntimeError("telegram down")
        await _run(make_user(), PurchaseType.RENEW, factory, billing, ntf)

        assert order == ["payment_message"]
