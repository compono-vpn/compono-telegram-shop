"""Centralized admin feature gate.

When SHOP_ADMIN_ENABLED is False, admin-only Telegram flows are blocked.
This module provides:
- ``admin_enabled_condition``: a magic-filter condition for aiogram_dialog ``when=``
- ``AdminGateMiddleware``: a router middleware that blocks admin dialog starts
- ``require_admin_enabled``: a sync guard for imperative handler checks
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from loguru import logger
from magic_filter import F

from src.core.constants import (
    ADMIN_DISABLED_MESSAGE,
    MIDDLEWARE_DATA_KEY,
    SHOP_ADMIN_ENABLED_KEY,
)

# Magic-filter condition usable in aiogram_dialog ``when=`` clauses.
# Evaluates to True only when the admin flag is enabled.
admin_enabled_condition = F[MIDDLEWARE_DATA_KEY][SHOP_ADMIN_ENABLED_KEY]


class AdminGateMiddleware(BaseMiddleware):
    """Blocks processing when SHOP_ADMIN_ENABLED is False.

    Attach to admin-only dialog routers via ``router.message.middleware()`` /
    ``router.callback_query.middleware()`` to prevent direct navigation into
    gated dialogs.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if data.get(SHOP_ADMIN_ENABLED_KEY, False):
            return await handler(event, data)

        logger.info("Admin gate: blocked admin action (SHOP_ADMIN_ENABLED=false)")

        # Send feedback to user.
        # Use duck-typing: CallbackQuery.answer() takes show_alert,
        # Message.answer() does not.  Check for callback_data attribute
        # to distinguish.
        if hasattr(event, "data"):
            # CallbackQuery
            await event.answer(ADMIN_DISABLED_MESSAGE, show_alert=True)
        elif hasattr(event, "answer"):
            await event.answer(ADMIN_DISABLED_MESSAGE)

        return None


def require_admin_enabled(data: dict[str, Any]) -> bool:
    """Return True if admin features are enabled.

    Use in imperative handlers::

        if not require_admin_enabled(data):
            await message.answer(ADMIN_DISABLED_MESSAGE)
            return
    """
    return bool(data.get(SHOP_ADMIN_ENABLED_KEY, False))
