import traceback
from typing import Optional, TypedDict, cast

from aiogram.types import CallbackQuery, Message
from aiogram.utils.formatting import Text
from aiogram_dialog import DialogManager, ShowMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from httpx import HTTPStatusError
from loguru import logger

from src.bot.keyboards import get_user_keyboard
from src.bot.states import Subscription
from src.core.constants import PURCHASE_PREFIX, USER_KEY
from src.core.enums import PaymentGatewayType, PurchaseType, SystemNotificationType
from src.core.utils.adapter import DialogDataAdapter
from src.core.utils.formatters import format_user_log as log
from src.core.utils.message_payload import MessagePayload
from src.infrastructure.billing.client import BillingClient
from src.infrastructure.database.models.dto import PlanDto, PlanSnapshotDto, PriceDetailsDto, UserDto
from src.services.notification import NotificationService
from src.services.subscription import SubscriptionService

PAYMENT_CACHE_KEY = "payment_cache"
CURRENT_DURATION_KEY = "selected_duration"
CURRENT_METHOD_KEY = "selected_payment_method"


class CachedPaymentData(TypedDict):
    payment_id: str
    payment_url: Optional[str]
    final_pricing: str


def _get_cache_key(duration: int, gateway_type: PaymentGatewayType) -> str:
    return f"{duration}:{gateway_type.value}"


def _load_payment_data(dialog_manager: DialogManager) -> dict[str, CachedPaymentData]:
    if PAYMENT_CACHE_KEY not in dialog_manager.dialog_data:
        dialog_manager.dialog_data[PAYMENT_CACHE_KEY] = {}
    return cast(dict[str, CachedPaymentData], dialog_manager.dialog_data[PAYMENT_CACHE_KEY])


def _save_payment_data(dialog_manager: DialogManager, payment_data: CachedPaymentData) -> None:
    dialog_manager.dialog_data["payment_id"] = payment_data["payment_id"]
    dialog_manager.dialog_data["payment_url"] = payment_data["payment_url"]
    dialog_manager.dialog_data["final_pricing"] = payment_data["final_pricing"]


async def _create_payment_and_get_data(
    dialog_manager: DialogManager,
    plan: PlanDto,
    duration_days: int,
    gateway_type: PaymentGatewayType,
    billing_client: BillingClient,
    notification_service: NotificationService,
) -> Optional[CachedPaymentData]:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    duration = plan.get_duration(duration_days)
    purchase_type: PurchaseType = dialog_manager.dialog_data["purchase_type"]

    if not duration:
        logger.error(f"{log(user)} Failed to find duration for payment creation")
        return None

    try:
        # Determine currency from gateway
        gateway_data = await billing_client.get_gateway_by_type(gateway_type.value)
        currency = gateway_data.get("currency", "XTR") if gateway_data else "XTR"

        result = await billing_client.create_payment(
            telegram_id=user.telegram_id,
            plan_id=plan.id,
            duration_days=duration_days,
            currency=currency,
            gateway_type=gateway_type.value,
            purchase_type=purchase_type.value,
        )

        pricing_data = result.get("pricing", {})
        pricing = PriceDetailsDto(
            final_amount=pricing_data.get("final_amount", 0),
            original_amount=pricing_data.get("original_amount", 0),
            discount_percent=pricing_data.get("discount_percent", 0),
        )

        return CachedPaymentData(
            payment_id=str(result.get("id", result.get("payment_id", ""))),
            payment_url=result.get("url"),
            final_pricing=pricing.model_dump_json(),
        )

    except Exception as exception:
        logger.error(f"{log(user)} Failed to create payment: {exception}")
        traceback_str = traceback.format_exc()
        error_type_name = type(exception).__name__
        error_message = Text(str(exception)[:512])

        await notification_service.error_notify(
            error_id=user.telegram_id,
            traceback_str=traceback_str,
            payload=MessagePayload.not_deleted(
                i18n_key="ntf-event-error",
                i18n_kwargs={
                    "user": True,
                    "user_id": str(user.telegram_id),
                    "user_name": user.name,
                    "username": user.username or False,
                    "error": f"{error_type_name}: Failed to create payment "
                    + f"check due to error: {error_message.as_html()}",
                },
                reply_markup=get_user_keyboard(user.telegram_id),
            ),
        )

        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-subscription-payment-creation-failed"),
        )
        return None


