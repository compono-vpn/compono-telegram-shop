"""The 2 h not-connected reminder must not nag users who already connected.

HWID device reporting is disabled (remnawave hwid_settings.enabled=false, last
device row 2026-07-03), so the reminder must also honour the subscription-fetch
and traffic signals that Remnawave still records.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.taskiq.tasks.notifications import user_already_connected
from tests.conftest import make_subscription, make_user


def _remnawave(devices=None, remote=None, get_user_error=None):
    svc = AsyncMock()
    svc.get_devices_user.return_value = devices or []
    if get_user_error:
        svc.get_user.side_effect = get_user_error
    else:
        svc.get_user.return_value = remote
    return svc


@pytest.mark.asyncio
async def test_registered_device_counts_as_connected():
    user = make_user(subscription=make_subscription(is_trial=True))
    svc = _remnawave(devices=[object()])
    assert await user_already_connected(user, user.current_subscription, svc)


@pytest.mark.asyncio
async def test_fetched_subscription_counts_as_connected_without_devices():
    user = make_user(subscription=make_subscription(is_trial=True))
    remote = SimpleNamespace(sub_last_opened_at="2026-10-10T09:00:00Z", user_traffic=None)
    svc = _remnawave(remote=remote)
    assert await user_already_connected(user, user.current_subscription, svc)
    svc.get_user.assert_awaited_once_with(user.current_subscription.user_remna_id)


@pytest.mark.asyncio
async def test_traffic_counts_as_connected_without_devices():
    user = make_user(subscription=make_subscription(is_trial=True))
    remote = SimpleNamespace(sub_last_opened_at=None, user_traffic=SimpleNamespace(
        used_traffic_bytes=0, lifetime_used_traffic_bytes=2048))
    assert await user_already_connected(user, user.current_subscription, _remnawave(remote=remote))


@pytest.mark.asyncio
async def test_no_signal_means_reminder_is_sent():
    user = make_user(subscription=make_subscription(is_trial=True))
    remote = SimpleNamespace(sub_last_opened_at=None, user_traffic=None)
    svc = _remnawave(remote=remote)
    assert not await user_already_connected(user, user.current_subscription, svc)


@pytest.mark.asyncio
async def test_panel_error_falls_back_to_device_signal_only():
    user = make_user(subscription=make_subscription(is_trial=True))
    svc = _remnawave(get_user_error=RuntimeError("panel down"))
    assert not await user_already_connected(user, user.current_subscription, svc)
    svc.get_devices_user.return_value = [object()]
    assert await user_already_connected(user, user.current_subscription, svc)
