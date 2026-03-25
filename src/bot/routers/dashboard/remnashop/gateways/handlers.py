from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode, SubManager
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from httpx import HTTPStatusError
from loguru import logger
from pydantic import SecretStr

from src.bot.states import RemnashopGateways
from src.core.constants import USER_KEY
from src.core.enums import Currency
from src.core.utils.formatters import format_user_log as log
from src.core.utils.message_payload import MessagePayload
from src.infrastructure.billing.client import BillingClient
from src.infrastructure.database.models.dto import UserDto
from src.services.notification import NotificationService


@inject
async def on_gateway_select(
    callback: CallbackQuery,
    widget: Button,
    sub_manager: SubManager,
    billing_client: FromDishka[BillingClient],
    notification_service: FromDishka[NotificationService],
) -> None:
    user: UserDto = sub_manager.middleware_data[USER_KEY]
    gateway_id = int(sub_manager.item_id)
    gateway = await billing_client.get_gateway(gateway_id)

    if not gateway:
        raise ValueError(f"Attempted to select non-existent gateway '{gateway_id}'")

    logger.info(f"{log(user)} Gateway '{gateway_id}' selected")

    if not gateway.get("settings"):
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-gateway-not-configurable"),
        )
        return

    sub_manager.manager.dialog_data["gateway_id"] = gateway_id
    await sub_manager.switch_to(state=RemnashopGateways.SETTINGS)


@inject
async def on_gateway_test(
    callback: CallbackQuery,
    widget: Button,
    sub_manager: SubManager,
    billing_client: FromDishka[BillingClient],
    notification_service: FromDishka[NotificationService],
) -> None:
    user: UserDto = sub_manager.middleware_data[USER_KEY]
    gateway_id = int(sub_manager.item_id)
    gateway = await billing_client.get_gateway(gateway_id)

    if not gateway:
        raise ValueError(f"Attempted to test non-existent gateway '{gateway_id}'")

    settings = gateway.get("settings")
    if settings and isinstance(settings, dict) and not settings.get("is_configure", True):
        logger.warning(f"{log(user)} Gateway '{gateway_id}' is not configured")
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-gateway-not-configured"),
        )
        return

    logger.info(f"{log(user)} Testing gateway '{gateway_id}'")

    try:
        payment = await billing_client.create_test_payment(
            telegram_id=user.telegram_id,
            gateway_type=gateway.get("type"),
        )
        logger.info(f"{log(user)} Test payment successful for gateway '{gateway_id}'")
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(
                i18n_key="ntf-gateway-test-payment-created",
                i18n_kwargs={"url": payment.get("url", "")},
            ),
        )

    except (HTTPStatusError, Exception) as exception:
        logger.exception(
            f"{log(user)} Test payment failed for gateway '{gateway_id}'. Exception: {exception}"
        )
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-gateway-test-payment-error"),
        )
        raise


@inject
async def on_active_toggle(
    callback: CallbackQuery,
    widget: Button,
    sub_manager: SubManager,
    billing_client: FromDishka[BillingClient],
    notification_service: FromDishka[NotificationService],
) -> None:
    await sub_manager.load_data()
    user: UserDto = sub_manager.middleware_data[USER_KEY]
    gateway_id = int(sub_manager.item_id)
    gateway = await billing_client.get_gateway(gateway_id)

    if not gateway:
        raise ValueError(f"Attempted to toggle non-existent gateway '{gateway_id}'")

    settings = gateway.get("settings")
    if settings and isinstance(settings, dict) and not settings.get("is_configure", True):
        logger.warning(f"{log(user)} Gateway '{gateway_id}' is not configured")
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-gateway-not-configured"),
        )
        return

    gateway["is_active"] = not gateway.get("is_active", False)
    logger.info(f"{log(user)} Toggled active state for gateway '{gateway_id}'")
    try:
        await billing_client.update_gateway(gateway)
    except HTTPStatusError as e:
        logger.error(f"{log(user)} Failed to toggle gateway: {e.response.status_code}")


async def on_field_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_field: str,
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    dialog_manager.dialog_data["selected_field"] = selected_field
    logger.info(f"{log(user)} Selected field '{selected_field}' for editing")
    await dialog_manager.switch_to(state=RemnashopGateways.FIELD)


@inject
async def on_field_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    billing_client: FromDishka[BillingClient],
    notification_service: FromDishka[NotificationService],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    gateway_id = dialog_manager.dialog_data["gateway_id"]
    selected_field = dialog_manager.dialog_data["selected_field"]

    if message.text is None:
        logger.warning(f"{log(user)} Empty input for field '{selected_field}'")
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-gateway-field-wrong-value"),
        )
        return

    gateway = await billing_client.get_gateway(gateway_id)

    if not gateway or not gateway.get("settings"):
        await dialog_manager.switch_to(state=RemnashopGateways.MAIN)
        raise ValueError(f"Attempted update of non-existent gateway '{gateway_id}'")

    input_value = message.text

    # Update the field in settings
    settings = gateway.get("settings", {})
    if isinstance(settings, dict):
        settings[selected_field] = input_value
        gateway["settings"] = settings

    try:
        await billing_client.update_gateway(gateway)
    except HTTPStatusError as e:
        logger.error(f"{log(user)} Failed to update gateway field: {e.response.status_code}")
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-gateway-field-wrong-value"),
        )
        return

    logger.info(f"{log(user)} Updated '{selected_field}' for gateway '{gateway_id}'")
    await dialog_manager.switch_to(state=RemnashopGateways.SETTINGS)


@inject
async def on_default_currency_select(
    callback: CallbackQuery,
    widget: Select[Currency],
    dialog_manager: DialogManager,
    selected_currency: Currency,
    billing_client: FromDishka[BillingClient],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    logger.info(f"{log(user)} Set default currency '{selected_currency}'")
    try:
        await billing_client.set_default_currency(selected_currency.value)
    except HTTPStatusError as e:
        logger.error(f"{log(user)} Failed to set default currency: {e.response.status_code}")


@inject
async def on_gateway_move(
    callback: CallbackQuery,
    widget: Button,
    sub_manager: SubManager,
    billing_client: FromDishka[BillingClient],
) -> None:
    await sub_manager.load_data()
    user: UserDto = sub_manager.middleware_data[USER_KEY]
    gateway_id = int(sub_manager.item_id)

    moved = await billing_client.move_gateway_up(gateway_id)
    if moved:
        logger.info(f"{log(user)} Moved gateway '{gateway_id}' up successfully")
    else:
        logger.warning(f"{log(user)} Failed to move gateway '{gateway_id}' up")
