import json

from pydantic import ValidationError

from app.core.config import AppConfig
from app.core.logger import setup_logging

config = AppConfig.get()
setup_logging(config.logging)

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import FastAPI, Request
from starlette.middleware.cors import CORSMiddleware

from app.bot.commands import commands_delete, commands_setup
from app.bot.webhook import webhook_shutdown, webhook_startup
from app.core.constants import BOT_KEY, HEADER_SECRET_TOKEN
from app.factories import create_bot, create_dispatcher

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting application")

    bot: Bot = create_bot(token=config.bot.token.get_secret_value())
    dispatcher: Dispatcher = create_dispatcher(config)

    application.state.bot = bot
    application.state.dispatcher = dispatcher

    await webhook_startup(bot, dispatcher, config)
    await commands_setup(bot, config)
    yield  # TODO: Notify devs for start and maintenance
    await commands_delete(bot, config)
    await webhook_shutdown(bot, config)

    logger.info("Stopping application")


app = FastAPI(
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post(config.bot.webhook_path)
async def webhook(request: Request, update: Update) -> Optional[dict]:
    bot: Bot = request.app.state.bot
    dispatcher: Dispatcher = request.app.state.dispatcher

    secret_token = request.headers.get(HEADER_SECRET_TOKEN)

    if not secret_token:
        logger.error("Missing secret token")
        return {"status": "error", "message": "Missing secret token"}

    if secret_token != config.bot.secret_token.get_secret_value():
        logger.error("Wrong secret token")
        return {"status": "error", "message": "Wrong secret token"}

    try:
        request_data = await request.json()
        update = Update.model_validate(request_data, context={BOT_KEY: bot})

        await dispatcher.feed_webhook_update(bot, update)
        return {"ok": True}
    except json.JSONDecodeError as exception:
        logger.error(
            f"Invalid JSON in webhook request: {exception}. "
            f"Request body: {await request.body()}"
        )
        return {"status": "error", "message": "Invalid JSON format"}
    except ValidationError as exception:
        logger.error(f"Webhook update validation error: {exception}. Data: {request_data}")
        return {"status": "error", "message": "Invalid update format"}
    except Exception as exception:
        logger.exception(f"Unhandled exception during webhook update processing: {exception}")
        return {"status": "error", "message": "Internal server error"}


if __name__ == "__main__":
    uvicorn.run(app, host=config.bot.host, port=config.bot.port)
