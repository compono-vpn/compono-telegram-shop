import logging
from decimal import Decimal, InvalidOperation

from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode, SubManager
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select

from app.bot.models import AppContainer
from app.bot.states import RemnashopPlans
from app.core.adapter import DialogDataAdapter
from app.core.constants import APP_CONTAINER_KEY
from app.core.enums import Currency, PlanAvailability, PlanType
from app.db.models.dto import PlanDurationSchema, PlanPriceSchema, PlanSchema

logger = logging.getLogger(__name__)


async def on_name_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT

    if message.text is None:
        # TODO: Notify wrong name
        return

    # TODO: Check the availability of a plan with that name

    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanSchema)
    plan.name = message.text
    adapter.save(plan)

    await dialog_manager.switch_to(state=RemnashopPlans.PLAN)


async def on_type_selected(
    message: Message,
    widget: Select,
    dialog_manager: DialogManager,
    selected_type: PlanType,
) -> None:
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanSchema)
    plan.type = selected_type
    adapter.save(plan)
    await dialog_manager.switch_to(state=RemnashopPlans.PLAN)


async def on_availability_selected(
    message: Message,
    widget: Select,
    dialog_manager: DialogManager,
    selected_availability: PlanAvailability,
) -> None:
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanSchema)
    plan.availability = selected_availability
    adapter.save(plan)
    await dialog_manager.switch_to(state=RemnashopPlans.PLAN)


async def on_active_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanSchema)
    plan.is_active = not plan.is_active
    adapter.save(plan)


async def on_traffic_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT

    if message.text is None or not message.text.isdigit():
        # Notify wrong name
        return

    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanSchema)
    plan.traffic_limit = int(message.text)
    adapter.save(plan)

    await dialog_manager.switch_to(state=RemnashopPlans.PLAN)


async def on_devices_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT

    if message.text is None or not message.text.isdigit():
        # Notify wrong name
        return

    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanSchema)
    plan.device_limit = int(message.text)
    adapter.save(plan)

    await dialog_manager.switch_to(state=RemnashopPlans.PLAN)


async def on_duration_selected(
    message: Message,
    widget: Button,
    sub_manager: SubManager,
) -> None:
    sub_manager.dialog_data["duration_selected"] = int(sub_manager.item_id)
    await sub_manager.switch_to(state=RemnashopPlans.PRICES)


async def on_duration_removed(
    message: Message,
    widget: Button,
    sub_manager: SubManager,
) -> None:
    await sub_manager.load_data()

    adapter = DialogDataAdapter(sub_manager.manager)
    plan = adapter.load(PlanSchema)

    duration_to_remove = int(sub_manager.item_id)
    new_durations = [d for d in plan.durations if d.days != duration_to_remove]
    plan.durations = new_durations
    adapter.save(plan)


async def on_duration_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT

    if message.text is None or not message.text.isdigit():
        # Notify wrong name
        return

    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanSchema)
    plan.durations.append(
        PlanDurationSchema(
            days=int(message.text),
            prices=[
                PlanPriceSchema(
                    currency=currency,
                    price=100,
                )
                for currency in Currency
            ],
        )
    )
    adapter.save(plan)
    await dialog_manager.switch_to(state=RemnashopPlans.DURATIONS)


async def on_currency_selected(
    message: Message,
    widget: Select,
    dialog_manager: DialogManager,
    currency_selected: Currency,
) -> None:
    dialog_manager.dialog_data["currency_selected"] = currency_selected
    await dialog_manager.switch_to(state=RemnashopPlans.PRICE)


async def on_price_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT

    if message.text is None:
        # Notify wrong price
        return

    try:
        # TODO: XTR - only int (currency_selected)
        new_price = Decimal(message.text)
    except InvalidOperation:
        # Notify incorrect number
        return

    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanSchema)

    duration_selected = dialog_manager.dialog_data.get("duration_selected")
    currency_selected = dialog_manager.dialog_data.get("currency_selected")

    for duration in plan.durations:
        if duration.days == duration_selected:
            for price in duration.prices:
                if price.currency == currency_selected:
                    price.price = new_price
                    break
            break

    adapter.save(plan)
    await dialog_manager.switch_to(state=RemnashopPlans.PRICES)


async def on_confirm_plan(
    message: Message,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    adapter = DialogDataAdapter(dialog_manager)
    plan_data = adapter.load(PlanSchema)

    container: AppContainer = dialog_manager.middleware_data[APP_CONTAINER_KEY]

    if plan_data.type == PlanType.DEVICES:
        plan_data.traffic_limit = None
    elif plan_data.type == PlanType.TRAFFIC:
        plan_data.device_limit = None
    elif plan_data.type == PlanType.BOTH:
        pass
    else:
        plan_data.traffic_limit = None
        plan_data.device_limit = None

    if plan_data.availability != PlanAvailability.ALLOWED:
        plan_data.allowed_user_ids = None

    plan = await container.services.plan.create(plan_data)

    plan = await container.services.plan.get(plan.id)
    print(plan)

    await dialog_manager.reset_stack()
    await dialog_manager.start(state=RemnashopPlans.MAIN)
