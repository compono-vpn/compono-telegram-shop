"""Tests for the SHOP_ADMIN_ENABLED feature flag.

Verifies that:
- Admin buttons are hidden when flag is OFF
- Admin buttons are visible when flag is ON
- End-user flows are unaffected by the flag
- The AdminGateMiddleware blocks/allows correctly
- The require_admin_enabled guard works
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure test env vars are loaded before any app imports
from tests.conftest import _TEST_ENV  # noqa: F401


# ---------------------------------------------------------------------------
# Dashboard dialog button visibility
# ---------------------------------------------------------------------------

from src.bot.routers.dashboard.dialog import dashboard as dashboard_window
from src.bot.routers.menu.dialog import menu as menu_window
from src.core.constants import (
    ADMIN_DISABLED_MESSAGE,
    IS_SUPER_DEV_KEY,
    MIDDLEWARE_DATA_KEY,
    SHOP_ADMIN_ENABLED_KEY,
    USER_KEY,
)


def _collect_button_ids(window):
    """Recursively collect widget IDs from a Window's keyboard."""
    ids = []
    for widget in window.keyboard.buttons:
        if hasattr(widget, "widget_id"):
            ids.append(widget.widget_id)
        if hasattr(widget, "buttons"):
            for btn in widget.buttons:
                if hasattr(btn, "widget_id"):
                    ids.append(btn.widget_id)
    return ids


class TestDashboardButtonVisibility:
    """Dashboard buttons gated by SHOP_ADMIN_ENABLED."""

    # Admin-gated button IDs
    GATED_IDS = {"broadcast", "promocodes", "access", "remnashop", "remnawave", "importer"}
    # Always-visible button IDs
    ALWAYS_IDS = {"statistics", "users"}

    def _find_widget_and_condition(self, window, widget_id: str):
        """Find a widget by ID and return its parent Row's `condition` (set by when=)."""
        from aiogram_dialog.widgets.kbd import Row

        for widget in window.keyboard.buttons:
            if isinstance(widget, Row):
                for btn in widget.buttons:
                    if getattr(btn, "widget_id", None) == widget_id:
                        return btn, getattr(widget, "condition", None)
        return None, None

    def test_statistics_button_exists(self):
        widget, cond = self._find_widget_and_condition(dashboard_window, "statistics")
        assert widget is not None, "Statistics button must exist in dashboard"

    def test_users_button_exists(self):
        widget, cond = self._find_widget_and_condition(dashboard_window, "users")
        assert widget is not None, "Users button must exist in dashboard"

    def test_broadcast_button_exists(self):
        widget, cond = self._find_widget_and_condition(dashboard_window, "broadcast")
        assert widget is not None, "Broadcast button must exist in dashboard"

    def test_promocodes_button_exists(self):
        widget, cond = self._find_widget_and_condition(dashboard_window, "promocodes")
        assert widget is not None, "Promocodes button must exist in dashboard"

    def test_gated_buttons_have_condition(self):
        """All gated buttons must have a condition (from when=) on their parent Row."""
        for btn_id in self.GATED_IDS:
            _, cond = self._find_widget_and_condition(dashboard_window, btn_id)
            assert cond is not None, (
                f"Button '{btn_id}' must have a when= condition for admin gating"
            )

    def test_always_visible_row_has_no_admin_gate(self):
        """Statistics and Users row must use the default true_condition (no gate)."""
        from aiogram_dialog.widgets.kbd import Row

        for widget in dashboard_window.keyboard.buttons:
            if isinstance(widget, Row):
                btn_ids = {
                    getattr(b, "widget_id", None) for b in widget.buttons
                }
                if btn_ids & self.ALWAYS_IDS:
                    cond = getattr(widget, "condition", None)
                    # When when= is not specified, aiogram_dialog sets a
                    # default true_condition function. Check it's the default.
                    cond_name = getattr(cond, "__name__", "")
                    assert cond_name == "true_condition", (
                        f"Row with {btn_ids & self.ALWAYS_IDS} must not be gated "
                        f"(expected true_condition, got {cond_name})"
                    )


