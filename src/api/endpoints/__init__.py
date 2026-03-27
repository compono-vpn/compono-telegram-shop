from .app import router as app_router
from .health import router as health_router
from .payments import router as payments_router
from .remnawave import router as remnawave_router
from .telegram import TelegramWebhookEndpoint
from .web import router as web_router

__all__ = [
    "app_router",
    "health_router",
    "payments_router",
    "remnawave_router",
    "web_router",
    "TelegramWebhookEndpoint",
]
