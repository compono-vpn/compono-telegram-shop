from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode, StartMode, SubManager
from aiogram_dialog.widgets.kbd import Button
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from fluentogram import TranslatorRunner
from httpx import HTTPStatusError
from loguru import logger

from src.bot.keyboards import CALLBACK_CHANNEL_CONFIRM, CALLBACK_RULES_ACCEPT
from src.bot.states import MainMenu
from src.core.constants import USER_KEY
from src.core.enums import MediaType
from src.core.i18n.translator import get_translated_kwargs
from src.core.utils.formatters import format_user_log as log
from src.core.utils.message_payload import MessagePayload
from src.infrastructure.billing.client import BillingClient
from src.infrastructure.database.models.dto import UserDto
from src.services.notification import NotificationService
from src.services.referral import ReferralService
from src.services.remnawave import RemnawaveService
from src.services.settings import SettingsService

router = Router(name=__name__)


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


@inject
@router.message(CommandStart(ignore_case=True))
async def on_start_command(
    message: Message,
    user: UserDto,
    dialog_manager: DialogManager,
    billing_client: FromDishka[BillingClient],
) -> None:
    # Handle web deep link: /start web_<short_id>
    if message.text and len(message.text.split()) > 1:
        param = message.text.split()[1]
        if param.startswith("web_"):
            await _handle_web_link(message, user, param, billing_client)

    await on_start_dialog(user, dialog_manager)


async def _handle_web_link(
    message: Message,
    user: UserDto,
    param: str,
    billing_client: BillingClient,
) -> None:
    short_id = param[len("web_"):]

    try:
        result = await billing_client.claim_web_order(user.telegram_id, short_id)
    except HTTPStatusError as e:
        status = e.response.status_code
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except Exception:
            pass

        if status == 404:
            logger.warning(f"{log(user)} Web link '{param}' — order not found or not completed")
            await message.answer(
                "Ссылка недействительна или оплата ещё не завершена. "
                "Если вы только что оплатили — подождите минуту и попробуйте снова."
            )
        elif status == 409 and "already claimed by you" in detail:
            logger.info(f"{log(user)} Re-opened already claimed web link '{param}'")
            await message.answer("Эта подписка уже привязана к вашему аккаунту.")
        elif status == 409:
            logger.warning(f"{log(user)} Web link '{param}' conflict: {detail}")
            await message.answer("Эта ссылка уже была использована другим пользователем.")
        elif status == 403:
            logger.warning(f"{log(user)} Trial already used, rejecting web link '{param}'")
            await message.answer(
                "Пробный период можно активировать только один раз. "
                "Оформите подписку для продолжения использования."
            )
        else:
            logger.error(f"{log(user)} Web link '{param}' billing error: {status} {detail}")
            await message.answer("Произошла ошибка при активации. Напишите в поддержку: support@componovpn.com")
        return
    except Exception as e:
        logger.error(f"{log(user)} Web link '{param}' unexpected error: {e}")
        await message.answer("Произошла ошибка при активации. Напишите в поддержку: support@componovpn.com")
        return

    kind = "trial" if result.get("is_trial") else "purchase"
    logger.info(f"{log(user)} Linked web {kind} subscription via billing service (short_id={short_id})")

    # BILLING_MIGRATION: old code below — _handle_web_link previously did:
    # - Direct DB lookup of web_orders via UnitOfWork
    # - Direct Remnawave API calls (get user, update user telegram_id)
    # - Direct subscription creation via SubscriptionService
    # All of this is now handled by billing_client.claim_web_order()


@inject
@router.message(F.text.contains("/api/sub/"))
async def on_subscription_url_paste(
    message: Message,
    user: UserDto,
    billing_client: FromDishka[BillingClient],
) -> None:
    """Handle when user pastes a subscription URL to link their web purchase."""
    import re  # noqa: PLC0415

    text = (message.text or "").strip()

    # Extract the token (last path segment of the subscription URL)
    match = re.search(r"/api/sub/([A-Za-z0-9_-]+)", text)
    if not match:
        await message.answer("Не удалось распознать ссылку подписки.")
        return

    token = match.group(1)

    try:
        await billing_client.link_subscription_url(user.telegram_id, token)
    except HTTPStatusError as e:
        status = e.response.status_code
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except Exception:
            pass

        if status == 404:
            logger.warning(f"{log(user)} Pasted sub URL with token '{token}' — not found")
            await message.answer("Подписка не найдена. Проверьте ссылку и попробуйте снова.")
        elif status == 409 and "already linked to you" in detail:
            await message.answer("Эта подписка уже привязана к вашему аккаунту.")
        elif status == 409 and "another" in detail:
            await message.answer("Эта подписка уже привязана к другому аккаунту Telegram.")
        elif status == 409:
            await message.answer(
                "У вас уже есть активная подписка. "
                "Для привязки другой подписки обратитесь в поддержку."
            )
        else:
            logger.error(f"{log(user)} Link sub URL error: {status} {detail}")
            await message.answer("Произошла ошибка. Попробуйте позже.")
        return
    except Exception as e:
        logger.error(f"{log(user)} Link sub URL unexpected error: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")
        return

    logger.info(f"{log(user)} Linked subscription via pasted URL, token='{token}'")
    await message.answer(
        "Подписка успешно привязана к вашему аккаунту! "
        "Теперь вы можете управлять ей через бота."
    )

    # BILLING_MIGRATION: old code below — on_subscription_url_paste previously did:
    # - Direct Remnawave API calls (get_user_by_short_uuid, update_user)
    # - Direct DB lookup/update of web_orders via UnitOfWork
    # - Direct subscription creation via SubscriptionService
    # All of this is now handled by billing_client.link_subscription_url()


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
    billing_client: FromDishka[BillingClient],
    notification_service: FromDishka[NotificationService],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]

    # Look up the trial plan via billing service
    trial_plan = await billing_client.get_trial_plan()
    if not trial_plan:
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-trial-unavailable"),
        )
        raise ValueError("Trial plan not exist")

    plan_id = trial_plan["id"]

    try:
        await billing_client.create_trial(user.telegram_id, plan_id)
    except HTTPStatusError as e:
        logger.error(f"{log(user)} Failed to create trial via billing: {e.response.status_code} {e.response.text}")
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-trial-unavailable"),
        )
        return
    except Exception as e:
        logger.error(f"{log(user)} Unexpected error creating trial: {e}")
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-trial-unavailable"),
        )
        return

    logger.info(f"{log(user)} Trial created via billing service (plan_id={plan_id})")

    # BILLING_MIGRATION: old code below — on_get_trial previously did:
    # - plan_service.get_trial_plan() — direct DB lookup
    # - trial_subscription_task.kiq(user, trial, False) — taskiq task that
    #   created remnawave user + local subscription
    # Now handled by billing_client.get_trial_plan() + billing_client.create_trial()


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
    settings_service: FromDishka[SettingsService],
) -> None:
    if await settings_service.is_referral_enable():
        await dialog_manager.switch_to(state=MainMenu.INVITE)
    else:
        return
