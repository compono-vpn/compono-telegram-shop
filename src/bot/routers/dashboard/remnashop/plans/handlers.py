from decimal import ROUND_UP, Decimal, InvalidOperation

from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode, SubManager
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.bot.states import RemnashopPlans
from src.core.constants import USER_KEY
from src.core.enums import Currency, PlanAvailability, PlanType
from src.core.utils.adapter import DialogDataAdapter
from src.core.utils.formatters import format_log_user
from src.infrastructure.database.models.dto import PlanDto, PlanDurationDto, PlanPriceDto, UserDto
from src.services import NotificationService, PlanService
from src.services.user import UserService


@inject
async def on_plan_selected(
    callback: CallbackQuery,
    widget: Button,
    sub_manager: SubManager,
    plan_service: FromDishka[PlanService],
) -> None:
    plan: PlanDto = await plan_service.get(plan_id=int(sub_manager.item_id))
    logger.debug(f"Selected plan ID: {plan.id}")

    adapter = DialogDataAdapter(sub_manager.manager)
    adapter.save(plan)

    await sub_manager.switch_to(state=RemnashopPlans.PLAN)


@inject
async def on_plan_removed(
    callback: CallbackQuery,
    widget: Button,
    sub_manager: SubManager,
    plan_service: FromDishka[PlanService],
) -> None:
    await sub_manager.load_data()
    plan_id = int(sub_manager.item_id)
    await plan_service.delete(plan_id)
    # TODO: Add action confirmation


@inject
async def on_name_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notification_service: FromDishka[NotificationService],
    plan_service: FromDishka[PlanService],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]

    logger.debug(f"{format_log_user(user)} Attempted to set plan name")

    if message.text is None:
        logger.warning(f"{format_log_user(user)} Provided empty plan name input")
        await notification_service.notify_user(user=user, text_key="ntf-plan-wrong-name")
        return

    if await plan_service.get_by_name(name=message.text):
        logger.warning(
            f"{format_log_user(user)} Tried to set plan name to "
            f"'{message.text}', which already exists"
        )
        await notification_service.notify_user(user=user, text_key="ntf-plan-wrong-name")
        return

    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanDto)

    if not plan:
        logger.error(f"{format_log_user(user)} Failed to load PlanDto for name input")
        return

    plan.name = message.text
    adapter.save(plan)

    logger.info(f"{format_log_user(user)} Successfully set plan name to '{plan.name}'")
    await dialog_manager.switch_to(state=RemnashopPlans.PLAN)


async def on_type_selected(
    callback: CallbackQuery,
    widget: Select[PlanType],
    dialog_manager: DialogManager,
    selected_type: PlanType,
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanDto)

    logger.debug(f"{format_log_user(user)} Selected plan type '{selected_type}'")

    if not plan:
        logger.error(f"{format_log_user(user)} Failed to load PlanDto for type selection")
        return

    plan.type = selected_type
    adapter.save(plan)

    logger.info(f"{format_log_user(user)} Successfully updated plan type to '{plan.type.name}'")
    await dialog_manager.switch_to(state=RemnashopPlans.PLAN)


async def on_availability_selected(
    callback: CallbackQuery,
    widget: Select[PlanAvailability],
    dialog_manager: DialogManager,
    selected_availability: PlanAvailability,
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanDto)

    logger.debug(f"{format_log_user(user)} Selected plan availability '{selected_availability}'")

    if not plan:
        logger.error(f"{format_log_user(user)} Failed to load PlanDto for availability selection")
        return

    plan.availability = selected_availability
    adapter.save(plan)

    logger.info(
        f"{format_log_user(user)} Successfully updated plan availability to '{plan.availability}'"
    )
    await dialog_manager.switch_to(state=RemnashopPlans.PLAN)


async def on_active_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanDto)

    logger.debug(f"{format_log_user(user)} Attempted to toggle plan active status")

    if not plan:
        logger.error(f"{format_log_user(user)} Failed to load PlanDto for active toggle")
        return

    plan.is_active = not plan.is_active
    adapter.save(plan)
    logger.info(
        f"{format_log_user(user)} Successfully toggled plan active status to '{plan.is_active}'"
    )


@inject
async def on_traffic_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notification_service: FromDishka[NotificationService],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]

    logger.debug(f"{format_log_user(user)} Attempted to set plan traffic limit")

    if message.text is None or not (message.text.isdigit() and int(message.text) > 0):
        logger.warning(
            f"{format_log_user(user)} Provided invalid traffic limit input: '{message.text}'"
        )
        await notification_service.notify_user(user=user, text_key="ntf-plan-wrong-number")
        return

    number = int(message.text)
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanDto)

    if not plan:
        logger.error(f"{format_log_user(user)} Failed to load PlanDto for traffic input")
        return

    plan.traffic_limit = number
    adapter.save(plan)

    logger.info(
        f"{format_log_user(user)} Successfully set plan traffic limit to '{plan.traffic_limit}'"
    )
    await dialog_manager.switch_to(state=RemnashopPlans.PLAN)


