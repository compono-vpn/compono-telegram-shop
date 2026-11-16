from typing import Optional

from aiogram import Bot
from aiogram_dialog import BgManagerFactory, ShowMode, StartMode
from dishka.integrations.taskiq import FromDishka, inject

from src.bot.states import MainMenu, Subscription
from src.core.enums import PurchaseType
from src.infrastructure.billing import BillingClient
from src.infrastructure.taskiq.broker import broker
from src.models.dto import UserDto
from src.services.dedicated_ip import offer_country_choice
from src.services.notification import NotificationService
from src.services.source_survey import offer_source_survey


@broker.task
@inject
async def redirect_to_main_menu_task(
    telegram_id: int,
    bot: FromDishka[Bot],
    bg_manager_factory: FromDishka[BgManagerFactory],
) -> None:
    bg_manager = bg_manager_factory.bg(
        bot=bot,
        user_id=telegram_id,
        chat_id=telegram_id,
    )
    await bg_manager.start(
        state=MainMenu.MAIN,
        mode=StartMode.RESET_STACK,
        show_mode=ShowMode.DELETE_AND_SEND,
    )


@broker.task
@inject
async def redirect_to_successed_trial_task(
    user: UserDto,
    bot: FromDishka[Bot],
    bg_manager_factory: FromDishka[BgManagerFactory],
) -> None:
    bg_manager = bg_manager_factory.bg(
        bot=bot,
        user_id=user.telegram_id,
        chat_id=user.telegram_id,
    )
    await bg_manager.start(
        state=Subscription.TRIAL,
        mode=StartMode.RESET_STACK,
        show_mode=ShowMode.DELETE_AND_SEND,
    )


@broker.task
@inject
async def redirect_to_successed_payment_task(
    user: UserDto,
    purchase_type: PurchaseType,
    bot: FromDishka[Bot],
    bg_manager_factory: FromDishka[BgManagerFactory],
    billing: FromDishka[BillingClient],
    notification_service: FromDishka[NotificationService],
    plan_tag: Optional[str] = None,
) -> None:
    bg_manager = bg_manager_factory.bg(
        bot=bot,
        user_id=user.telegram_id,
        chat_id=user.telegram_id,
    )
    await bg_manager.start(
        state=Subscription.SUCCESS,
        data={"purchase_type": purchase_type},
        mode=StartMode.RESET_STACK,
        show_mode=ShowMode.DELETE_AND_SEND,
    )
    await offer_country_choice(
        user=user,
        plan_tag=plan_tag,
        billing=billing,
        notification_service=notification_service,
    )
    await offer_source_survey(user=user, billing=billing, notification_service=notification_service)


@broker.task
@inject
async def redirect_to_failed_subscription_task(
    user: UserDto,
    bot: FromDishka[Bot],
    bg_manager_factory: FromDishka[BgManagerFactory],
) -> None:
    bg_manager = bg_manager_factory.bg(
        bot=bot,
        user_id=user.telegram_id,
        chat_id=user.telegram_id,
    )
    await bg_manager.start(
        state=Subscription.FAILED,
        mode=StartMode.RESET_STACK,
        show_mode=ShowMode.DELETE_AND_SEND,
    )