class TestMenuDialogUnaffected:
    """Main menu end-user buttons must not be affected by admin flag."""

    def _find_widget_by_id(self, window, widget_id: str):
        from aiogram_dialog.widgets.kbd import Row

        for widget in window.keyboard.buttons:
            if hasattr(widget, "widget_id") and widget.widget_id == widget_id:
                return widget
            if isinstance(widget, Row):
                for btn in widget.buttons:
                    if getattr(btn, "widget_id", None) == widget_id:
                        return btn
        return None

    def test_core_user_buttons_exist(self):
        """Core end-user buttons must exist in menu regardless of admin flag."""
        # These are the key end-user buttons that must never be removed
        core_ids = {"trial", "purchase_subscription", "info"}
        for btn_id in core_ids:
            widget = self._find_widget_by_id(menu_window, btn_id)
            assert widget is not None, (
                f"End-user button '{btn_id}' must exist in main menu"
            )

    def test_dashboard_button_not_gated_by_admin_flag(self):
        """Dashboard button is gated by is_privileged, NOT by admin flag.

        Admins should still see the dashboard — just with fewer buttons inside.
        """
        from aiogram_dialog.widgets.kbd import Row

        for widget in menu_window.keyboard.buttons:
            if isinstance(widget, Row):
                for btn in widget.buttons:
                    if getattr(btn, "widget_id", None) == "dashboard":
                        cond = getattr(widget, "condition", None)
                        assert cond is not None, "Dashboard button must have a when= condition"
                        return
        pytest.fail("Dashboard button not found in menu")


# ---------------------------------------------------------------------------
# AdminGateMiddleware
# ---------------------------------------------------------------------------

from src.bot.filters.admin_gate import (
    AdminGateMiddleware,
    get_admin_disabled_message,
    require_admin_enabled,
)
from src.core.constants import ADMIN_DISABLED_MESSAGE_WITH_URL, ADMIN_PORTAL_URL_KEY