@inject
async def on_purchase_type_select(
    purchase_type: PurchaseType,
    dialog_manager: DialogManager,
    billing_client: FromDishka[BillingClient],
    notification_service: FromDishka[NotificationService],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    plans_data = await billing_client.get_available_plans(user.telegram_id)
    gateways = await billing_client.filter_active_gateways()
    dialog_manager.dialog_data["purchase_type"] = purchase_type
    dialog_manager.dialog_data.pop(CURRENT_DURATION_KEY, None)

    if not plans_data:
        logger.warning(f"{log(user)} No available subscription plans")
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-subscription-plans-not-available"),
        )
        return

    if not gateways:
        logger.warning(f"{log(user)} No active payment gateways")
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-subscription-gateways-not-available"),
        )
        return

    plans = [PlanDto.model_validate(p) for p in plans_data]
    adapter = DialogDataAdapter(dialog_manager)

    if purchase_type == PurchaseType.RENEW:
        if user.current_subscription:
            matched_plan = SubscriptionService.find_matching_plan(
                plan_snapshot=user.current_subscription.plan,
                plans=plans,
            )
            logger.debug(f"Matched plan for renewal: '{matched_plan}'")

            if matched_plan:
                adapter.save(matched_plan)
                dialog_manager.dialog_data["only_single_plan"] = True
                await dialog_manager.switch_to(state=Subscription.DURATION)
                return
            else:
                logger.warning(f"{log(user)} Tried to renew, but no matching plan found")
                await notification_service.notify_user(
                    user=user,
                    payload=MessagePayload(i18n_key="ntf-subscription-renew-plan-unavailable"),
                )
                return

    if len(plans) == 1:
        logger.info(f"{log(user)} Auto-selected single plan '{plans[0].id}'")
        adapter.save(plans[0])
        dialog_manager.dialog_data["only_single_plan"] = True
        await dialog_manager.switch_to(state=Subscription.DURATION)
        return

    dialog_manager.dialog_data["only_single_plan"] = False
    await dialog_manager.switch_to(state=Subscription.PLANS)


@inject
async def on_subscription_plans(  # noqa: C901
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    billing_client: FromDishka[BillingClient],
    notification_service: FromDishka[NotificationService],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    logger.info(f"{log(user)} Opened subscription plans menu")

    plans_data = await billing_client.get_available_plans(user.telegram_id)
    gateways = await billing_client.filter_active_gateways()

    if not callback.data:
        raise ValueError("Callback data is empty")

    purchase_type = PurchaseType(callback.data.removeprefix(PURCHASE_PREFIX))
    dialog_manager.dialog_data["purchase_type"] = purchase_type

    dialog_manager.dialog_data.pop(CURRENT_DURATION_KEY, None)

    if not plans_data:
        logger.warning(f"{log(user)} No available subscription plans")
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-subscription-plans-not-available"),
        )
        return

    if not gateways:
        logger.warning(f"{log(user)} No active payment gateways")
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-subscription-gateways-not-available"),
        )
        return

    plans = [PlanDto.model_validate(p) for p in plans_data]
    adapter = DialogDataAdapter(dialog_manager)

    if purchase_type == PurchaseType.RENEW:
        if user.current_subscription:
            matched_plan = SubscriptionService.find_matching_plan(
                plan_snapshot=user.current_subscription.plan,
                plans=plans,
            )
            logger.debug(f"Matched plan for renewal: '{matched_plan}'")

            if matched_plan:
                adapter.save(matched_plan)
                dialog_manager.dialog_data["only_single_plan"] = True
                await dialog_manager.switch_to(state=Subscription.DURATION)
                return
            else:
                logger.warning(f"{log(user)} Tried to renew, but no matching plan found")
                await notification_service.notify_user(
                    user=user,
                    payload=MessagePayload(i18n_key="ntf-subscription-renew-plan-unavailable"),
                )
                return

    if len(plans) == 1:
        logger.info(f"{log(user)} Auto-selected single plan '{plans[0].id}'")
        adapter.save(plans[0])
        dialog_manager.dialog_data["only_single_plan"] = True

        if len(plans[0].durations) == 1:
            logger.info(f"{log(user)} Auto-selected duration '{plans[0].durations[0].days}'")
            dialog_manager.dialog_data["selected_duration"] = plans[0].durations[0].days
            dialog_manager.dialog_data["only_single_duration"] = True

            if len(gateways) == 1:
                gateway_type = PaymentGatewayType(gateways[0].get("type"))
                logger.info(f"{log(user)} Auto-selected payment method '{gateway_type}'")
                dialog_manager.dialog_data["selected_payment_method"] = gateway_type

                payment_data = await _create_payment_and_get_data(
                    dialog_manager=dialog_manager,
                    plan=plans[0],
                    duration_days=plans[0].durations[0].days,
                    gateway_type=gateway_type,
                    billing_client=billing_client,
                    notification_service=notification_service,
                )

                if payment_data:
                    _save_payment_data(dialog_manager, payment_data)

                await dialog_manager.switch_to(state=Subscription.CONFIRM)
                return

            await dialog_manager.switch_to(state=Subscription.PAYMENT_METHOD)
            return

        await dialog_manager.switch_to(state=Subscription.DURATION)
        return

    dialog_manager.dialog_data["only_single_plan"] = False
    dialog_manager.dialog_data["only_single_duration"] = False
    await dialog_manager.switch_to(state=Subscription.PLANS)


