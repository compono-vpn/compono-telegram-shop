from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode, SubManager
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.bot.states import RemnashopGateways
from src.core.constants import USER_KEY
from src.core.enums import Currency, PaymentGatewayType
from src.core.utils.formatters import format_log_user
from src.infrastructure.database.models.dto import UserDto
from src.services import NotificationService, PaymentGatewayService


@inject
async def on_gateway_selected(
    callback: CallbackQuery,
    widget: Button,
    sub_manager: SubManager,
    payment_gateway_service: FromDishka[PaymentGatewayService],
    notification_service: FromDishka[NotificationService],
) -> None:
    user: UserDto = sub_manager.middleware_data[USER_KEY]
    gateway_id = int(sub_manager.item_id)
    gateway = await payment_gateway_service.get(gateway_id=gateway_id)

    if gateway.type == PaymentGatewayType.TELEGRAM_STARS:
        await notification_service.notify_user(user=user, text_key="ntf-gateway-not-configurable")
        return

    sub_manager.manager.dialog_data["gateway_id"] = gateway_id
    await sub_manager.switch_to(state=RemnashopGateways.SHOP)


@inject
async def on_gateway_test(
    callback: CallbackQuery,
    widget: Button,
    sub_manager: SubManager,
    payment_gateway_service: FromDishka[PaymentGatewayService],
    notification_service: FromDishka[NotificationService],
) -> None:
    user: UserDto = sub_manager.middleware_data[USER_KEY]
    gateway_id = int(sub_manager.item_id)
    gateway = await payment_gateway_service.get(gateway_id=gateway_id)

    # TODO: Implement test payment


@inject
async def on_active_toggle(
    callback: CallbackQuery,
    widget: Button,
    sub_manager: SubManager,
    payment_gateway_service: FromDishka[PaymentGatewayService],
    notification_service: FromDishka[NotificationService],
) -> None:
    await sub_manager.load_data()
    user: UserDto = sub_manager.middleware_data[USER_KEY]
    gateway_id = int(sub_manager.item_id)
    gateway = await payment_gateway_service.get(gateway_id=gateway_id)

    if gateway.type != PaymentGatewayType.TELEGRAM_STARS:
        if not gateway.shop_id or not gateway.api_token:
            logger.warning(f"[{format_log_user(user)}] Gateway '{gateway_id}' is not configured")
            await notification_service.notify_user(user=user, text_key="ntf-gateway-not-configured")
            return

    gateway.is_active = not gateway.is_active
    logger.debug(f"[{format_log_user(user)}] Toggling active state for gateway '{gateway_id}'")
    await payment_gateway_service.update(gateway=gateway)


@inject
async def on_shop_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    payment_gateway_service: FromDishka[PaymentGatewayService],
    notification_service: FromDishka[NotificationService],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    gateway_id = dialog_manager.dialog_data["gateway_id"]

    if message.text is None or len(message.text) < 4:
        logger.warning(f"{format_log_user(user)} Provided empty gateway id input")
        await notification_service.notify_user(user=user, text_key="ntf-gateway-wrong-id")
        return

    gateway = await payment_gateway_service.get(gateway_id=gateway_id)
    gateway.shop_id = message.text

    await payment_gateway_service.update(gateway=gateway)
    await dialog_manager.switch_to(state=RemnashopGateways.TOKEN)


@inject
async def on_token_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    payment_gateway_service: FromDishka[PaymentGatewayService],
    notification_service: FromDishka[NotificationService],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    gateway_id = dialog_manager.dialog_data["gateway_id"]

    if message.text is None or len(message.text) < 8:
        logger.warning(f"{format_log_user(user)} Provided empty gateway token input")
        await notification_service.notify_user(user=user, text_key="ntf-gateway-wrong-token")
        return

    gateway = await payment_gateway_service.get(gateway_id=gateway_id)
    gateway.api_token = message.text  # TODO: Implement encrypt

    await payment_gateway_service.update(gateway=gateway)
    await dialog_manager.switch_to(state=RemnashopGateways.MAIN)


@inject
async def on_default_currency_selected(
    callback: CallbackQuery,
    widget: Select[Currency],
    dialog_manager: DialogManager,
    selected_currency: Currency,
    payment_gateway_service: FromDishka[PaymentGatewayService],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    await payment_gateway_service.set_default_currency(selected_currency)
