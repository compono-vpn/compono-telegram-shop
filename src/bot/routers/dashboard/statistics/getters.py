from typing import Any, Optional

from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.common import ManagedScroll
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from fluentogram import TranslatorRunner
from httpx import HTTPStatusError
from loguru import logger

from src.infrastructure.billing.client import BillingClient


@inject
async def statistics_getter(
    dialog_manager: DialogManager,
    i18n: FromDishka[TranslatorRunner],
    billing_client: FromDishka[BillingClient],
    **kwargs: Any,
) -> dict[str, Any]:
    widget: Optional[ManagedScroll] = dialog_manager.find("statistics")

    if not widget:
        raise ValueError()

    current_page = await widget.get_page()

    try:
        statistics = await billing_client.get_statistics()
    except HTTPStatusError:
        logger.error("Failed to fetch statistics from billing service")
        statistics = {}

    pages = {
        0: "msg-statistics-users",
        1: "msg-statistics-transactions",
        2: "msg-statistics-subscriptions",
        3: "msg-statistics-plans",
        4: "msg-statistics-promocodes",
    }

    template = pages.get(current_page)
    if template is None:
        raise ValueError(f"Invalid statistics page index: '{current_page}'")

    # The billing service returns pre-computed statistics keyed by page type
    page_keys = {
        0: "users",
        1: "transactions",
        2: "subscriptions",
        3: "plans",
        4: "promocodes",
    }

    page_data = statistics.get(page_keys[current_page], {})
    formatted_message = i18n.get(template, **page_data)

    return {
        "pages": 4,
        "current_page": current_page + 1,
        "statistics": formatted_message,
    }