@inject
async def on_plan_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_plan: int,
    billing_client: FromDishka[BillingClient],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    plan_data = await billing_client.get_plan(plan_id=selected_plan)

    if not plan_data:
        raise ValueError(f"Selected plan '{selected_plan}' not found")

    plan = PlanDto.model_validate(plan_data)
    logger.info(f"{log(user)} Selected plan '{plan.id}'")
    adapter = DialogDataAdapter(dialog_manager)
    adapter.save(plan)

    dialog_manager.dialog_data.pop(PAYMENT_CACHE_KEY, None)
    dialog_manager.dialog_data.pop(CURRENT_DURATION_KEY, None)
    dialog_manager.dialog_data.pop(CURRENT_METHOD_KEY, None)

    if len(plan.durations) == 1:
        logger.info(f"{log(user)} Auto-selected single duration '{plan.durations[0].days}'")
        dialog_manager.dialog_data["only_single_duration"] = True
        await on_duration_select(callback, widget, dialog_manager, plan.durations[0].days)
        return

    await dialog_manager.switch_to(state=Subscription.DURATION)


@inject
async def on_duration_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_duration: int,
    billing_client: FromDishka[BillingClient],
    notification_service: FromDishka[NotificationService],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    logger.info(f"{log(user)} Selected subscription duration '{selected_duration}' days")
    dialog_manager.dialog_data[CURRENT_DURATION_KEY] = selected_duration

    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanDto)

    if not plan:
        raise ValueError("PlanDto not found in dialog data")

    gateways = await billing_client.filter_active_gateways()

    # Calculate price using billing service to check if free
    default_currency = await billing_client.get_default_currency()
    try:
        price_data = await billing_client.calculate_price(
            telegram_id=user.telegram_id,
            plan_id=plan.id,
            duration_days=selected_duration,
            currency=default_currency,
        )
        is_free = price_data.get("is_free", False)
    except HTTPStatusError:
        is_free = False

    dialog_manager.dialog_data["is_free"] = is_free

    if len(gateways) == 1 or is_free:
        selected_payment_method = PaymentGatewayType(gateways[0].get("type"))
        dialog_manager.dialog_data[CURRENT_METHOD_KEY] = selected_payment_method

        cache = _load_payment_data(dialog_manager)
        cache_key = _get_cache_key(selected_duration, selected_payment_method)

        if cache_key in cache:
            logger.info(f"{log(user)} Re-selected same duration and single gateway")
            _save_payment_data(dialog_manager, cache[cache_key])
            await dialog_manager.switch_to(state=Subscription.CONFIRM)
            return

        logger.info(f"{log(user)} Auto-selected single gateway '{selected_payment_method}'")

        payment_data = await _create_payment_and_get_data(
            dialog_manager=dialog_manager,
            plan=plan,
            duration_days=selected_duration,
            gateway_type=selected_payment_method,
            billing_client=billing_client,
            notification_service=notification_service,
        )

        if payment_data:
            cache[cache_key] = payment_data
            _save_payment_data(dialog_manager, payment_data)
            await dialog_manager.switch_to(state=Subscription.CONFIRM)
            return

    dialog_manager.dialog_data.pop(CURRENT_METHOD_KEY, None)
    await dialog_manager.switch_to(state=Subscription.PAYMENT_METHOD)


