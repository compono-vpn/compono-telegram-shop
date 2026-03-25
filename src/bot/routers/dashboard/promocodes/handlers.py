import re

from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode, StartMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from httpx import HTTPStatusError
from loguru import logger

from src.bot.states import DashboardPromocodes
from src.core.constants import USER_KEY
from src.core.enums import PromocodeAvailability, PromocodeRewardType
from src.core.utils.adapter import DialogDataAdapter
from src.core.utils.formatters import format_user_log as log
from src.core.utils.message_payload import MessagePayload
from src.core.utils.validators import is_double_click, parse_int
from src.infrastructure.billing.client import BillingClient
from src.infrastructure.database.models.dto import PlanSnapshotDto, PromocodeDto, UserDto
from src.services.notification import NotificationService


async def on_active_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    adapter = DialogDataAdapter(dialog_manager)
    promocode = adapter.load(PromocodeDto)

    if not promocode:
        raise ValueError("PromocodeDto not found in dialog data")

    promocode.is_active = not promocode.is_active
    adapter.save(promocode)
    logger.debug(f"{log(user)} Toggled promocode active to '{promocode.is_active}'")


@inject
async def on_code_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notification_service: FromDishka[NotificationService],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]

    if not message.text or not re.match(r"^[A-Za-z0-9_-]+$", message.text):
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-promocode-invalid-code"),
        )
        return

    adapter = DialogDataAdapter(dialog_manager)
    promocode = adapter.load(PromocodeDto)

    if not promocode:
        raise ValueError("PromocodeDto not found in dialog data")

    promocode.code = message.text.upper()
    adapter.save(promocode)
    logger.info(f"{log(user)} Set promocode code to '{promocode.code}'")
    await dialog_manager.switch_to(state=DashboardPromocodes.CONFIGURATOR)


async def on_type_select(
    callback: CallbackQuery,
    widget: Select[PromocodeRewardType],
    dialog_manager: DialogManager,
    selected_type: PromocodeRewardType,
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    adapter = DialogDataAdapter(dialog_manager)
    promocode = adapter.load(PromocodeDto)

    if not promocode:
        raise ValueError("PromocodeDto not found in dialog data")

    promocode.reward_type = selected_type
    adapter.save(promocode)
    logger.info(f"{log(user)} Set promocode reward type to '{selected_type}'")
    await dialog_manager.switch_to(state=DashboardPromocodes.CONFIGURATOR)


async def on_availability_select(
    callback: CallbackQuery,
    widget: Select[PromocodeAvailability],
    dialog_manager: DialogManager,
    selected_availability: PromocodeAvailability,
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    adapter = DialogDataAdapter(dialog_manager)
    promocode = adapter.load(PromocodeDto)

    if not promocode:
        raise ValueError("PromocodeDto not found in dialog data")

    promocode.availability = selected_availability
    adapter.save(promocode)
    logger.info(f"{log(user)} Set promocode availability to '{selected_availability}'")
    await dialog_manager.switch_to(state=DashboardPromocodes.CONFIGURATOR)


@inject
async def on_reward_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notification_service: FromDishka[NotificationService],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]

    adapter = DialogDataAdapter(dialog_manager)
    promocode = adapter.load(PromocodeDto)

    if not promocode:
        raise ValueError("PromocodeDto not found in dialog data")

    number = parse_int(message.text)

    reward_ranges = {
        PromocodeRewardType.PERSONAL_DISCOUNT: (1, 100),
        PromocodeRewardType.PURCHASE_DISCOUNT: (1, 100),
        PromocodeRewardType.DURATION: (1, 3650),
        PromocodeRewardType.TRAFFIC: (1, 99999),
        PromocodeRewardType.DEVICES: (1, 100),
    }
    min_val, max_val = reward_ranges.get(promocode.reward_type, (1, 100))

    if number is None or not (min_val <= number <= max_val):
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-promocode-invalid-reward"),
        )
        return

    promocode.reward = number
    adapter.save(promocode)
    logger.info(f"{log(user)} Set promocode reward to '{number}'")
    await dialog_manager.switch_to(state=DashboardPromocodes.CONFIGURATOR)


