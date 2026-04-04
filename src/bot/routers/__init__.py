from aiogram import Router
from aiogram.filters import ExceptionTypeFilter
from aiogram_dialog.api.exceptions import (
    InvalidStackIdError,
    OutdatedIntent,
    UnknownIntent,
    UnknownState,
)

from src.bot.filters.admin_gate import AdminGateMiddleware
from src.bot.routers.extra.error import on_lost_context

from . import dashboard, extra, menu, subscription
from .dashboard import (
    access,
    broadcast,
    importer,
    promocodes,
    remnashop,
    remnawave,
    statistics,
    users,
)

__all__ = [
    "setup_routers",
]


def _apply_admin_gate(router: Router) -> None:
    """Attach AdminGateMiddleware to a router so all its handlers are blocked
    when SHOP_ADMIN_ENABLED is False."""
    gate = AdminGateMiddleware()
    router.message.middleware(gate)
    router.callback_query.middleware(gate)


def setup_routers(router: Router) -> None:
    # WARNING: The order of router registration matters!

    # --- Admin-gated dialog routers ---
    # These are blocked when SHOP_ADMIN_ENABLED=false.
    # Buttons are already hidden in the dashboard, but the middleware provides
    # defence-in-depth against direct navigation.
    _admin_gated_routers = [
        access.dialog.router,
        broadcast.dialog.router,
        promocodes.dialog.router,
        #
        remnashop.dialog.router,
        remnashop.gateways.dialog.router,
        remnashop.referral.dialog.router,
        remnashop.notifications.dialog.router,
        remnashop.plans.dialog.router,
        #
        remnawave.dialog.router,
        #
        importer.dialog.router,
    ]

    for r in _admin_gated_routers:
        _apply_admin_gate(r)

    routers = [
        extra.payment.router,
        extra.notification.router,
        extra.test.router,
        extra.commands.router,
        extra.member.router,
        extra.goto.router,
        #
        menu.handlers.router,
        menu.dialog.router,
        #
        subscription.dialog.router,
        #
        dashboard.dialog.router,
        statistics.dialog.router,
        *_admin_gated_routers,
        #
        # Users: NOT gated — MUST stay enabled for emergency user management
        # (block abusers, inspect subscriptions, grant access).
        users.dialog.router,
        users.user.dialog.router,
    ]

    router.include_routers(*routers)


def setup_error_handlers(router: Router) -> None:
    router.errors.register(on_lost_context, ExceptionTypeFilter(UnknownIntent))
    router.errors.register(on_lost_context, ExceptionTypeFilter(UnknownState))
    router.errors.register(on_lost_context, ExceptionTypeFilter(OutdatedIntent))
    router.errors.register(on_lost_context, ExceptionTypeFilter(InvalidStackIdError))
