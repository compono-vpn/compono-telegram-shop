from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode, StartMode, SubManager
from aiogram_dialog.widgets.kbd import Button
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from fluentogram import TranslatorRunner
from loguru import logger

from src.bot.keyboards import CALLBACK_CHANNEL_CONFIRM, CALLBACK_RULES_ACCEPT, get_channel_keyboard
from src.bot.states import MainMenu, Subscription
from src.core.constants import USER_KEY
from src.core.enums import MediaType
from src.core.i18n.translator import get_translated_kwargs
from src.core.utils.calls import generate_calls_qr, render_amneziawg_conf
from src.core.utils.formatters import format_user_log as log
from src.core.utils.message_payload import MessagePayload
from src.infrastructure.billing import BillingClient, billing_calls_bundle_to_dto
from src.infrastructure.billing.client import BillingClientError, CallsNotEntitledError
from src.models.dto import UserDto
from src.services.channel_incentive import ChannelIncentiveService
from src.services.experiment import TRIAL_EXPERIMENT_KEY, ExperimentService
from src.services.notification import NotificationService
from src.services.referral import ReferralService
from src.services.remnawave import RemnawaveService

router = Router(name=__name__)


def _record_trial_activation(experiment_service: ExperimentService, user: UserDto) -> None:
    try:
        experiment_service.record_conversion(
            TRIAL_EXPERIMENT_KEY,
            user.telegram_id,
            "trial_activated",
            created_at=user.created_at,
        )
        return
    except TypeError:
        experiment_service.record_conversion(
            TRIAL_EXPERIMENT_KEY,
            user.telegram_id,
            "trial_activated",
        )


async def on_start_dialog(
    user: UserDto,
    dialog_manager: DialogManager,
) -> None:
    logger.info(f"{log(user)} Started dialog")
    await dialog_manager.start(
        state=MainMenu.MAIN,
        mode=StartMode.RESET_STACK,
        show_mode=ShowMode.DELETE_AND_SEND,
    )


async def _maybe_prompt_channel_incentive(
    user: UserDto,
    channel_incentive_service: ChannelIncentiveService,
    notification_service: NotificationService,
) -> None:
    channel_url = channel_incentive_service.channel_url
    if not channel_url:
        return
    if not await channel_incentive_service.should_prompt(user):
        return
    await notification_service.notify_user(
        user=user,
        payload=MessagePayload(
            i18n_key="ntf-channel-incentive",
            i18n_kwargs={"percent": channel_incentive_service.discount_percent},
            reply_markup=get_channel_keyboard(channel_url),
            auto_delete_after=None,
            add_close_button=False,
        ),
    )


@inject
@router.message(CommandStart(ignore_case=True))
async def on_start_command(
    message: Message,
    user: UserDto,
    dialog_manager: DialogManager,
    i18n: FromDishka[TranslatorRunner],
    channel_incentive_service: FromDishka[ChannelIncentiveService],
    notification_service: FromDishka[NotificationService],
) -> None:
    # Web purchases are managed at the web portal — this bot is TG-native only.
    # If the user arrives via a legacy /start web_<token> deep link, send a
    # neutral redirect message instead of attempting to claim or link any
    # subscription on the billing side.
    if message.text and len(message.text.split()) > 1:
        param = message.text.split()[1]
        if param.startswith("web_"):
            logger.info(
                f"{log(user)} Received legacy web deep link '{param}' — "
                f"sending neutral redirect; web claim flow is removed"
            )
            await message.answer(i18n.get("msg-web-purchase-redirect"))

    await on_start_dialog(user, dialog_manager)
    await _maybe_prompt_channel_incentive(
        user=user,
        channel_incentive_service=channel_incentive_service,
        notification_service=notification_service,
    )


@router.callback_query(F.data == CALLBACK_RULES_ACCEPT)
async def on_rules_accept(
    callback: CallbackQuery,
    user: UserDto,
    dialog_manager: DialogManager,
) -> None:
    logger.info(f"{log(user)} Accepted rules")
    await on_start_dialog(user, dialog_manager)


@router.callback_query(F.data == CALLBACK_CHANNEL_CONFIRM)
async def on_channel_confirm(
    callback: CallbackQuery,
    user: UserDto,
    dialog_manager: DialogManager,
) -> None:
    logger.info(f"{log(user)} Cofirmed join channel")
    await on_start_dialog(user, dialog_manager)


