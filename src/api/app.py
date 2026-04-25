from aiogram import Dispatcher
from fastapi import FastAPI, Request, Response
from prometheus_client import make_asgi_app
from starlette.middleware.cors import CORSMiddleware

from src.api.endpoints import (
    TelegramWebhookEndpoint,
    health_router,
)
from src.core.config import AppConfig
from src.lifespan import lifespan


def create_app(config: AppConfig, dispatcher: Dispatcher) -> FastAPI:
    app: FastAPI = FastAPI(lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def no_cache_api(request: Request, call_next):
        response: Response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return response

    app.include_router(health_router)
    app.mount("/metrics", make_asgi_app())

    telegram_webhook_endpoint = TelegramWebhookEndpoint(
        dispatcher=dispatcher,
        secret_token=config.bot.secret_token.get_secret_value(),
    )
    telegram_webhook_endpoint.register(app=app, path=config.bot.webhook_path)
    app.state.telegram_webhook_endpoint = telegram_webhook_endpoint
    app.state.dispatcher = dispatcher

    return app
