from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode, StartMode, SubManager
from aiogram_dialog.widgets.kbd import Button
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from fluentogram import TranslatorRunner
from loguru import logger

from src.bot.keyboards import CALLBACK_CHANNEL_CONFIRM, CALLBACK_RULES_ACCEPT
from src.bot.states import MainMenu
from src.core.constants import USER_KEY
from src.core.enums import MediaType, SystemNotificationType
from src.core.i18n.translator import get_translated_kwargs
from src.core.utils.formatters import format_user_log as log
from src.core.utils.message_payload import MessagePayload
from src.infrastructure.billing import BillingClient, billing_plan_to_dto
from src.infrastructure.database.models.dto import PlanSnapshotDto, UserDto
from src.infrastructure.taskiq.tasks.subscriptions import trial_subscription_task
from src.services.notification import NotificationService
from src.services.referral import ReferralService
from src.services.remnawave import RemnawaveService
from src.services.subscription import SubscriptionService

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
    billing: FromDishka[BillingClient],
    remnawave_service: FromDishka[RemnawaveService],
    subscription_service: FromDishka[SubscriptionService],
    notification_service: FromDishka[NotificationService],
) -> None:
    # Handle web deep link: /start web_<short_id>
    if message.text and len(message.text.split()) > 1:
        param = message.text.split()[1]
        if param.startswith("web_"):
            await _handle_web_link(
                message, user, param, billing, remnawave_service,
                subscription_service, notification_service,
            )

    await on_start_dialog(user, dialog_manager)


