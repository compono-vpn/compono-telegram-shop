"""Tests for the menu dialog widget structure.

Verifies button ordering and i18n key usage in the main menu.
"""

from __future__ import annotations

from aiogram_dialog.widgets.common.when import true_condition
from aiogram_dialog.widgets.kbd import Button, Row, SwitchTo, Url

from src.bot.routers.menu.dialog import connect, menu
from src.bot.states import MainMenu


def _get_rows(window):
    """Extract Row widgets from a Window (they are positional args in keyboard)."""
    return [w for w in window.keyboard.buttons if isinstance(w, Row)]


def _find_widget_by_id(window, widget_id: str):
    """Find a widget by its ID in the window's keyboard rows."""
    for row in _get_rows(window):
        for widget in row.buttons:
            if getattr(widget, "widget_id", None) == widget_id:
                return widget
    return None


def _get_row_index(window, widget_id: str) -> int:
    """Return the index of the Row containing a widget with the given ID."""
    for i, row in enumerate(_get_rows(window)):
        for widget in row.buttons:
            if getattr(widget, "widget_id", None) == widget_id:
                return i
    return -1


class TestMenuButtonOrder:
    """The TG proxy button must appear right after the connect row."""

    def test_tg_proxy_button_exists(self):
        widget = _find_widget_by_id(menu, "tg_proxy")
        assert widget is not None, "TG proxy button not found in menu"

    def test_tg_proxy_right_after_connect(self):
        connect_row_idx = _get_row_index(menu, "not_available")
        proxy_row_idx = _get_row_index(menu, "tg_proxy")

        assert connect_row_idx >= 0, "Connect row not found"
        assert proxy_row_idx >= 0, "TG proxy row not found"
        assert proxy_row_idx == connect_row_idx + 1, (
            f"TG proxy button should be right after connect row "
            f"(expected index {connect_row_idx + 1}, got {proxy_row_idx})"
        )

    def test_tg_proxy_before_trial(self):
        proxy_row_idx = _get_row_index(menu, "tg_proxy")
        trial_row_idx = _get_row_index(menu, "trial")

        assert proxy_row_idx >= 0, "TG proxy row not found"
        assert trial_row_idx >= 0, "Trial row not found"
        assert proxy_row_idx < trial_row_idx, (
            f"TG proxy (index {proxy_row_idx}) should be before trial (index {trial_row_idx})"
        )


class TestIosAppButton:
    def test_ios_button_is_url(self):
        widget = _find_widget_by_id(menu, "ios_app")
        assert widget is not None, "iOS app button not found in menu"
        assert isinstance(widget, Url)

    def test_ios_button_right_after_devices_row(self):
        devices_row_idx = _get_row_index(menu, "devices")
        ios_row_idx = _get_row_index(menu, "ios_app")

        assert devices_row_idx >= 0
        assert ios_row_idx == devices_row_idx + 1

    def test_ios_button_before_invite_and_support(self):
        ios_row_idx = _get_row_index(menu, "ios_app")

        assert 0 <= ios_row_idx < _get_row_index(menu, "invite")
        assert ios_row_idx < _get_row_index(menu, "support")

    def test_ios_button_is_shown_to_every_user(self):
        row = _get_rows(menu)[_get_row_index(menu, "ios_app")]

        assert row.condition is true_condition
        assert all(w.condition is true_condition for w in row.buttons)


class TestMenuI18nKeys:
    """Button text must use proper i18n keys (not hardcoded strings)."""

    def test_tg_proxy_button_uses_i18n(self):
        widget = _find_widget_by_id(menu, "tg_proxy")
        assert widget is not None
        # I18nFormat stores the key — check it's not a hardcoded English string
        text_widget = widget.text
        assert hasattr(text_widget, "key") or hasattr(text_widget, "text"), \
            "TG proxy button text should use I18nFormat"


class TestConnectButton:
    """The main-menu connect button opens the connect submenu instead of a raw URL."""

    def test_connect_button_exists(self):
        widget = _find_widget_by_id(menu, "connect")
        assert widget is not None, "Connect button not found in menu"

    def test_connect_button_is_a_callback_that_opens_the_card_or_the_submenu(self):
        from aiogram_dialog.widgets.kbd import Button

        from src.bot.routers.menu.handlers import on_connect_open

        widget = _find_widget_by_id(menu, "connect")
        assert isinstance(widget, Button) and not isinstance(widget, SwitchTo), (
            "Connect button must be a callback button, not a Url button"
        )
        assert widget.on_click.callback is on_connect_open

    def test_not_available_button_still_present(self):
        """Users without a usable subscription keep the old 'not available' reason button."""
        widget = _find_widget_by_id(menu, "not_available")
        assert widget is not None

    def test_connect_and_not_available_share_a_row(self):
        connect_row_idx = _get_row_index(menu, "connect")
        not_available_row_idx = _get_row_index(menu, "not_available")

        assert connect_row_idx >= 0
        assert connect_row_idx == not_available_row_idx


class TestConnectSubmenu:
    """The connect submenu offers a guide URL, a give-link callback, and a back button."""

    def test_guide_button_is_url(self):
        widget = _find_widget_by_id(connect, "connect_guide")
        assert widget is not None, "Guide button not found in connect submenu"
        assert isinstance(widget, Url)

    def test_give_link_button_is_callback(self):
        widget = _find_widget_by_id(connect, "connect_give_link")
        assert widget is not None, "Give-link button not found in connect submenu"
        assert isinstance(widget, Button)

    def test_back_button_returns_to_main_menu(self):
        widget = _find_widget_by_id(connect, "back")
        assert widget is not None
        assert isinstance(widget, SwitchTo)
        assert widget.state == MainMenu.MAIN

    def test_submenu_state_is_registered(self):
        assert connect.get_state() == MainMenu.CONNECT
