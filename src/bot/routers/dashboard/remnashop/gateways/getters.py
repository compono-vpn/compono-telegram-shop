from typing import Any

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.core.config import AppConfig
from src.core.enums import Currency
from src.infrastructure.billing import BillingClient


@inject
async def gateways_getter(
    dialog_manager: DialogManager,
    billing: FromDishka[BillingClient],
    **kwargs: Any,
) -> dict[str, Any]:
    billing_gateways = await billing.list_gateways()

    formatted_gateways = [
        {
            "id": g.ID,
            "gateway_type": f"{g.Type} [{g.Channel}]" if g.Channel else g.Type,
            "is_active": g.IsActive,
        }
        for g in billing_gateways
    ]

    return {
        "gateways": formatted_gateways,
    }


def _settings_to_list(settings: Any) -> list[dict[str, str]]:
    """Convert raw settings dict to list of {field, value} for display."""
    if not settings or not isinstance(settings, dict):
        return []
    return [
        {"field": k, "value": "***" if "key" in k.lower() or "secret" in k.lower() else str(v)}
        for k, v in settings.items()
        if k != "type"
    ]


@inject
async def gateway_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    billing: FromDishka[BillingClient],
    **kwargs: Any,
) -> dict[str, Any]:
    gateway_id = dialog_manager.dialog_data["gateway_id"]
    gateway = await billing.get_gateway(gateway_id=gateway_id)

    if not gateway:
        raise ValueError(f"Gateway '{gateway_id}' not found")

    webhook_url = f"https://{config.domain.get_secret_value()}/api/v1/payments/webhook/{gateway.Type.lower()}"

    return {
        "id": gateway.ID,
        "gateway_type": gateway.Type,
        "is_active": gateway.IsActive,
        "settings": _settings_to_list(gateway.Settings),
        "webhook": webhook_url,
        "requires_webhook": gateway.Type in ("PLATEGA", "YOOKASSA"),
    }


@inject
async def field_getter(
    dialog_manager: DialogManager,
    billing: FromDishka[BillingClient],
    **kwargs: Any,
) -> dict[str, Any]:
    gateway_id = dialog_manager.dialog_data["gateway_id"]
    selected_field = dialog_manager.dialog_data["selected_field"]

    gateway = await billing.get_gateway(gateway_id=gateway_id)

    if not gateway:
        raise ValueError(f"Gateway '{gateway_id}' not found")

    return {
        "gateway_type": gateway.Type,
        "field": selected_field,
    }


@inject
async def currency_getter(
    dialog_manager: DialogManager,
    billing: FromDishka[BillingClient],
    **kwargs: Any,
) -> dict[str, Any]:
    default_currency_str = await billing.get_default_currency()
    default_currency = Currency(default_currency_str) if default_currency_str else Currency.XTR
    return {
        "currency_list": [
            {
                "symbol": currency.symbol,
                "currency": currency.value,
                "enabled": currency == default_currency,
            }
            for currency in Currency
        ]
    }


@inject
async def placement_getter(
    dialog_manager: DialogManager,
    billing: FromDishka[BillingClient],
    **kwargs: Any,
) -> dict[str, Any]:
    billing_gateways = await billing.list_gateways()

    formatted_gateways = [
        {
            "id": g.ID,
            "gateway_type": f"{g.Type} [{g.Channel}]" if g.Channel else g.Type,
            "is_active": g.IsActive,
        }
        for g in billing_gateways
    ]

    return {
        "gateways": formatted_gateways,
    }