@inject
async def on_payment_method_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_payment_method: PaymentGatewayType,
    billing_client: FromDishka[BillingClient],
    notification_service: FromDishka[NotificationService],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    logger.info(f"{log(user)} Selected payment method '{selected_payment_method}'")

    selected_duration = dialog_manager.dialog_data[CURRENT_DURATION_KEY]
    dialog_manager.dialog_data[CURRENT_METHOD_KEY] = selected_payment_method
    cache = _load_payment_data(dialog_manager)
    cache_key = _get_cache_key(selected_duration, selected_payment_method)

    if cache_key in cache:
        logger.info(f"{log(user)} Re-selected same method and duration")
        _save_payment_data(dialog_manager, cache[cache_key])
        await dialog_manager.switch_to(state=Subscription.CONFIRM)
        return

    logger.info(f"{log(user)} New combination. Creating new payment")

    adapter = DialogDataAdapter(dialog_manager)
    plan = adapter.load(PlanDto)

    if not plan:
        raise ValueError("PlanDto not found in dialog data")

    payment_data = await _create_payment_and_get_data(
        dialog_manager=dialog_manager,
        plan=plan,
        duration_days=selected_duration,
        gateway_type=selected_payment_method,
        billing_client=billing_client,
        notification_service=notification_service,
    )

    if payment_data:
        cache[cache_key] = payment_data
        _save_payment_data(dialog_manager, payment_data)

    await dialog_manager.switch_to(state=Subscription.CONFIRM)


@inject
async def on_get_subscription(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    billing_client: FromDishka[BillingClient],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    payment_id = dialog_manager.dialog_data["payment_id"]
    logger.info(f"{log(user)} Getted free subscription '{payment_id}'")
    try:
        await billing_client.handle_free_payment(payment_id)
    except HTTPStatusError as e:
        logger.error(f"{log(user)} Failed to handle free payment: {e.response.status_code}")


@inject
async def on_promocode_input(
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

    code = message.text.strip()

    try:
        result = await billing_client.activate_promocode(code=code, telegram_id=user.telegram_id)
    except HTTPStatusError as e:
        logger.error(f"{log(user)} Failed to activate promocode: {e.response.status_code}")
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except Exception:
            pass
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-promocode-activation-failed"),
        )
        return

    notification_key = result.get("notification_key", "ntf-promocode-activated")
    notification_kwargs = result.get("notification_kwargs", {})

    await notification_service.notify_user(
        user=user,
        payload=MessagePayload(
            i18n_key=notification_key,
            i18n_kwargs=notification_kwargs,
        ),
    )

    if result.get("success"):
        # Send system notification to admins
        promocode_data = await billing_client.get_promocode_by_code(code.upper())
        if promocode_data:
            await notification_service.system_notify(
                payload=MessagePayload.not_deleted(
                    i18n_key="ntf-event-promocode-activated",
                    i18n_kwargs={
                        "user": True,
                        "user_id": str(user.telegram_id),
                        "user_name": user.name,
                        "username": user.username or False,
                        "code": promocode_data.get("code", ""),
                        "reward_type": str(promocode_data.get("reward_type", "")),
                        "reward": str(promocode_data.get("reward", "")),
                    },
                    reply_markup=get_user_keyboard(user.telegram_id),
                ),
                ntf_type=SystemNotificationType.PROMOCODE_ACTIVATED,
            )

        reward_type = result.get("reward_type")
        dialog_manager.dialog_data["promocode_reward_type"] = reward_type
        dialog_manager.dialog_data["promocode_code"] = code.upper()
        await dialog_manager.switch_to(state=Subscription.PROMOCODE_SUCCESS)