@inject
async def on_devices_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notification_service: FromDishka[NotificationService],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]

    logger.debug(f"{format_log_user(user)} Attempted to set plan device limit")

    if message.text is None or not (message.text.isdigit() and int(message.text) > 0):
        logger.warning(
            f"{format_log_user(user)} Provided invalid device limit input: '{message.text}'"
        )
        await notification_service.notify_user(user=user, text_key="ntf-plan-wrong-number")
        return

    number = int(message.text)
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanDto)

    if not plan:
        logger.error(f"{format_log_user(user)} Failed to load PlanDto for devices input")
        return

    plan.device_limit = number
    adapter.save(plan)

    logger.info(
        f"{format_log_user(user)} Successfully set plan device limit to '{plan.device_limit}'"
    )
    await dialog_manager.switch_to(state=RemnashopPlans.PLAN)


async def on_duration_selected(
    callback: CallbackQuery,
    widget: Button,
    sub_manager: SubManager,
) -> None:
    user: UserDto = sub_manager.middleware_data[USER_KEY]
    sub_manager.dialog_data["duration_selected"] = int(sub_manager.item_id)
    logger.debug(f"{format_log_user(user)} Selected duration '{sub_manager.item_id}' days")
    await sub_manager.switch_to(state=RemnashopPlans.PRICES)


async def on_duration_removed(
    callback: CallbackQuery,
    widget: Button,
    sub_manager: SubManager,
) -> None:
    await sub_manager.load_data()
    user: UserDto = sub_manager.middleware_data[USER_KEY]

    logger.debug(f"{format_log_user(user)} Attempted to remove duration")

    adapter = DialogDataAdapter(sub_manager.manager)
    plan = adapter.load(PlanDto)

    if not plan:
        logger.error(f"{format_log_user(user)} Failed to load PlanDto for duration removal")
        return

    duration_to_remove = int(sub_manager.item_id)
    new_durations = [d for d in plan.durations if d.days != duration_to_remove]
    plan.durations = new_durations
    adapter.save(plan)
    logger.info(
        f"{format_log_user(user)} Successfully removed duration "
        f"'{duration_to_remove}' days from plan"
    )


@inject
async def on_duration_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notification_service: FromDishka[NotificationService],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]

    logger.debug(f"{format_log_user(user)} Attempted to add new plan duration")

    if message.text is None or not (message.text.isdigit() and int(message.text) > 0):
        logger.warning(f"{format_log_user(user)} Provided invalid duration input: '{message.text}'")
        await notification_service.notify_user(user=user, text_key="ntf-plan-wrong-number")
        return

    number = int(message.text)
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanDto)

    if not plan:
        logger.error(f"{format_log_user(user)} Failed to load PlanDto for duration input")
        return

    plan.durations.append(
        PlanDurationDto(
            days=number,
            prices=[
                PlanPriceDto(
                    currency=currency,
                    price=100,
                )
                for currency in Currency
            ],
        )
    )
    adapter.save(plan)

    logger.info(f"{format_log_user(user)} New duration '{number}' days added to plan")
    await dialog_manager.switch_to(state=RemnashopPlans.DURATIONS)


async def on_currency_selected(
    callback: CallbackQuery,
    widget: Select[Currency],
    dialog_manager: DialogManager,
    currency_selected: Currency,
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    logger.debug(f"{format_log_user(user)} Selected currency '{currency_selected}'")
    dialog_manager.dialog_data["currency_selected"] = currency_selected.value
    await dialog_manager.switch_to(state=RemnashopPlans.PRICE)


@inject
async def on_price_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    notification_service: FromDishka[NotificationService],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]

    logger.debug(f"{format_log_user(user)} Attempted to set plan price")

    if message.text is None:
        logger.warning(f"{format_log_user(user)} Provided empty price input")
        await notification_service.notify_user(user=user, text_key="ntf-plan-wrong-number")
        return

    try:
        new_price = Decimal(message.text)
        if new_price <= 0:
            raise InvalidOperation
    except InvalidOperation:
        logger.warning(f"{format_log_user(user)} Provided invalid price input: '{message.text}'")
        await notification_service.notify_user(user=user, text_key="ntf-plan-wrong-number")
        return

    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanDto)

    if not plan:
        logger.error(f"{format_log_user(user)} Failed to load PlanDto for price input")
        return

    duration_selected = dialog_manager.dialog_data.get("duration_selected")
    currency_selected = dialog_manager.dialog_data.get("currency_selected")

    # TODO: Check what is the minimum price allowed for payment providers
    if currency_selected == Currency.XTR:
        new_price = new_price.quantize(Decimal(1), rounding=ROUND_UP)
        logger.debug(f"{format_log_user(user)} Quantizing XTR price to integer: '{new_price}'")

    for duration in plan.durations:
        if duration.days == duration_selected:
            for price in duration.prices:
                if price.currency == currency_selected:
                    price.price = new_price
                    logger.debug(
                        f"{format_log_user(user)} Updated price for duration '{duration.days}' "
                        f"and currency '{currency_selected}' to '{new_price}'"
                    )
                    break
            break

    adapter.save(plan)
    await dialog_manager.switch_to(state=RemnashopPlans.PRICES)