async def _handle_web_link(
    message: Message,
    user: UserDto,
    param: str,
    billing: BillingClient,
    remnawave_service: RemnawaveService,
    subscription_service: SubscriptionService,
    notification_service: NotificationService,
) -> None:
    from remnapy.models import UpdateUserRequestDto  # noqa: PLC0415
    from remnapy.enums.users import TrafficLimitStrategy  # noqa: PLC0415
    from src.core.enums import PlanType  # noqa: PLC0415
    from src.core.utils.formatters import format_device_count  # noqa: PLC0415
    from src.infrastructure.database.models.dto import SubscriptionDto  # noqa: PLC0415

    short_id = param[len("web_"):]
    username = f"web_{short_id}"

    # 1. Validate the web order exists and is completed
    order = await billing.get_web_order_by_short_id(short_id)

    if not order or order.Status != "completed" or not order.SubscriptionURL:
        logger.warning(f"{log(user)} Web link '{param}' — order not found or not completed")
        await message.answer(
            "Ссылка недействительна или оплата ещё не завершена. "
            "Если вы только что оплатили — подождите минуту и попробуйте снова."
        )
        return

    is_trial = order.IsTrial

    # 2. Check if this order was already claimed by someone
    if order.ClaimedByTelegramID is not None:
        if order.ClaimedByTelegramID == user.telegram_id:
            logger.info(f"{log(user)} Re-opened already claimed web link '{param}'")
            await message.answer("Эта подписка уже привязана к вашему аккаунту.")
        else:
            logger.warning(f"{log(user)} Tried to claim web link '{param}' already claimed by {order.ClaimedByTelegramID}")
            await message.answer("Эта ссылка уже была использована другим пользователем.")
        return

    # 3. Trial-only checks (skip for full purchases)
    if is_trial:
        already_claimed = await billing.exists_claimed_web_order_by_telegram_id(user.telegram_id)

        if already_claimed:
            logger.warning(f"{log(user)} Already claimed a web trial, rejecting '{param}'")
            await message.answer(
                "Пробный период можно активировать только один раз. "
                "Оформите подписку для продолжения использования."
            )
            return

        has_trial = await subscription_service.has_used_trial(user.telegram_id)
        if has_trial:
            logger.warning(f"{log(user)} Already has trial subscription, rejecting web link '{param}'")
            await message.answer(
                "Пробный период можно активировать только один раз. "
                "Оформите подписку для продолжения использования."
            )
            return

    # 4. Find the Remnawave user created for this web order
    try:
        remna_user = await remnawave_service.remnawave.users.get_user_by_username(username)
    except Exception:
        logger.error(f"{log(user)} Remnawave user '{username}' not found")
        await message.answer("Произошла ошибка при активации. Напишите в поддержку: support@componovpn.com")
        return

    # 5. Claim the order — atomically set claimed_by_telegram_id
    await billing.update_web_order(
        order.PaymentID,
        claimed_by_telegram_id=user.telegram_id,
    )

    # 5b. Link Customer to this telegram user
    customer = None
    if order.CustomerID:
        customer = await billing.get_customer_by_id(order.CustomerID)
    if not customer and order.Email:
        customer = await billing.get_customer_by_email(order.Email)
    if customer:
        if not customer.TelegramID:
            await billing.update_customer(
                customer.ID, telegram_id=user.telegram_id
            )
        if not user.customer_id:
            await billing.update_user(user.telegram_id, {"customer_id": customer.ID})

    # 5c. Append email to user's linked_emails (deduplicated)
    if order.Email and order.Email not in (user.linked_emails or []):
        emails = list(user.linked_emails or [])
        emails.append(order.Email)
        user.linked_emails = emails
        await billing.update_user(user.telegram_id, {"linked_emails": emails})
        logger.info(f"{log(user)} Linked email '{order.Email}' (total: {len(emails)})")

    # 6. Update Remnawave user with telegram_id
    await remnawave_service.remnawave.users.update_user(
        UpdateUserRequestDto(
            uuid=remna_user.uuid,
            telegram_id=user.telegram_id,
        )
    )

    # 7. Build plan snapshot from web order
    from datetime import timedelta  # noqa: PLC0415
    from src.core.utils.time import datetime_now  # noqa: PLC0415

    total_days = order.PlanDurationDays

    if order.PlanSnapshot and not is_trial:
        snapshot = order.PlanSnapshot
        plan = PlanSnapshotDto(
            id=snapshot.get("id", -1),
            name=snapshot.get("name", "Web Purchase"),
            tag=remna_user.tag,
            type=PlanType(snapshot.get("type", "UNLIMITED")),
            traffic_limit=snapshot.get("traffic_limit", -1),
            device_limit=snapshot.get("device_limit", -1),
            duration=total_days,
            traffic_limit_strategy=remna_user.traffic_limit_strategy or TrafficLimitStrategy.NO_RESET,
            internal_squads=[s.uuid for s in remna_user.active_internal_squads],
            external_squad=remna_user.external_squad_uuid,
        )
        traffic_limit = snapshot.get("traffic_limit", -1)
        device_limit = snapshot.get("device_limit", -1)
    else:
        traffic_limit = 5
        device_limit = format_device_count(remna_user.hwid_device_limit)
        plan = PlanSnapshotDto(
            id=-1,
            name="Web Trial",
            tag=remna_user.tag,
            type=PlanType.UNLIMITED,
            traffic_limit=traffic_limit,
            device_limit=device_limit,
            duration=total_days,
            traffic_limit_strategy=remna_user.traffic_limit_strategy or TrafficLimitStrategy.NO_RESET,
            internal_squads=[s.uuid for s in remna_user.active_internal_squads],
            external_squad=remna_user.external_squad_uuid,
        )

    # 8. Merge into existing subscription or create new
    existing = await subscription_service.get_current(user.telegram_id)

    if existing and existing.expire_at:
        # Extend existing subscription — stack days on top of current expiry
        base_date = max(existing.expire_at, datetime_now())
        new_expire = base_date + timedelta(days=total_days)

        # Take the higher limits between existing and web order plan
        existing.traffic_limit = max(existing.traffic_limit or 0, traffic_limit or 0)
        existing.device_limit = max(existing.device_limit or 0, device_limit or 0)
        existing.expire_at = new_expire
        existing.is_trial = False
        existing.plan = plan

        updated_remna = await remnawave_service.updated_user(
            user=user,
            uuid=existing.user_remna_id,
            subscription=existing,
        )
        existing.expire_at = updated_remna.expire_at
        await subscription_service.update(existing)

        # Disable orphaned web Remnawave user (don't delete — deletion triggers
        # a webhook that can race with the merge and nuke the real subscription)
        try:
            await remnawave_service.remnawave.users.disable_user(remna_user.uuid)
            logger.info(f"{log(user)} Disabled orphaned web Remnawave user '{username}'")
        except Exception:
            logger.warning(f"{log(user)} Failed to disable orphaned web Remnawave user '{username}'")

        logger.info(
            f"{log(user)} Extended existing subscription by {total_days}d "
            f"(new expiry: {existing.expire_at}, email: {order.Email})"
        )
        await message.answer(
            f"✅ Подписка продлена на {total_days} дней!\n"
            f"📦 План: {plan.name}\n"
            f"📅 Действует до: {existing.expire_at.strftime('%d.%m.%Y')}"
        )
    else:
        # No existing subscription — create new one
        sub_url = remnawave_service._rewrite_sub_url(remna_user.subscription_url)
        subscription = SubscriptionDto(
            user_remna_id=remna_user.uuid,
            status=remna_user.status,
            is_trial=is_trial,
            traffic_limit=traffic_limit,
            device_limit=device_limit,
            traffic_limit_strategy=remna_user.traffic_limit_strategy or TrafficLimitStrategy.NO_RESET,
            tag=remna_user.tag,
            internal_squads=[s.uuid for s in remna_user.active_internal_squads],
            external_squad=remna_user.external_squad_uuid,
            expire_at=remna_user.expire_at,
            url=sub_url,
            plan=plan,
        )
        await subscription_service.create(user, subscription)
        kind = "trial" if is_trial else "purchase"
        logger.info(f"{log(user)} Linked web {kind} subscription '{username}' (email: {order.Email}, {total_days}d)")
        await message.answer(
            f"✅ Подписка привязана!\n"
            f"📦 План: {plan.name} ({total_days}д)\n"
            f"🔗 Ваша ссылка для подключения уже в профиле."
        )

    await notification_service.system_notify(
        ntf_type=SystemNotificationType.WEB_CLAIM,
        payload=MessagePayload.not_deleted(
            i18n_key="ntf-event-web-claim",
            i18n_kwargs={
                "user_id": str(user.telegram_id),
                "user_name": user.name,
                "username": user.username or False,
                "email": order.Email,
                "plan_name": plan.name,
                "plan_duration": total_days,
            },
        ),
    )


