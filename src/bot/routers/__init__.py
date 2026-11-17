from aiogram import Router
from aiogram.filters import ExceptionTypeFilter
from aiogram_dialog.api.exceptions import (
    InvalidStackIdError,
    OutdatedIntent,
    UnknownIntent,
    UnknownState,
)

from src.bot.filters import PrivilegedFilter
from src.bot.routers.extra.error import on_lost_context

from . import dashboard, extra, menu, subscription
from .dashboard import (
    statistics,
    users,
)

__all__ = [
    "setup_routers",
]


def setup_routers(router: Router) -> None:
    # WARNING: The order of router registration matters!

    routers = [
        extra.payment.router,
        extra.payment_nudge.router,
        extra.recovery_offer.router,
        extra.notification.router,
        extra.commands.router,
        extra.member.router,
        extra.goto.router,
        extra.cancel_survey.router,
        extra.source_survey.router,
        extra.dedicated_ip.router,
        extra.tv_pair.router,
        extra.setup_checkin.router,
        #
        menu.handlers.router,
        menu.dialog.router,
        #
        subscription.dialog.router,
        #
        dashboard.dialog.router,
        statistics.dialog.router,
        #
        # Users: emergency user management (block abusers, inspect
        # subscriptions, grant access).  Kept until Django admin panel.
        users.dialog.router,
        users.user.dialog.router,
    ]

    # The admin dialogs change roles and grant subscriptions: only ADMIN/DEV updates reach them,
    # whatever callback data arrives.
    for admin_router in (
        dashboard.dialog.router,
        statistics.dialog.router,
        users.dialog.router,
        users.user.dialog.router,
    ):
        admin_router.message.filter(PrivilegedFilter())
        admin_router.callback_query.filter(PrivilegedFilter())

    router.include_routers(*routers)


def setup_error_handlers(router: Router) -> None:
    router.errors.register(on_lost_context, ExceptionTypeFilter(UnknownIntent))
    router.errors.register(on_lost_context, ExceptionTypeFilter(UnknownState))
    router.errors.register(on_lost_context, ExceptionTypeFilter(OutdatedIntent))
    router.errors.register(on_lost_context, ExceptionTypeFilter(InvalidStackIdError))
