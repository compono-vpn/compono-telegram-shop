import re

from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode, StartMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.bot.states import DashboardPromocodes
from src.core.constants import USER_KEY
from src.core.enums import PromocodeAvailability, PromocodeRewardType
from src.core.utils.adapter import DialogDataAdapter
from src.core.utils.formatters import format_user_log as log
from src.core.utils.message_payload import MessagePayload
from src.core.utils.validators import is_double_click, parse_int
from src.infrastructure.database.models.dto import PromocodeDto, UserDto
from src.services.notification import NotificationService
from src.services.promocode import PromocodeService


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
    promocode_service: FromDishka[PromocodeService],
    notification_service: FromDishka[NotificationService],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    adapter = DialogDataAdapter(dialog_manager)
    promocode = adapter.load(PromocodeDto)

    if not promocode:
        raise ValueError("PromocodeDto not found in dialog data")

    if promocode.id is not None:
        # Update existing
        updated = await promocode_service.update(promocode)
        if updated:
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
        created = await promocode_service.create(promocode)
        if created:
            await notification_service.notify_user(
                user=user,
                payload=MessagePayload(
                    i18n_key="ntf-promocode-created",
                    i18n_kwargs={"code": promocode.code},
                ),
            )
            logger.info(f"{log(user)} Created promocode '{promocode.code}'")

    await dialog_manager.start(state=DashboardPromocodes.MAIN, mode=StartMode.RESET_STACK)


@inject
async def on_list_select(
    callback: CallbackQuery,
    widget: Select[int],
    dialog_manager: DialogManager,
    selected_id: int,
    promocode_service: FromDishka[PromocodeService],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    promocode = await promocode_service.get(selected_id)

    if not promocode:
        raise ValueError(f"Promocode '{selected_id}' not found")

    adapter = DialogDataAdapter(dialog_manager)
    adapter.save(promocode)
    logger.info(f"{log(user)} Selected promocode '{promocode.code}' for editing")
    await dialog_manager.switch_to(state=DashboardPromocodes.CONFIGURATOR)


@inject
async def on_list(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    promocode_service: FromDishka[PromocodeService],
    notification_service: FromDishka[NotificationService],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    promocodes = await promocode_service.get_all()

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
    promocode_service: FromDishka[PromocodeService],
    notification_service: FromDishka[NotificationService],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]

    if not message.text:
        return

    promocode = await promocode_service.get_by_code(message.text.strip().upper())

    if not promocode:
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-promocode-not-found"),
        )
        return

    adapter = DialogDataAdapter(dialog_manager)
    adapter.save(promocode)
    logger.info(f"{log(user)} Found promocode '{promocode.code}' via search")
    await dialog_manager.switch_to(state=DashboardPromocodes.CONFIGURATOR)


@inject
async def on_delete(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    promocode_service: FromDishka[PromocodeService],
    notification_service: FromDishka[NotificationService],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    adapter = DialogDataAdapter(dialog_manager)
    promocode = adapter.load(PromocodeDto)

    if not promocode or promocode.id is None:
        raise ValueError("PromocodeDto not found in dialog data")

    if is_double_click(dialog_manager, key=f"delete_confirm_{promocode.id}", cooldown=10):
        await promocode_service.delete(promocode.id)
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