@inject
async def on_get_trial(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    billing: FromDishka[BillingClient],
    notification_service: FromDishka[NotificationService],
    experiment_service: FromDishka[ExperimentService],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]

    if not await experiment_service.is_trial_offer_enabled(user):
        logger.info(f"{log(user)} Trial suppressed by experiment variant")
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-trial-unavailable"),
        )
        return

    billing_plan = await billing.get_trial_plan()

    if not billing_plan:
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-trial-unavailable"),
        )
        raise ValueError("Trial plan not exist")

    try:
        await billing.create_trial_subscription(user.telegram_id, billing_plan.ID)
        _record_trial_activation(experiment_service, user)
        await callback.answer("Пробный период активирован")
        await dialog_manager.start(
            state=Subscription.TRIAL,
            mode=StartMode.RESET_STACK,
            show_mode=ShowMode.EDIT,
        )
    except BillingClientError as e:
        if e.status_code == 409 or "already used trial" in e.message:
            logger.warning(f"{log(user)} Trial already used: {e}")
            await notification_service.notify_user(
                user=user,
                payload=MessagePayload(i18n_key="ntf-trial-already-used"),
            )
            return
        raise


@inject
async def on_device_delete(
    callback: CallbackQuery,
    widget: Button,
    sub_manager: SubManager,
    remnawave_service: FromDishka[RemnawaveService],
) -> None:
    await sub_manager.load_data()
    selected_short_hwid = sub_manager.item_id
    user: UserDto = sub_manager.middleware_data[USER_KEY]
    hwid_map = sub_manager.dialog_data.get("hwid_map")

    if not hwid_map:
        raise ValueError(f"Selected '{selected_short_hwid}' HWID, but 'hwid_map' is missing")

    full_hwid = next((d["hwid"] for d in hwid_map if d["short_hwid"] == selected_short_hwid), None)

    if not full_hwid:
        raise ValueError(f"Full HWID not found for '{selected_short_hwid}'")

    if not (user.current_subscription and user.current_subscription.device_limit):
        raise ValueError("User has no active subscription or device limit unlimited")

    devices = await remnawave_service.delete_device(user=user, hwid=full_hwid)
    logger.info(f"{log(user)} Deleted device '{full_hwid}'")

    if devices:
        return

    await sub_manager.switch_to(state=MainMenu.MAIN)


@inject
async def show_reason(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    i18n: FromDishka[TranslatorRunner],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    subscription = user.current_subscription

    if subscription:
        kwargs = {
            "status": subscription.get_status,
            "is_trial": subscription.is_trial,
            "traffic_strategy": subscription.traffic_limit_strategy,
            "reset_time": subscription.get_expire_time,
        }
    else:
        kwargs = {"status": False}

    await callback.answer(
        text=i18n.get("ntf-connect-not-available", **get_translated_kwargs(i18n, kwargs)),
        show_alert=True,
    )


@inject
async def on_show_qr(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    referral_service: FromDishka[ReferralService],
    notification_service: FromDishka[NotificationService],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]

    ref_link = await referral_service.get_ref_link(user.referral_code)
    ref_qr = referral_service.get_ref_qr(ref_link)

    await notification_service.notify_user(
        user=user,
        payload=MessagePayload.not_deleted(
            i18n_key="",
            media=ref_qr,
            media_type=MediaType.PHOTO,
        ),
    )


@inject
async def on_calls_beta(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    billing: FromDishka[BillingClient],
    notification_service: FromDishka[NotificationService],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]

    try:
        billing_bundle = await billing.provision_calls(user.telegram_id)
    except CallsNotEntitledError:
        logger.info(f"{log(user)} Calls beta provisioning rejected: not entitled")
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-calls-beta-not-entitled"),
        )
        return

    bundle = billing_calls_bundle_to_dto(billing_bundle)
    conf = render_amneziawg_conf(bundle.amneziawg)
    hysteria2_uri = bundle.hysteria2.uri.get_secret_value()

    await notification_service.notify_user(
        user=user,
        payload=MessagePayload.not_deleted(
            i18n_key="msg-calls-beta",
            media=BufferedInputFile(conf.encode(), filename="compono-calls.conf"),
            media_type=MediaType.DOCUMENT,
        ),
    )
    await notification_service.notify_user(
        user=user,
        payload=MessagePayload.not_deleted(
            i18n_key="",
            media=generate_calls_qr(conf, "compono-calls-amneziawg.png"),
            media_type=MediaType.PHOTO,
        ),
    )
    await notification_service.notify_user(
        user=user,
        payload=MessagePayload.not_deleted(
            i18n_key="",
            media=generate_calls_qr(hysteria2_uri, "compono-calls-hysteria2.png"),
            media_type=MediaType.PHOTO,
        ),
    )
    logger.info(f"{log(user)} Provisioned Calls beta bundle")


@inject
async def on_withdraw_points(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    i18n: FromDishka[TranslatorRunner],
) -> None:
    await callback.answer(
        text=i18n.get("ntf-invite-withdraw-points-error"),
        show_alert=True,
    )


@inject
async def on_invite(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    billing: FromDishka[BillingClient],
) -> None:
    settings = await billing.get_settings()
    referral_settings = settings.Referral or {}
    is_referral_enable = bool(referral_settings.get("enable", False))
    if is_referral_enable:
        await dialog_manager.switch_to(state=MainMenu.INVITE)
    else:
        return