@inject
async def on_lifetime_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notification_service: FromDishka[NotificationService],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]

    number = parse_int(message.text)

    if number is None or (number < -1 or number == 0):
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-promocode-invalid-lifetime"),
        )
        return

    adapter = DialogDataAdapter(dialog_manager)
    promocode = adapter.load(PromocodeDto)

    if not promocode:
        raise ValueError("PromocodeDto not found in dialog data")

    promocode.lifetime = number
    adapter.save(promocode)
    logger.info(f"{log(user)} Set promocode lifetime to '{number}'")
    await dialog_manager.switch_to(state=DashboardPromocodes.CONFIGURATOR)


@inject
async def on_confirm(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    billing_client: FromDishka[BillingClient],
    notification_service: FromDishka[NotificationService],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    adapter = DialogDataAdapter(dialog_manager)
    promocode = adapter.load(PromocodeDto)

    if not promocode:
        raise ValueError("PromocodeDto not found in dialog data")

    try:
        data = promocode.model_dump(mode="json")
        if promocode.id is not None:
            # Update existing
            await billing_client.update_promocode(data)
            await notification_service.notify_user(
                user=user,
                payload=MessagePayload(
                    i18n_key="ntf-promocode-updated",
                    i18n_kwargs={"code": promocode.code},
                ),
            )
            logger.info(f"{log(user)} Updated promocode '{promocode.code}'")
        else:
            # Create new
            await billing_client.create_promocode(data)
            await notification_service.notify_user(
                user=user,
                payload=MessagePayload(
                    i18n_key="ntf-promocode-created",
                    i18n_kwargs={"code": promocode.code},
                ),
            )
            logger.info(f"{log(user)} Created promocode '{promocode.code}'")
    except HTTPStatusError as e:
        logger.error(f"{log(user)} Failed to save promocode: {e.response.status_code}")
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-error"),
        )
        return

    await dialog_manager.start(state=DashboardPromocodes.MAIN, mode=StartMode.RESET_STACK)


@inject
async def on_list_select(
    callback: CallbackQuery,
    widget: Select[int],
    dialog_manager: DialogManager,
    selected_id: int,
    billing_client: FromDishka[BillingClient],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    promocode_data = await billing_client.get_promocode(selected_id)

    if not promocode_data:
        raise ValueError(f"Promocode '{selected_id}' not found")

    promocode = PromocodeDto.model_validate(promocode_data)
    adapter = DialogDataAdapter(dialog_manager)
    adapter.save(promocode)
    logger.info(f"{log(user)} Selected promocode '{promocode.code}' for editing")
    await dialog_manager.switch_to(state=DashboardPromocodes.CONFIGURATOR)


@inject
async def on_list(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    billing_client: FromDishka[BillingClient],
    notification_service: FromDishka[NotificationService],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    promocodes = await billing_client.list_promocodes()

    if not promocodes:
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-promocode-list-empty"),
        )
        return

    await dialog_manager.switch_to(state=DashboardPromocodes.LIST)


@inject
async def on_search_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    billing_client: FromDishka[BillingClient],
    notification_service: FromDishka[NotificationService],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]

    if not message.text:
        return

    promocode_data = await billing_client.get_promocode_by_code(message.text.strip().upper())

    if not promocode_data:
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-promocode-not-found"),
        )
        return

    promocode = PromocodeDto.model_validate(promocode_data)
    adapter = DialogDataAdapter(dialog_manager)
    adapter.save(promocode)
    logger.info(f"{log(user)} Found promocode '{promocode.code}' via search")
    await dialog_manager.switch_to(state=DashboardPromocodes.CONFIGURATOR)


@inject
async def on_delete(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    billing_client: FromDishka[BillingClient],
    notification_service: FromDishka[NotificationService],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    adapter = DialogDataAdapter(dialog_manager)
    promocode = adapter.load(PromocodeDto)

    if not promocode or promocode.id is None:
        raise ValueError("PromocodeDto not found in dialog data")

    if is_double_click(dialog_manager, key=f"delete_confirm_{promocode.id}", cooldown=10):
        try:
            await billing_client.delete_promocode(promocode.id)
        except HTTPStatusError as e:
            logger.error(f"{log(user)} Failed to delete promocode: {e.response.status_code}")
            await notification_service.notify_user(
                user=user,
                payload=MessagePayload(i18n_key="ntf-error"),
            )
            return

        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-promocode-deleted"),
        )
        logger.info(f"{log(user)} Deleted promocode '{promocode.code}'")
        await dialog_manager.start(state=DashboardPromocodes.MAIN, mode=StartMode.RESET_STACK)
        return

    await notification_service.notify_user(
        user=user,
        payload=MessagePayload(i18n_key="ntf-double-click-confirm"),
    )


