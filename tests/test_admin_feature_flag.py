"""Tests for the admin surface reduction.

Verifies that:
- Removed admin buttons are no longer in the dashboard
- Emergency flows (statistics, users) still exist
- End-user flows are unaffected
- Removed admin routers are no longer registered
- Admin gate module has been fully removed
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
    """Dashboard buttons after admin surface reduction."""

    # Removed admin button IDs (should NOT exist)
    REMOVED_IDS = {"broadcast", "promocodes", "access", "remnashop", "remnawave", "importer"}
    # Always-visible button IDs (must still exist)
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

    def test_removed_admin_buttons_are_gone(self):
        """Admin buttons that were gated must no longer exist in the dashboard."""
        all_ids = set(_collect_button_ids(dashboard_window))
        for btn_id in self.REMOVED_IDS:
            assert btn_id not in all_ids, (
                f"Removed admin button '{btn_id}' should not exist in dashboard"
            )

    def test_always_visible_row_has_no_condition(self):
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
    """Main menu end-user buttons must not be affected by admin removal."""

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

        Admins should still see the dashboard -- just with fewer buttons inside.
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
# Admin gate module fully removed
# ---------------------------------------------------------------------------


class TestAdminGateRemoved:
    """Admin gate module and config flag have been fully removed."""

    def test_admin_gate_module_not_importable(self):
        import importlib

        with pytest.raises((ImportError, ModuleNotFoundError)):
            importlib.import_module("src.bot.filters.admin_gate")

    def test_config_has_no_shop_admin_enabled(self):
        from src.core.config import AppConfig

        config = AppConfig.get()
        assert not hasattr(config, "shop_admin_enabled"), (
            "shop_admin_enabled config field should be removed"
        )

    def test_constants_have_no_admin_keys(self):
        import src.core.constants as constants

        assert not hasattr(constants, "SHOP_ADMIN_ENABLED_KEY"), (
            "SHOP_ADMIN_ENABLED_KEY constant should be removed"
        )
        assert not hasattr(constants, "ADMIN_DISABLED_MESSAGE"), (
            "ADMIN_DISABLED_MESSAGE constant should be removed"
        )


# ---------------------------------------------------------------------------
# Router registration: removed admin routers must not be registered
# ---------------------------------------------------------------------------


class TestRouterRegistration:
    """Verify removed admin flows are no longer wired into the bot.

    Instead of calling setup_routers (which fails if routers are already
    attached), we inspect the setup_routers source to verify which routers
    are referenced.
    """

    def _get_setup_source(self) -> str:
        import inspect
        from src.bot.routers import setup_routers
        return inspect.getsource(setup_routers)

    def test_no_admin_gated_routers_in_setup(self):
        """setup_routers should not reference any removed admin dialog routers."""
        source = self._get_setup_source()

        removed_module_fragments = [
            "access.dialog", "broadcast.dialog", "importer.dialog",
            "promocodes.dialog", "remnashop.dialog", "remnawave.dialog",
            "gateways.dialog", "referral.dialog", "notifications.dialog",
            "plans.dialog",
        ]
        for fragment in removed_module_fragments:
            assert fragment not in source, (
                f"Removed admin router '{fragment}' is still referenced in setup_routers"
            )

    def test_emergency_users_router_still_in_setup(self):
        """Users router must remain in setup_routers for emergency user management."""
        source = self._get_setup_source()
        assert "users.dialog.router" in source, "Users router must be in setup_routers"
        assert "users.user.dialog.router" in source, "User detail router must be in setup_routers"

    def test_statistics_router_still_in_setup(self):
        """Statistics router must remain in setup_routers."""
        source = self._get_setup_source()
        assert "statistics.dialog.router" in source, "Statistics router must be in setup_routers"

    def test_end_user_routers_still_in_setup(self):
        """End-user routers (menu, subscription, payment, etc.) must remain."""
        source = self._get_setup_source()
        for keyword in ["menu.dialog.router", "subscription.dialog.router",
                         "payment.router", "commands.router"]:
            assert keyword in source, f"End-user router '{keyword}' must be in setup_routers"

    def test_removed_admin_modules_not_importable(self):
        """Removed admin modules should not be importable."""
        import importlib

        removed_modules = [
            "src.bot.routers.dashboard.access",
            "src.bot.routers.dashboard.broadcast",
            "src.bot.routers.dashboard.importer",
            "src.bot.routers.dashboard.promocodes",
            "src.bot.routers.dashboard.remnashop",
            "src.bot.routers.dashboard.remnawave",
        ]
        for mod_name in removed_modules:
            with pytest.raises((ImportError, ModuleNotFoundError)):
                importlib.import_module(mod_name)



# ---------------------------------------------------------------------------
# Removed services are not importable
# ---------------------------------------------------------------------------


class TestRemovedServices:
    """Verify removed admin services are no longer importable."""

    def test_broadcast_service_not_importable(self):
        import importlib

        with pytest.raises((ImportError, ModuleNotFoundError)):
            importlib.import_module("src.services.broadcast")

    def test_importer_service_not_importable(self):
        import importlib

        with pytest.raises((ImportError, ModuleNotFoundError)):
            importlib.import_module("src.services.importer")

    def test_broadcast_tasks_not_importable(self):
        import importlib

        with pytest.raises((ImportError, ModuleNotFoundError)):
            importlib.import_module("src.infrastructure.taskiq.tasks.broadcast")

    def test_importer_tasks_not_importable(self):
        import importlib

        with pytest.raises((ImportError, ModuleNotFoundError)):
            importlib.import_module("src.infrastructure.taskiq.tasks.importer")
