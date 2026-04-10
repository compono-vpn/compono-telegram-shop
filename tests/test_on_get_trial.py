"""Tests for on_get_trial handler — trial subscription creation flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import make_user, make_dialog_manager, unwrap_inject
from src.bot.routers.menu.handlers import on_get_trial
from src.core.constants import USER_KEY
from src.infrastructure.billing.client import BillingClientError
from src.infrastructure.billing.models import BillingPlan


def _make_trial_plan() -> BillingPlan:
    return BillingPlan(ID=1, Name="Trial", IsActive=True, Tag="trial")


def _setup(
    *,
    trial_plan: BillingPlan | None = None,
    create_side_effect: Exception | None = None,
) -> tuple:
    """Build mocks for on_get_trial handler."""
    user = make_user(telegram_id=450987966, name="Анастасия")

    billing = AsyncMock()
    billing.get_trial_plan.return_value = trial_plan
    if create_side_effect:
        billing.create_trial_subscription.side_effect = create_side_effect

    notification_service = AsyncMock()

    dm = make_dialog_manager()
    dm.middleware_data[USER_KEY] = user

    callback = MagicMock()
    widget = MagicMock()

    return callback, widget, dm, billing, notification_service


class TestOnGetTrial:
    """Test the on_get_trial handler."""

    async def test_trial_success(self):
        callback, widget, dm, billing, ntf = _setup(trial_plan=_make_trial_plan())
        raw_fn = unwrap_inject(on_get_trial)

        await raw_fn(callback, widget, dm, billing, ntf)

        billing.create_trial_subscription.assert_called_once_with(450987966, 1)
        ntf.notify_user.assert_not_called()

    async def test_trial_plan_not_found(self):
        callback, widget, dm, billing, ntf = _setup(trial_plan=None)
        raw_fn = unwrap_inject(on_get_trial)

        with pytest.raises(ValueError, match="Trial plan not exist"):
            await raw_fn(callback, widget, dm, billing, ntf)

        ntf.notify_user.assert_called_once()
        payload = ntf.notify_user.call_args[1]["payload"]
        assert payload.i18n_key == "ntf-trial-unavailable"

    async def test_trial_already_used_409(self):
        callback, widget, dm, billing, ntf = _setup(
            trial_plan=_make_trial_plan(),
            create_side_effect=BillingClientError(409, "user 450987966 has already used trial"),
        )
        raw_fn = unwrap_inject(on_get_trial)

        await raw_fn(callback, widget, dm, billing, ntf)

        ntf.notify_user.assert_called_once()
        payload = ntf.notify_user.call_args[1]["payload"]
        assert payload.i18n_key == "ntf-trial-already-used"

    async def test_trial_already_used_500_backwards_compat(self):
        """Billing may still return 500 with 'already used trial' message."""
        callback, widget, dm, billing, ntf = _setup(
            trial_plan=_make_trial_plan(),
            create_side_effect=BillingClientError(500, "user 450987966 has already used trial"),
        )
        raw_fn = unwrap_inject(on_get_trial)

        await raw_fn(callback, widget, dm, billing, ntf)

        ntf.notify_user.assert_called_once()
        payload = ntf.notify_user.call_args[1]["payload"]
        assert payload.i18n_key == "ntf-trial-already-used"

    async def test_other_billing_error_propagates(self):
        callback, widget, dm, billing, ntf = _setup(
            trial_plan=_make_trial_plan(),
            create_side_effect=BillingClientError(500, "database connection refused"),
        )
        raw_fn = unwrap_inject(on_get_trial)

        with pytest.raises(BillingClientError):
            await raw_fn(callback, widget, dm, billing, ntf)

        ntf.notify_user.assert_not_called()