@inject
async def on_max_activations_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notification_service: FromDishka[NotificationService],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]

    number = parse_int(message.text)

    if number is None or (number < -1 or number == 0):
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-promocode-invalid-max-activations"),
        )
        return

    adapter = DialogDataAdapter(dialog_manager)
    promocode = adapter.load(PromocodeDto)

    if not promocode:
        raise ValueError("PromocodeDto not found in dialog data")

    promocode.max_activations = number
    adapter.save(promocode)
    logger.info(f"{log(user)} Set promocode max_activations to '{number}'")
    await dialog_manager.switch_to(state=DashboardPromocodes.CONFIGURATOR)


@inject
async def on_purchase_discount_max_days_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notification_service: FromDishka[NotificationService],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]

    number = parse_int(message.text)

    if number is None or (number < -1 or number == 0):
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-promocode-invalid-max-days"),
        )
        return

    adapter = DialogDataAdapter(dialog_manager)
    promocode = adapter.load(PromocodeDto)

    if not promocode:
        raise ValueError("PromocodeDto not found in dialog data")

    promocode.purchase_discount_max_days = number if number > 0 else None
    adapter.save(promocode)
    logger.info(f"{log(user)} Set promocode purchase_discount_max_days to '{number}'")
    await dialog_manager.switch_to(state=DashboardPromocodes.CONFIGURATOR)


@inject
async def on_allowed_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notification_service: FromDishka[NotificationService],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]

    if not message.text:
        return

    try:
        ids = [int(x.strip()) for x in message.text.split(",") if x.strip()]
        if not ids:
            raise ValueError
    except ValueError:
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-promocode-invalid-allowed"),
        )
        return

    adapter = DialogDataAdapter(dialog_manager)
    promocode = adapter.load(PromocodeDto)

    if not promocode:
        raise ValueError("PromocodeDto not found in dialog data")

    promocode.allowed_telegram_ids = ids
    adapter.save(promocode)
    logger.info(f"{log(user)} Set promocode allowed_telegram_ids to '{ids}'")
    await dialog_manager.switch_to(state=DashboardPromocodes.CONFIGURATOR)


async def on_plan_select(
    callback: CallbackQuery,
    widget: Select[int],
    dialog_manager: DialogManager,
    selected_plan_id: int,
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    logger.info(f"{log(user)} Selected plan '{selected_plan_id}' for promocode")
    dialog_manager.dialog_data["selected_plan_id"] = selected_plan_id
    await dialog_manager.switch_to(state=DashboardPromocodes.PLAN_DURATION)


@inject
async def on_plan_duration_select(
    callback: CallbackQuery,
    widget: Select[int],
    dialog_manager: DialogManager,
    selected_duration: int,
    billing_client: FromDishka[BillingClient],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    selected_plan_id = dialog_manager.dialog_data["selected_plan_id"]
    plan_data = await billing_client.get_plan(selected_plan_id)

    if not plan_data:
        raise ValueError(f"Plan '{selected_plan_id}' not found")

    adapter = DialogDataAdapter(dialog_manager)
    promocode = adapter.load(PromocodeDto)

    if not promocode:
        raise ValueError("PromocodeDto not found in dialog data")

    plan_snapshot = PlanSnapshotDto(
        name=plan_data["name"],
        type=plan_data.get("type"),
        traffic_limit=plan_data.get("traffic_limit", -1),
        device_limit=plan_data.get("device_limit", -1),
        duration=selected_duration,
    )
    promocode.plan = plan_snapshot
    adapter.save(promocode)
    logger.info(f"{log(user)} Set promocode plan to '{plan_data['name']}' with duration '{selected_duration}'")
    await dialog_manager.switch_to(state=DashboardPromocodes.CONFIGURATOR)
