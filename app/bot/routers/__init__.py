from . import dashboard, menu
from .dashboard import broadcast, plans, promocodes, remnashop, remnawave, user, users

# NOTE: Order matters!
routers = [
    menu.handlers.router,  # NOTE: Must be registered first to handle common entrypoints!
    menu.dialog.router,
    dashboard.dialog.router,
    broadcast.dialog.router,
    plans.dialog.router,
    promocodes.dialog.router,
    remnashop.dialog.router,
    remnawave.dialog.router,
    user.dialog.router,
    users.dialog.router,
]

__all__ = [
    "routers",
]
