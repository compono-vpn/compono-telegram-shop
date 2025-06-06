from . import dashboard, menu
from .dashboard import remnashop, remnawave

routers = [
    menu.handlers.router,  # NOTE: Must be registered first to handle common entrypoints before dialogs
    menu.dialog.router,
    dashboard.dialog.router,
    remnashop.dialog.router,
    remnawave.dialog.router,
]

__all__ = [
    "routers",
]
