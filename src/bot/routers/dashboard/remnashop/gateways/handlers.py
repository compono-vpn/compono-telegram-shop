from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode, SubManager
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.bot.states import RemnashopGateways
from src.core.constants import USER_KEY
from src.core.enums import Currency
from src.core.utils.formatters import format_user_log as log
from src.core.utils.message_payload import MessagePayload
from src.infrastructure.billing import BillingClient
from src.models.dto import UserDto
from src.services.notification import NotificationService


@inject
async def on_gateway_select(
    callback: CallbackQuery,
    widget: Button,
    sub_manager: SubManager,
    billing: FromDishka[BillingClient],
    notification_service: FromDishka[NotificationService],
) -> None:
    user: UserDto = sub_manager.middleware_data[USER_KEY]
    gateway_id = int(sub_manager.item_id)
    gateway = await billing.get_gateway(gateway_id)

    if not gateway:
        raise ValueError(f"Attempted to select non-existent gateway '{gateway_id}'")

    logger.info(f"{log(user)} Gateway '{gateway_id}' selected")

    if not gateway.Settings:
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
    billing: FromDishka[BillingClient],
    notification_service: FromDishka[NotificationService],
) -> None:
    user: UserDto = sub_manager.middleware_data[USER_KEY]
    gateway_id = int(sub_manager.item_id)
    gateway = await billing.get_gateway(gateway_id)

    if not gateway:
        raise ValueError(f"Attempted to test non-existent gateway '{gateway_id}'")

    logger.info(f"{log(user)} Testing gateway '{gateway_id}'")

    try:
        payment = await billing.create_test_payment(user.telegram_id, gateway.Type)
        logger.info(f"{log(user)} Test payment successful for gateway '{gateway_id}'")
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(
                i18n_key="ntf-gateway-test-payment-created",
                i18n_kwargs={"url": payment.URL},
            ),
        )

    except Exception as exception:
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
    billing: FromDishka[BillingClient],
    notification_service: FromDishka[NotificationService],
) -> None:
    await sub_manager.load_data()
    user: UserDto = sub_manager.middleware_data[USER_KEY]
    gateway_id = int(sub_manager.item_id)
    gateway = await billing.get_gateway(gateway_id)

    if not gateway:
        raise ValueError(f"Attempted to toggle non-existent gateway '{gateway_id}'")

    new_active = not gateway.IsActive
    logger.info(f"{log(user)} Toggled active state for gateway '{gateway_id}' to {new_active}")
    await billing.update_gateway({"ID": gateway_id, "IsActive": new_active})


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
    billing: FromDishka[BillingClient],
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

    gateway = await billing.get_gateway(gateway_id)

    if not gateway or not gateway.Settings:
        await dialog_manager.switch_to(state=RemnashopGateways.MAIN)
        raise ValueError(f"Attempted update of non-existent gateway '{gateway_id}'")

    # Update the settings field via billing API
    settings = gateway.Settings
    if isinstance(settings, dict):
        settings[selected_field] = message.text
    await billing.update_gateway({"ID": gateway_id, "Settings": settings})

    logger.info(f"{log(user)} Updated '{selected_field}' for gateway '{gateway_id}'")
    await dialog_manager.switch_to(state=RemnashopGateways.SETTINGS)


@inject
async def on_default_currency_select(
    callback: CallbackQuery,
    widget: Select[Currency],
    dialog_manager: DialogManager,
    selected_currency: Currency,
    billing: FromDishka[BillingClient],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    logger.info(f"{log(user)} Set default currency '{selected_currency}'")
    await billing.set_default_currency(selected_currency.value)


@inject
async def on_gateway_move(
    callback: CallbackQuery,
    widget: Button,
    sub_manager: SubManager,
    billing: FromDishka[BillingClient],
) -> None:
    await sub_manager.load_data()
    user: UserDto = sub_manager.middleware_data[USER_KEY]
    gateway_id = int(sub_manager.item_id)

    moved = await billing.move_gateway_up(gateway_id)
    if moved:
        logger.info(f"{log(user)} Moved plan '{gateway_id}' up successfully")
    else:
        logger.warning(f"{log(user)} Failed to move plan '{gateway_id}' up")
