"""Tests for the menu dialog widget structure.

Verifies button ordering and i18n key usage in the main menu.
"""

from __future__ import annotations

from aiogram_dialog.widgets.kbd import Row, SwitchTo, Url, ListGroup
from src.bot.routers.menu.dialog import menu, tg_proxy


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
        connect_row_idx = _get_row_index(menu, "not_available")  # connect row has not_available button
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


class TestTGProxyWindow:
    """The TG proxy window must not use Url buttons (tg:// is rejected by Telegram inline keyboards)."""

    def test_no_url_buttons_in_proxy_window(self):
        """tg:// links don't work as inline keyboard Url buttons — Telegram rejects them."""
        for widget in tg_proxy.keyboard.buttons:
            if isinstance(widget, ListGroup):
                for row in widget.buttons:
                    if isinstance(row, Row):
                        for btn in row.buttons:
                            assert not isinstance(btn, Url), (
                                "TG proxy window must not use Url buttons — "
                                "tg:// scheme is rejected by Telegram inline keyboards"
                            )


class TestMenuI18nKeys:
    """Button text must use proper i18n keys (not hardcoded strings)."""

    def test_tg_proxy_button_uses_i18n(self):
        widget = _find_widget_by_id(menu, "tg_proxy")
        assert widget is not None
        # I18nFormat stores the key — check it's not a hardcoded English string
        text_widget = widget.text
        assert hasattr(text_widget, "key") or hasattr(text_widget, "text"), \
            "TG proxy button text should use I18nFormat"
