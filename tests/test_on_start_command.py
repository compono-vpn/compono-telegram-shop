"""Tests for on_start_command — verifies the web→Telegram claim/link flow has
been removed and replaced with a neutral redirect message.

After PR 4 of the Web/TG split, the bot:
- Shows a neutral redirect message when a /start web_<token> deep link is used.
- Never calls billing or remnawave APIs to claim/link a web subscription.
- Has no message handler that links pasted /api/sub/<token> URLs.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import make_dialog_manager, make_user, unwrap_inject
from src.bot.routers.menu import handlers as menu_handlers
from src.bot.routers.menu.handlers import on_start_command


def _setup(start_text: str) -> tuple:
    """Build mocks for on_start_command handler."""
    user = make_user(telegram_id=450987966, name="Анастасия")

    message = MagicMock()
    message.text = start_text
    message.answer = AsyncMock()

    dm = MagicMock()
    dm.start = AsyncMock()

    i18n = MagicMock()
    # Echo the key with a recognizable prefix so we can assert what was used.
    i18n.get.side_effect = lambda key, **kwargs: f"[{key}]"

    return message, user, dm, i18n


class TestOnStartCommandWebPayload:
    """A /start web_<token> payload no longer claims/links anything."""

    async def test_web_payload_sends_neutral_redirect(self):
        message, user, dm, i18n = _setup("/start web_ABC123")
        raw_fn = unwrap_inject(on_start_command)

        await raw_fn(message, user, dm, i18n)

        # The redirect message uses the dedicated i18n key.
        i18n.get.assert_any_call("msg-web-purchase-redirect")
        message.answer.assert_called_once_with("[msg-web-purchase-redirect]")

        # Main menu still opens after the redirect.
        dm.start.assert_called_once()

    async def test_web_payload_does_not_call_any_billing_or_remnawave_api(self):
        """The handler must not depend on billing/remnawave subscription_service.

        We verify this by inspecting the handler signature: it must only
        require message/user/dm/i18n. Any FromDishka injection of
        BillingClient, RemnawaveService, SubscriptionService or
        NotificationService would mean the claim/link flow is still
        wired in.
        """
        import inspect

        sig = inspect.signature(unwrap_inject(on_start_command))
        param_names = set(sig.parameters.keys())

        # Only these four are allowed.
        assert param_names == {"message", "user", "dialog_manager", "i18n"}, (
            f"on_start_command must not depend on subscription/billing/remnawave "
            f"services — got params {param_names}"
        )

    async def test_no_web_payload_skips_redirect(self):
        message, user, dm, i18n = _setup("/start")
        raw_fn = unwrap_inject(on_start_command)

        await raw_fn(message, user, dm, i18n)

        # No redirect message sent.
        message.answer.assert_not_called()
        i18n.get.assert_not_called()

        # Menu still opens.
        dm.start.assert_called_once()

    async def test_non_web_payload_skips_redirect(self):
        message, user, dm, i18n = _setup("/start REF_abcdef")
        raw_fn = unwrap_inject(on_start_command)

        await raw_fn(message, user, dm, i18n)

        message.answer.assert_not_called()
        i18n.get.assert_not_called()
        dm.start.assert_called_once()


class TestPastedSubUrlHandlerRemoved:
    """The handler that linked pasted /api/sub/<token> URLs is gone."""

    def test_handler_function_is_removed(self):
        """on_subscription_url_paste must not exist on the handlers module."""
        assert not hasattr(menu_handlers, "on_subscription_url_paste"), (
            "on_subscription_url_paste handler should be removed — pasted "
            "/api/sub/ links must not trigger any subscription linking flow."
        )

    def test_link_helpers_are_removed(self):
        """The pasted-URL helper functions must also be gone."""
        for name in (
            "_validate_pasted_sub_url",
            "_link_pasted_subscription",
            "_handle_web_link",
            "_validate_web_order",
            "_check_already_claimed",
            "_check_trial_eligibility",
            "_link_customer_and_email",
            "_create_new_web_subscription",
            "_extend_existing_subscription",
            "_build_plan_snapshot",
        ):
            assert not hasattr(menu_handlers, name), (
                f"Web claim/link helper '{name}' should be removed; web "
                f"purchases are managed by the web portal."
            )

    def test_router_has_no_text_message_handler_for_sub_url(self):
        """The Router must not have a message handler triggered by /api/sub/."""
        from aiogram import F

        router = menu_handlers.router
        # Iterate registered message observers. aiogram's Router exposes
        # message handlers via the .message observer's .handlers list.
        for handler in router.message.handlers:
            for f in handler.filters:
                # MagicFilter uses callable(); the offending filter would
                # contain the substring "/api/sub/" somewhere in its repr.
                # We accept any way the handler was registered: simply
                # checking the repr is the simplest reliable signal.
                callback_repr = repr(getattr(f, "callback", f))
                assert "/api/sub/" not in callback_repr, (
                    "A message handler triggered by '/api/sub/' is still "
                    "registered on the menu router; it must be removed."
                )
        # Sanity-check we did look at at least one handler (the /start one).
        assert router.message.handlers, (
            "Expected at least one message handler on the menu router."
        )
