from aiogram import Router

from .admin_gate import (
    AdminGateMiddleware,
    admin_enabled_condition,
    get_admin_disabled_message,
    require_admin_enabled,
)
from .private import PrivateFilter
from .super_dev import SuperDevFilter

__all__ = [
    "AdminGateMiddleware",
    "SuperDevFilter",
    "admin_enabled_condition",
    "get_admin_disabled_message",
    "require_admin_enabled",
    "setup_global_filters",
]


def setup_global_filters(router: Router) -> None:
    filters = [
        PrivateFilter(),  # global filter allows only private chats
    ]

    for filter in filters:
        router.message.filter(filter)
