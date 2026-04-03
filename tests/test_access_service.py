"""Tests for AccessService -- verifies access control, waitlist, and mode management."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_config, make_user

from src.core.enums import AccessMode, Locale, UserRole
from src.models.dto.settings import SettingsDto
from src.models.dto.user import UserDto
from src.services.access import AccessService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(**overrides) -> SettingsDto:
    defaults = dict(
        access_mode=AccessMode.PUBLIC,
        purchases_allowed=True,
        registration_allowed=True,
    )
    defaults.update(overrides)
    return SettingsDto(**defaults)


def _make_service(
    settings: SettingsDto | None = None,
    user: UserDto | None = None,
    user_exists: bool = True,
    is_referral_event: bool = False,
) -> tuple[AccessService, AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    """Return (service, settings_service, user_service, referral_service, notification_service)."""
    config = make_config()
    bot = AsyncMock()
    redis_client = AsyncMock()
    redis_repository = AsyncMock()
    translator_hub = MagicMock()

    settings_service = AsyncMock()
    settings_service.get.return_value = settings or _make_settings()
    settings_service.get_access_mode.return_value = (settings or _make_settings()).access_mode
    settings_service.set_access_mode = AsyncMock()

    user_service = AsyncMock()
    user_service.get.return_value = user if user_exists else None

    referral_service = AsyncMock()
    referral_service.is_referral_event.return_value = is_referral_event

    notification_service = AsyncMock()

    svc = AccessService(
        config=config,
        bot=bot,
        redis_client=redis_client,
        redis_repository=redis_repository,
        translator_hub=translator_hub,
        settings_service=settings_service,
        user_service=user_service,
        referral_service=referral_service,
        notification_service=notification_service,
    )

    return svc, settings_service, user_service, referral_service, notification_service


def _make_aiogram_user(user_id: int = 12345) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    u.full_name = "Test User"
    u.language_code = "en"
    return u


def _make_callback_event(data: str = "some_callback") -> MagicMock:
    from aiogram.types import CallbackQuery

    event = MagicMock(spec=CallbackQuery)
    event.data = data
    return event


def _make_message_event() -> MagicMock:
    from aiogram.types import Message

    event = MagicMock(spec=Message)
    return event


# ---------------------------------------------------------------------------
# Tests: is_access_allowed -- new user (user=None)
# ---------------------------------------------------------------------------


class TestIsAccessAllowedNewUser:
    """When user_service.get() returns None the user is considered new."""

    async def test_public_mode_allows_new_user(self):
        svc, *_ = _make_service(
            settings=_make_settings(access_mode=AccessMode.PUBLIC),
            user_exists=False,
        )
        event = _make_message_event()
        result = await svc.is_access_allowed(_make_aiogram_user(), event)
        assert result is True

    async def test_invited_mode_denies_new_user_without_referral(self):
        svc, _, _, referral_svc, notification_svc = _make_service(
            settings=_make_settings(access_mode=AccessMode.INVITED),
            user_exists=False,
            is_referral_event=False,
        )
        event = _make_message_event()
        result = await svc.is_access_allowed(_make_aiogram_user(), event)

        assert result is False
        notification_svc.notify_user.assert_awaited_once()

    async def test_invited_mode_allows_new_user_with_referral(self):
        svc, *_ = _make_service(
            settings=_make_settings(access_mode=AccessMode.INVITED),
            user_exists=False,
            is_referral_event=True,
        )
        event = _make_message_event()
        result = await svc.is_access_allowed(_make_aiogram_user(), event)
        assert result is True

    async def test_restricted_mode_denies_new_user(self):
        svc, _, _, _, notification_svc = _make_service(
            settings=_make_settings(access_mode=AccessMode.RESTRICTED),
            user_exists=False,
        )
        event = _make_message_event()
        result = await svc.is_access_allowed(_make_aiogram_user(), event)

        assert result is False
        notification_svc.notify_user.assert_awaited_once()

    async def test_registration_blocked_denies_new_user(self):
        svc, _, _, _, notification_svc = _make_service(
            settings=_make_settings(
                access_mode=AccessMode.PUBLIC,
                registration_allowed=False,
            ),
            user_exists=False,
        )
        event = _make_message_event()
        result = await svc.is_access_allowed(_make_aiogram_user(), event)

        assert result is False
        notification_svc.notify_user.assert_awaited_once()
        # Verify the right i18n_key was used
        call_kwargs = notification_svc.notify_user.call_args
        payload = call_kwargs.kwargs.get("payload") or call_kwargs[1].get("payload")
        assert payload.i18n_key == "ntf-access-denied-registration"


# ---------------------------------------------------------------------------
# Tests: is_access_allowed -- existing user
# ---------------------------------------------------------------------------


class TestIsAccessAllowedExistingUser:
    """When user_service.get() returns a UserDto."""

    async def test_blocked_user_denied(self):
        user = make_user()
        user.is_blocked = True
        svc, *_ = _make_service(user=user)
        event = _make_message_event()

        result = await svc.is_access_allowed(_make_aiogram_user(user.telegram_id), event)
        assert result is False

    async def test_privileged_user_always_allowed(self):
        user = make_user()
        user.role = UserRole.ADMIN
        svc, *_ = _make_service(user=user)
        event = _make_message_event()

        result = await svc.is_access_allowed(_make_aiogram_user(user.telegram_id), event)
        assert result is True

    async def test_dev_user_always_allowed(self):
        user = make_user()
        user.role = UserRole.DEV
        svc, *_ = _make_service(user=user)
        event = _make_message_event()

        result = await svc.is_access_allowed(_make_aiogram_user(user.telegram_id), event)
        assert result is True

    async def test_public_mode_allows_regular_user(self):
        user = make_user()
        svc, *_ = _make_service(
            settings=_make_settings(access_mode=AccessMode.PUBLIC),
            user=user,
        )
        event = _make_message_event()

        result = await svc.is_access_allowed(_make_aiogram_user(user.telegram_id), event)
        assert result is True

    async def test_restricted_mode_denies_regular_user(self):
        user = make_user()
        svc, _, _, _, notification_svc = _make_service(
            settings=_make_settings(access_mode=AccessMode.RESTRICTED),
            user=user,
        )
        event = _make_message_event()

        result = await svc.is_access_allowed(_make_aiogram_user(user.telegram_id), event)
        assert result is False
        notification_svc.notify_user.assert_awaited_once()

    async def test_invited_mode_allows_existing_user(self):
        user = make_user()
        svc, *_ = _make_service(
            settings=_make_settings(access_mode=AccessMode.INVITED),
            user=user,
        )
        event = _make_message_event()

        result = await svc.is_access_allowed(_make_aiogram_user(user.telegram_id), event)
        assert result is True

    @patch("src.services.access.redirect_to_main_menu_task")
    @patch("src.services.access.remove_intent_id")
    async def test_purchase_blocked_denies_purchase_action(
        self, mock_remove_intent, mock_redirect_task
    ):
        """When purchases_allowed=False and user triggers a purchase callback."""
        from src.core.constants import PURCHASE_PREFIX

        mock_remove_intent.return_value = ["ignored", f"{PURCHASE_PREFIX}plan_1"]
        mock_redirect_task.kiq = AsyncMock()

        user = make_user()
        svc, _, _, _, notification_svc = _make_service(
            settings=_make_settings(purchases_allowed=False),
            user=user,
        )
        # Must set up redis_repository for waitlist check
        svc.redis_repository.collection_is_member = AsyncMock(return_value=False)
        svc.redis_repository.collection_add = AsyncMock(return_value=1)

        event = _make_callback_event(data=f"some_intent:{PURCHASE_PREFIX}plan_1")

        result = await svc.is_access_allowed(_make_aiogram_user(user.telegram_id), event)

        assert result is False
        mock_redirect_task.kiq.assert_awaited_once_with(user.telegram_id)
        notification_svc.notify_user.assert_awaited_once()

    @patch("src.services.access.redirect_to_main_menu_task")
    @patch("src.services.access.remove_intent_id")
    async def test_purchase_blocked_adds_to_waitlist_if_not_member(
        self, mock_remove_intent, mock_redirect_task
    ):
        from src.core.constants import PURCHASE_PREFIX

        mock_remove_intent.return_value = ["ignored", f"{PURCHASE_PREFIX}plan_1"]
        mock_redirect_task.kiq = AsyncMock()

        user = make_user()
        svc, *_ = _make_service(
            settings=_make_settings(purchases_allowed=False),
            user=user,
        )
        svc.redis_repository.collection_is_member = AsyncMock(return_value=False)
        svc.redis_repository.collection_add = AsyncMock(return_value=1)

        event = _make_callback_event(data=f"intent:{PURCHASE_PREFIX}plan_1")
        await svc.is_access_allowed(_make_aiogram_user(user.telegram_id), event)

        svc.redis_repository.collection_add.assert_awaited_once()

    @patch("src.services.access.redirect_to_main_menu_task")
    @patch("src.services.access.remove_intent_id")
    async def test_purchase_blocked_skips_waitlist_if_already_member(
        self, mock_remove_intent, mock_redirect_task
    ):
        from src.core.constants import PURCHASE_PREFIX

        mock_remove_intent.return_value = ["ignored", f"{PURCHASE_PREFIX}plan_1"]
        mock_redirect_task.kiq = AsyncMock()

        user = make_user()
        svc, *_ = _make_service(
            settings=_make_settings(purchases_allowed=False),
            user=user,
        )
        svc.redis_repository.collection_is_member = AsyncMock(return_value=True)
        svc.redis_repository.collection_add = AsyncMock(return_value=0)

        event = _make_callback_event(data=f"intent:{PURCHASE_PREFIX}plan_1")
        await svc.is_access_allowed(_make_aiogram_user(user.telegram_id), event)

        svc.redis_repository.collection_add.assert_not_awaited()

    async def test_non_purchase_callback_allowed_when_purchases_blocked(self):
        """Non-purchase callbacks should not be blocked even if purchases_allowed=False."""
        user = make_user()
        svc, *_ = _make_service(
            settings=_make_settings(
                access_mode=AccessMode.PUBLIC,
                purchases_allowed=False,
            ),
            user=user,
        )
        event = _make_message_event()

        result = await svc.is_access_allowed(_make_aiogram_user(user.telegram_id), event)
        assert result is True


# ---------------------------------------------------------------------------
# Tests: _is_purchase_action
# ---------------------------------------------------------------------------


class TestIsPurchaseAction:

    @patch("src.services.access.remove_intent_id")
    def test_callback_with_purchase_prefix_returns_true(self, mock_remove):
        from src.core.constants import PURCHASE_PREFIX

        mock_remove.return_value = ["ignored", f"{PURCHASE_PREFIX}plan_1"]
        svc, *_ = _make_service()
        event = _make_callback_event(data=f"intent:{PURCHASE_PREFIX}plan_1")

        assert svc._is_purchase_action(event) is True

    @patch("src.services.access.remove_intent_id")
    def test_callback_without_purchase_prefix_returns_false(self, mock_remove):
        mock_remove.return_value = ["ignored", "other_action"]
        svc, *_ = _make_service()
        event = _make_callback_event(data="intent:other_action")

        assert svc._is_purchase_action(event) is False

    def test_message_event_returns_false(self):
        svc, *_ = _make_service()
        event = _make_message_event()
        assert svc._is_purchase_action(event) is False

    def test_callback_without_data_returns_false(self):
        svc, *_ = _make_service()
        event = _make_callback_event(data="")
        event.data = None
        assert svc._is_purchase_action(event) is False


# ---------------------------------------------------------------------------
# Tests: get_available_modes
# ---------------------------------------------------------------------------


class TestGetAvailableModes:

    async def test_excludes_current_mode(self):
        svc, settings_svc, *_ = _make_service(
            settings=_make_settings(access_mode=AccessMode.PUBLIC),
        )
        settings_svc.get_access_mode.return_value = AccessMode.PUBLIC

        modes = await svc.get_available_modes()

        assert AccessMode.PUBLIC not in modes
        assert AccessMode.INVITED in modes
        assert AccessMode.RESTRICTED in modes

    async def test_all_other_modes_returned(self):
        svc, settings_svc, *_ = _make_service(
            settings=_make_settings(access_mode=AccessMode.RESTRICTED),
        )
        settings_svc.get_access_mode.return_value = AccessMode.RESTRICTED

        modes = await svc.get_available_modes()

        assert AccessMode.RESTRICTED not in modes
        assert len(modes) == len(AccessMode) - 1


# ---------------------------------------------------------------------------
# Tests: set_mode
# ---------------------------------------------------------------------------


class TestSetMode:

    @patch("src.services.access.send_access_opened_notifications_task")
    async def test_set_public_notifies_waiting_users(self, mock_notify_task):
        mock_notify_task.kiq = AsyncMock()
        svc, settings_svc, *_ = _make_service()
        svc.redis_repository.collection_members = AsyncMock(return_value=["111", "222"])
        svc.redis_repository.delete = AsyncMock()

        await svc.set_mode(AccessMode.PUBLIC)

        settings_svc.set_access_mode.assert_awaited_once_with(AccessMode.PUBLIC)
        mock_notify_task.kiq.assert_awaited_once_with([111, 222])

    @patch("src.services.access.send_access_opened_notifications_task")
    async def test_set_invited_notifies_waiting_users(self, mock_notify_task):
        mock_notify_task.kiq = AsyncMock()
        svc, settings_svc, *_ = _make_service()
        svc.redis_repository.collection_members = AsyncMock(return_value=["333"])
        svc.redis_repository.delete = AsyncMock()

        await svc.set_mode(AccessMode.INVITED)

        mock_notify_task.kiq.assert_awaited_once_with([333])

    @patch("src.services.access.send_access_opened_notifications_task")
    async def test_set_restricted_does_not_notify(self, mock_notify_task):
        mock_notify_task.kiq = AsyncMock()
        svc, *_ = _make_service()
        svc.redis_repository.collection_members = AsyncMock(return_value=[])
        svc.redis_repository.delete = AsyncMock()

        await svc.set_mode(AccessMode.RESTRICTED)

        mock_notify_task.kiq.assert_not_awaited()

    @patch("src.services.access.send_access_opened_notifications_task")
    async def test_set_mode_clears_waitlist(self, mock_notify_task):
        mock_notify_task.kiq = AsyncMock()
        svc, *_ = _make_service()
        svc.redis_repository.collection_members = AsyncMock(return_value=[])
        svc.redis_repository.delete = AsyncMock()

        await svc.set_mode(AccessMode.PUBLIC)

        svc.redis_repository.delete.assert_awaited_once()

    @patch("src.services.access.send_access_opened_notifications_task")
    async def test_set_public_no_waiting_users_skips_notification(self, mock_notify_task):
        mock_notify_task.kiq = AsyncMock()
        svc, *_ = _make_service()
        svc.redis_repository.collection_members = AsyncMock(return_value=[])
        svc.redis_repository.delete = AsyncMock()

        await svc.set_mode(AccessMode.PUBLIC)

        mock_notify_task.kiq.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests: waitlist operations
# ---------------------------------------------------------------------------


class TestWaitlist:

    async def test_add_user_to_waitlist_new(self):
        svc, *_ = _make_service()
        svc.redis_repository.collection_add = AsyncMock(return_value=1)

        result = await svc.add_user_to_waitlist(12345)
        assert result is True

    async def test_add_user_to_waitlist_already_exists(self):
        svc, *_ = _make_service()
        svc.redis_repository.collection_add = AsyncMock(return_value=0)

        result = await svc.add_user_to_waitlist(12345)
        assert result is False

    async def test_remove_user_from_waitlist_success(self):
        svc, *_ = _make_service()
        svc.redis_repository.collection_remove = AsyncMock(return_value=1)

        result = await svc.remove_user_from_waitlist(12345)
        assert result is True

    async def test_remove_user_from_waitlist_not_found(self):
        svc, *_ = _make_service()
        svc.redis_repository.collection_remove = AsyncMock(return_value=0)

        result = await svc.remove_user_from_waitlist(12345)
        assert result is False

    async def test_get_all_waiting_users(self):
        svc, *_ = _make_service()
        svc.redis_repository.collection_members = AsyncMock(return_value=["100", "200", "300"])

        result = await svc.get_all_waiting_users()
        assert result == [100, 200, 300]

    async def test_get_all_waiting_users_empty(self):
        svc, *_ = _make_service()
        svc.redis_repository.collection_members = AsyncMock(return_value=[])

        result = await svc.get_all_waiting_users()
        assert result == []

    async def test_clear_all_waiting_users(self):
        svc, *_ = _make_service()
        svc.redis_repository.delete = AsyncMock()

        await svc.clear_all_waiting_users()
        svc.redis_repository.delete.assert_awaited_once()


# ---------------------------------------------------------------------------
# Tests: _can_add_to_waitlist (private but worth covering)
# ---------------------------------------------------------------------------


class TestCanAddToWaitlist:

    async def test_can_add_when_not_member(self):
        svc, *_ = _make_service()
        svc.redis_repository.collection_is_member = AsyncMock(return_value=False)

        result = await svc._can_add_to_waitlist(12345)
        assert result is True

    async def test_cannot_add_when_already_member(self):
        svc, *_ = _make_service()
        svc.redis_repository.collection_is_member = AsyncMock(return_value=True)

        result = await svc._can_add_to_waitlist(12345)
        assert result is False