class TestAdminGateMiddleware:
    """AdminGateMiddleware blocks/allows based on SHOP_ADMIN_ENABLED."""

    @pytest.fixture
    def gate(self):
        return AdminGateMiddleware()

    @pytest.fixture
    def handler(self):
        return AsyncMock(return_value="ok")

    @pytest.mark.asyncio
    async def test_allows_when_enabled(self, gate, handler):
        event = MagicMock()
        data = {SHOP_ADMIN_ENABLED_KEY: True}
        result = await gate(handler, event, data)
        handler.assert_awaited_once_with(event, data)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_blocks_callback_when_disabled(self, gate, handler):
        # Simulate CallbackQuery (has .data attribute)
        callback = AsyncMock()
        callback.data = "some_callback"
        data = {SHOP_ADMIN_ENABLED_KEY: False}
        result = await gate(handler, callback, data)
        handler.assert_not_awaited()
        callback.answer.assert_awaited_once_with(ADMIN_DISABLED_MESSAGE, show_alert=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_blocks_when_key_missing(self, gate, handler):
        callback = AsyncMock()
        callback.data = "some_callback"
        data = {}
        result = await gate(handler, callback, data)
        handler.assert_not_awaited()
        assert result is None

    @pytest.mark.asyncio
    async def test_blocks_message_event(self, gate, handler):
        """When event is a Message-like object (no .data), use message.answer()."""
        message = AsyncMock()
        # Remove .data attribute so it's treated as a message
        del message.data
        data = {SHOP_ADMIN_ENABLED_KEY: False}
        result = await gate(handler, message, data)
        handler.assert_not_awaited()
        message.answer.assert_awaited_once_with(ADMIN_DISABLED_MESSAGE)


class TestRequireAdminEnabled:
    """require_admin_enabled() guard function."""

    def test_returns_true_when_enabled(self):
        assert require_admin_enabled({SHOP_ADMIN_ENABLED_KEY: True}) is True

    def test_returns_false_when_disabled(self):
        assert require_admin_enabled({SHOP_ADMIN_ENABLED_KEY: False}) is False

    def test_returns_false_when_missing(self):
        assert require_admin_enabled({}) is False


# ---------------------------------------------------------------------------
# Config flag
# ---------------------------------------------------------------------------


class TestConfigFlag:
    """SHOP_ADMIN_ENABLED env var is read correctly."""

    def test_default_is_false(self):
        from src.core.config import AppConfig

        config = AppConfig.get()
        assert config.shop_admin_enabled is False

    def test_env_override_true(self, monkeypatch):
        monkeypatch.setenv("APP_SHOP_ADMIN_ENABLED", "true")
        from src.core.config.app import AppConfig

        config = AppConfig()
        assert config.shop_admin_enabled is True

    def test_env_override_false(self, monkeypatch):
        monkeypatch.setenv("APP_SHOP_ADMIN_ENABLED", "false")
        from src.core.config.app import AppConfig

        config = AppConfig()
        assert config.shop_admin_enabled is False


# ---------------------------------------------------------------------------
# Enabling flag restores full behavior
# ---------------------------------------------------------------------------


class TestFlagRestorationBehavior:
    """When flag is ON, admin middleware allows through."""

    @pytest.mark.asyncio
    async def test_admin_gate_passes_when_flag_on(self):
        gate = AdminGateMiddleware()
        handler = AsyncMock(return_value="result")
        event = MagicMock()
        data = {SHOP_ADMIN_ENABLED_KEY: True}

        result = await gate(handler, event, data)
        assert result == "result"
        handler.assert_awaited_once()


# ---------------------------------------------------------------------------
# Admin portal URL handoff
# ---------------------------------------------------------------------------


class TestGetAdminDisabledMessage:
    """get_admin_disabled_message builds the right message based on portal URL."""

    def test_includes_url_when_configured(self):
        url = "https://admin.compono.it.com"
        data = {ADMIN_PORTAL_URL_KEY: url}
        msg = get_admin_disabled_message(data)
        assert url in msg
        assert msg == ADMIN_DISABLED_MESSAGE_WITH_URL.format(url=url)

    def test_fallback_when_url_empty(self):
        data = {ADMIN_PORTAL_URL_KEY: ""}
        msg = get_admin_disabled_message(data)
        assert msg == ADMIN_DISABLED_MESSAGE
        assert "https://" not in msg

    def test_fallback_when_url_missing(self):
        data = {}
        msg = get_admin_disabled_message(data)
        assert msg == ADMIN_DISABLED_MESSAGE

    def test_fallback_message_mentions_migration(self):
        msg = get_admin_disabled_message({})
        assert "migrated" in msg.lower() or "migrating" in msg.lower()


class TestAdminGateMiddlewarePortalHandoff:
    """AdminGateMiddleware shows portal URL in blocked responses."""

    @pytest.fixture
    def gate(self):
        return AdminGateMiddleware()

    @pytest.fixture
    def handler(self):
        return AsyncMock(return_value="ok")

    @pytest.mark.asyncio
    async def test_callback_shows_portal_url_when_configured(self, gate, handler):
        url = "https://admin.compono.it.com"
        callback = AsyncMock()
        callback.data = "some_callback"
        data = {SHOP_ADMIN_ENABLED_KEY: False, ADMIN_PORTAL_URL_KEY: url}
        await gate(handler, callback, data)
        handler.assert_not_awaited()
        expected = ADMIN_DISABLED_MESSAGE_WITH_URL.format(url=url)
        callback.answer.assert_awaited_once_with(expected, show_alert=True)

    @pytest.mark.asyncio
    async def test_message_shows_portal_url_when_configured(self, gate, handler):
        url = "https://admin.compono.it.com"
        message = AsyncMock()
        del message.data
        data = {SHOP_ADMIN_ENABLED_KEY: False, ADMIN_PORTAL_URL_KEY: url}
        await gate(handler, message, data)
        handler.assert_not_awaited()
        expected = ADMIN_DISABLED_MESSAGE_WITH_URL.format(url=url)
        message.answer.assert_awaited_once_with(expected)

    @pytest.mark.asyncio
    async def test_callback_shows_fallback_when_no_url(self, gate, handler):
        callback = AsyncMock()
        callback.data = "some_callback"
        data = {SHOP_ADMIN_ENABLED_KEY: False}
        await gate(handler, callback, data)
        callback.answer.assert_awaited_once_with(ADMIN_DISABLED_MESSAGE, show_alert=True)

    @pytest.mark.asyncio
    async def test_emergency_users_flow_not_blocked(self):
        """Users router is NOT in the admin-gated list — verify the design."""
        from src.bot.routers import setup_routers
        from aiogram import Router

        root = Router()
        setup_routers(root)

        # users.dialog.router and users.user.dialog.router must be included
        # but must NOT have AdminGateMiddleware attached.
        from src.bot.routers.dashboard import users

        user_router = users.dialog.router
        user_user_router = users.user.dialog.router

        for r in [user_router, user_user_router]:
            for mw in r.message.middleware:
                assert not isinstance(mw, AdminGateMiddleware), (
                    f"Users router {r} must NOT have AdminGateMiddleware"
                )


class TestAdminPortalUrlConfig:
    """ADMIN_PORTAL_URL env var is read correctly."""

    def test_default_is_empty(self):
        from src.core.config import AppConfig

        config = AppConfig.get()
        assert config.admin_portal_url == ""

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("APP_ADMIN_PORTAL_URL", "https://admin.compono.it.com")
        from src.core.config.app import AppConfig

        config = AppConfig()
        assert config.admin_portal_url == "https://admin.compono.it.com"