@inject
async def on_allowed_user_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    user_service: FromDishka[UserService],
    notification_service: FromDishka[NotificationService],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]

    logger.debug(f"{format_log_user(user)} Attempted to set allowed id for plan")

    if message.text is None or not message.text.isdigit():
        logger.warning(f"{format_log_user(user)} Provided non-numeric user ID")
        await notification_service.notify_user(user=user, text_key="ntf-plan-wrong-allowed-id")
        return

    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanDto)
    allowed_user = await user_service.get(telegram_id=int(message.text))

    if not allowed_user:
        logger.warning(f"{format_log_user(user)} No user found with Telegram ID '{message.text}'")
        await notification_service.notify_user(user=user, text_key="ntf-plan-no-user-found")
        return  # TODO: Allow adding non-existent users to the list?

    if plan.allowed_user_ids is None:
        plan.allowed_user_ids = []

    if allowed_user.telegram_id in plan.allowed_user_ids:
        logger.warning(
            f"{format_log_user(user)} User '{allowed_user.telegram_id}' is already allowed for plan"
        )
        await notification_service.notify_user(user=user, text_key="ntf-plan-user-already-allowed")
        return

    plan.allowed_user_ids.append(allowed_user.telegram_id)
    adapter.save(plan)


@inject
async def on_allowed_user_removed(
    callback: CallbackQuery,
    widget: Button,
    sub_manager: SubManager,
    plan_service: FromDishka[PlanService],
) -> None:
    await sub_manager.load_data()
    user_id = int(sub_manager.item_id)

    adapter = DialogDataAdapter(sub_manager.manager)
    plan = adapter.load(PlanDto)

    plan.allowed_user_ids.remove(user_id)
    adapter.save(plan)


@inject
async def on_confirm_plan(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    notification_service: FromDishka[NotificationService],
    plan_service: FromDishka[PlanService],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]

    logger.debug(f"{format_log_user(user)} Attempted to confirm plan")

    adapter = DialogDataAdapter(dialog_manager)
    plan_data = adapter.load(PlanDto)

    if not plan_data:
        logger.error(f"{format_log_user(user)} Failed to load PlanDto for plan confirmation")
        await notification_service.notify_user(user=user, text_key="ntf-plan-save-error")
        return

    if plan_data.type == PlanType.DEVICES:
        plan_data.traffic_limit = None
    elif plan_data.type == PlanType.TRAFFIC:
        plan_data.device_limit = None
    elif plan_data.type == PlanType.BOTH:
        pass
    else:  # PlanType.UNLIMITED
        plan_data.traffic_limit = None
        plan_data.device_limit = None

    if plan_data.availability != PlanAvailability.ALLOWED:
        plan_data.allowed_user_ids = None

    if plan_data.allowed_user_ids is None:
        plan_data.allowed_user_ids = []

    if plan_data.id:
        logger.info(f"{format_log_user(user)} Updating existing plan with ID '{plan_data.id}'")
        await plan_service.update(plan=plan_data)
        logger.info(f"{format_log_user(user)} Plan '{plan_data.name}' updated successfully")
        await notification_service.notify_user(user=user, text_key="ntf-plan-updated-success")
    else:
        existing_plan: PlanDto = await plan_service.get_by_name(name=plan_data.name)
        if existing_plan:
            logger.warning(
                f"{format_log_user(user)} Plan with name '{plan_data.name}' "
                f"already exists during creation. Aborting plan creation"
            )
            await notification_service.notify_user(
                user=user,
                text_key="ntf-plan-name-already-exists",
            )
            return

        logger.info(f"{format_log_user(user)} Creating new plan with name '{plan_data.name}'")
        plan = await plan_service.create(plan_data)
        logger.info(f"{format_log_user(user)} Plan '{plan.name}' created successfully")
        await notification_service.notify_user(user=user, text_key="ntf-plan-created-success")

    await dialog_manager.reset_stack()
    await dialog_manager.start(state=RemnashopPlans.MAIN)
