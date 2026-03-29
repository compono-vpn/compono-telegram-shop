from typing import Any

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.core.config import AppConfig
from src.core.enums import Currency
from src.infrastructure.billing import BillingClient, billing_gateway_to_dto
from src.infrastructure.database.models.dto import PaymentGatewayDto
from src.services.payment_gateway import PaymentGatewayService


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


@inject
async def gateway_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    payment_gateway_service: FromDishka[PaymentGatewayService],
    **kwargs: Any,
) -> dict[str, Any]:
    gateway_id = dialog_manager.dialog_data["gateway_id"]
    # Gateway settings (secrets) are not exposed via billing API,
    # so we still use PaymentGatewayService for detail view with settings.
    gateway = await payment_gateway_service.get(gateway_id=gateway_id)

    if not gateway:
        raise ValueError(f"Gateway '{gateway_id}' not found")

    if not gateway.settings:
        raise ValueError(f"Gateway '{gateway_id}' has not settings")

    return {
        "id": gateway.id,
        "gateway_type": gateway.type,
        "is_active": gateway.is_active,
        "settings": gateway.settings.get_settings_as_list_data,
        "webhook": config.get_webhook(gateway.type),
        "requires_webhook": gateway.requires_webhook,
    }


@inject
async def field_getter(
    dialog_manager: DialogManager,
    payment_gateway_service: FromDishka[PaymentGatewayService],
    **kwargs: Any,
) -> dict[str, Any]:
    gateway_id = dialog_manager.dialog_data["gateway_id"]
    selected_field = dialog_manager.dialog_data["selected_field"]

    # Gateway settings need local service for secret field display
    gateway = await payment_gateway_service.get(gateway_id=gateway_id)

    if not gateway:
        raise ValueError(f"Gateway '{gateway_id}' not found")

    if not gateway.settings:
        raise ValueError(f"Gateway '{gateway_id}' has not settings")

    return {
        "gateway_type": gateway.type,
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
