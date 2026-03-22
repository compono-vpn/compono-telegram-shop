from typing import Any

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.core.config import AppConfig
from src.core.enums import Currency
from src.infrastructure.billing.client import BillingClient


@inject
async def gateways_getter(
    dialog_manager: DialogManager,
    billing_client: FromDishka[BillingClient],
    **kwargs: Any,
) -> dict[str, Any]:
    gateways = await billing_client.list_gateways()

    formatted_gateways = [
        {
            "id": gateway.get("id"),
            "gateway_type": gateway.get("type"),
            "is_active": gateway.get("is_active"),
        }
        for gateway in gateways
    ]

    return {
        "gateways": formatted_gateways,
    }


@inject
async def gateway_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    billing_client: FromDishka[BillingClient],
    **kwargs: Any,
) -> dict[str, Any]:
    gateway_id = dialog_manager.dialog_data["gateway_id"]
    gateway = await billing_client.get_gateway(gateway_id)

    if not gateway:
        raise ValueError(f"Gateway '{gateway_id}' not found")

    settings = gateway.get("settings")
    if not settings:
        raise ValueError(f"Gateway '{gateway_id}' has no settings")

    # Build settings list from the dict returned by billing
    settings_list = [
        {"field": k, "value": v}
        for k, v in settings.items()
        if k not in ("id", "gateway_id")
    ] if isinstance(settings, dict) else settings.get("settings_list", [])

    gateway_type = gateway.get("type")

    return {
        "id": gateway.get("id"),
        "gateway_type": gateway_type,
        "is_active": gateway.get("is_active"),
        "settings": settings_list,
        "webhook": config.get_webhook(gateway_type),
        "requires_webhook": gateway.get("requires_webhook", False),
    }


@inject
async def field_getter(
    dialog_manager: DialogManager,
    billing_client: FromDishka[BillingClient],
    **kwargs: Any,
) -> dict[str, Any]:
    gateway_id = dialog_manager.dialog_data["gateway_id"]
    selected_field = dialog_manager.dialog_data["selected_field"]

    gateway = await billing_client.get_gateway(gateway_id)

    if not gateway:
        raise ValueError(f"Gateway '{gateway_id}' not found")

    if not gateway.get("settings"):
        raise ValueError(f"Gateway '{gateway_id}' has no settings")

    return {
        "gateway_type": gateway.get("type"),
        "field": selected_field,
    }


@inject
async def currency_getter(
    dialog_manager: DialogManager,
    billing_client: FromDishka[BillingClient],
    **kwargs: Any,
) -> dict[str, Any]:
    default_currency_str = await billing_client.get_default_currency()

    return {
        "currency_list": [
            {
                "symbol": currency.symbol,
                "currency": currency.value,
                "enabled": currency.value == default_currency_str,
            }
            for currency in Currency
        ]
    }


@inject
async def placement_getter(
    dialog_manager: DialogManager,
    billing_client: FromDishka[BillingClient],
    **kwargs: Any,
) -> dict[str, Any]:
    gateways = await billing_client.list_gateways()

    formatted_gateways = [
        {
            "id": gateway.get("id"),
            "gateway_type": gateway.get("type"),
            "is_active": gateway.get("is_active"),
        }
        for gateway in gateways
    ]

    return {
        "gateways": formatted_gateways,
    }
