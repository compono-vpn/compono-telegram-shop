from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage

from src.core.utils.message_payload import MessagePayload
from src.services.notification import NotificationService
from src.services.remnawave import RemnawaveService
from tests.conftest import make_subscription, make_user


async def test_device_check_uses_separately_loaded_subscription():
    user = make_user()
    user.current_subscription = None
    subscription = make_subscription()
    lookup = AsyncMock(return_value=SimpleNamespace(total=1, devices=['registered-device']))
    service = SimpleNamespace(remnawave=SimpleNamespace(hwid=SimpleNamespace(get_hwid_user=lookup)))
    result = await RemnawaveService.get_devices_user(service, user, subscription=subscription)
    assert result == ['registered-device']
    lookup.assert_awaited_once_with(subscription.user_remna_id)
    assert user.current_subscription is None


@pytest.mark.parametrize('reason, expected_level', [
    ('Forbidden: bot was blocked by the user', 'info'),
    ('Forbidden: bot is not a member of the channel chat', 'exception'),
])
async def test_notification_block_is_expected_but_other_forbidden_errors_remain_visible(reason, expected_level):
    error = TelegramForbiddenError(method=SendMessage(chat_id=12345, text='test'), message=reason)
    service = SimpleNamespace(
        _prepare_reply_markup=Mock(return_value=None),
        _send_text_message=AsyncMock(side_effect=error),
    )
    with patch('src.services.notification.logger') as log:
        result = await NotificationService._send_message(service, make_user(), MessagePayload(i18n_key='test'))
    assert result is None
    getattr(log, expected_level).assert_called_once()
    if expected_level == 'info':
        log.exception.assert_not_called()


async def test_reminder_checks_devices_using_current_subscription_from_billing():
    from redis.asyncio import Redis
    from src.infrastructure.taskiq.tasks.notifications import process_pending_not_connected_reminders_task
    from src.services.subscription import SubscriptionService
    from src.services.user import UserService

    user = make_user()
    user.current_subscription = None
    subscription = make_subscription(is_trial=True)
    redis = AsyncMock()
    redis.zrangebyscore.return_value = [b'12345:https://example.invalid/connect/test']
    redis.exists.return_value = False
    remna = AsyncMock()
    remna.get_devices_user.return_value = ['registered-device']
    notify = AsyncMock()
    deps = {
        Redis: redis,
        UserService: SimpleNamespace(get=AsyncMock(return_value=user)),
        SubscriptionService: SimpleNamespace(get_current=AsyncMock(return_value=subscription)),
        RemnawaveService: remna,
        NotificationService: notify,
    }
    container = AsyncMock()
    container.get.side_effect = lambda dependency, **kwargs: deps[dependency]
    await process_pending_not_connected_reminders_task.original_func(dishka_container=container)
    remna.get_devices_user.assert_awaited_once_with(user, subscription=subscription)
    notify.notify_user.assert_not_awaited()