@inject
@router.message(F.text.contains("/api/sub/"))
async def on_subscription_url_paste(
    message: Message,
    user: UserDto,
    billing: FromDishka[BillingClient],
    remnawave_service: FromDishka[RemnawaveService],
    subscription_service: FromDishka[SubscriptionService],
    notification_service: FromDishka[NotificationService],
) -> None:
    """Handle when user pastes a subscription URL to link their web purchase."""
    import re  # noqa: PLC0415
    from remnapy.models import UpdateUserRequestDto  # noqa: PLC0415
    from remnapy.enums.users import TrafficLimitStrategy  # noqa: PLC0415
    from src.core.enums import PlanType  # noqa: PLC0415
    from src.core.utils.formatters import format_device_count  # noqa: PLC0415
    from src.infrastructure.database.models.dto import SubscriptionDto  # noqa: PLC0415

    text = (message.text or "").strip()

    # Extract the token (last path segment of the subscription URL)
    match = re.search(r"/api/sub/([A-Za-z0-9_-]+)", text)
    if not match:
        await message.answer("Не удалось распознать ссылку подписки.")
        return

    token = match.group(1)

    # Find the Remnawave user by subscription token (shortUuid)
    try:
        sub_info = await remnawave_service.remnawave.users.get_user_by_short_uuid(token)
    except Exception:
        logger.warning(f"{log(user)} Pasted sub URL with token '{token}' — remnawave user not found")
        await message.answer("Подписка не найдена. Проверьте ссылку и попробуйте снова.")
        return

    if not sub_info:
        await message.answer("Подписка не найдена. Проверьте ссылку и попробуйте снова.")
        return

    # Check if this remnawave user is already linked to a telegram account
    if sub_info.telegram_id and sub_info.telegram_id != user.telegram_id:
        await message.answer("Эта подписка уже привязана к другому аккаунту Telegram.")
        return

    if sub_info.telegram_id == user.telegram_id:
        await message.answer("Эта подписка уже привязана к вашему аккаунту.")
        return

    # Check if this user already has a subscription linked
    existing = await subscription_service.get_current(user.telegram_id)
    if existing:
        await message.answer(
            "У вас уже есть активная подписка. "
            "Для привязки другой подписки обратитесь в поддержку."
        )
        return

    # Link: update remnawave user with telegram_id
    await remnawave_service.remnawave.users.update_user(
        UpdateUserRequestDto(
            uuid=sub_info.uuid,
            telegram_id=user.telegram_id,
        )
    )

    # Link Customer if one exists for this Remnawave user
    customer = await billing.get_customer_by_remna_user_uuid(str(sub_info.uuid))
    if customer:
        if not customer.TelegramID:
            await billing.update_customer(
                customer.ID, telegram_id=user.telegram_id
            )
        if not user.customer_id:
            await billing.update_user(user.telegram_id, {"customer_id": customer.ID})

    # Try to find matching web order to claim it
    if sub_info.username and sub_info.username.startswith("web_"):
        short_id = sub_info.username[len("web_"):]
        order = await billing.get_web_order_by_short_id(short_id)
        if order and order.ClaimedByTelegramID is None:
            await billing.update_web_order(
                order.PaymentID,
                claimed_by_telegram_id=user.telegram_id,
            )

    # Create local subscription
    sub_url = remnawave_service._rewrite_sub_url(sub_info.subscription_url)

    # Determine plan details from remnawave user
    traffic_limit = sub_info.traffic_limit_bytes // (1024 ** 3) if sub_info.traffic_limit_bytes else -1
    device_limit = format_device_count(sub_info.hwid_device_limit)

    plan = PlanSnapshotDto(
        id=-1,
        name="Web Purchase",
        tag=sub_info.tag,
        type=PlanType.UNLIMITED,
        traffic_limit=traffic_limit,
        device_limit=device_limit,
        duration=-1,
        traffic_limit_strategy=sub_info.traffic_limit_strategy or TrafficLimitStrategy.NO_RESET,
        internal_squads=[s.uuid for s in sub_info.active_internal_squads],
        external_squad=sub_info.external_squad_uuid,
    )

    subscription = SubscriptionDto(
        user_remna_id=sub_info.uuid,
        status=sub_info.status,
        is_trial=False,
        traffic_limit=traffic_limit,
        device_limit=device_limit,
        traffic_limit_strategy=sub_info.traffic_limit_strategy or TrafficLimitStrategy.NO_RESET,
        tag=sub_info.tag,
        internal_squads=[s.uuid for s in sub_info.active_internal_squads],
        external_squad=sub_info.external_squad_uuid,
        expire_at=sub_info.expire_at,
        url=sub_url,
        plan=plan,
    )

    await subscription_service.create(user, subscription)
    logger.info(f"{log(user)} Linked subscription via pasted URL, token='{token}'")

    await message.answer(
        "Подписка успешно привязана к вашему аккаунту! "
        "Теперь вы можете управлять ей через бота."
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
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    billing_plan = await billing.get_trial_plan()

    if not billing_plan:
        await notification_service.notify_user(
            user=user,
            payload=MessagePayload(i18n_key="ntf-trial-unavailable"),
        )
        raise ValueError("Trial plan not exist")

    await billing.create_trial_subscription(user.telegram_id, billing_plan.ID)


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
    billing: FromDishka[BillingClient],
) -> None:
    settings = await billing.get_settings()
    referral_settings = settings.Referral or {}
    is_referral_enable = bool(referral_settings.get("enable", False))
    if is_referral_enable:
        await dialog_manager.switch_to(state=MainMenu.INVITE)
    else:
        return
