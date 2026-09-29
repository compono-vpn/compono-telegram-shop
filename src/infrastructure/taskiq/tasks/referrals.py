from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from dishka.integrations.taskiq import FromDishka, inject
from loguru import logger

from src.bot.keyboards import get_connect_keyboard
from src.core.config import AppConfig
from src.core.enums import (
    MessageEffect,
    ReferralRewardType,
    SubscriptionStatus,
    UserNotificationType,
)
from src.core.utils.message_payload import MessagePayload
from src.core.utils.time import datetime_now
from src.infrastructure.api import ApiClient
from src.infrastructure.billing import BillingClient
from src.infrastructure.taskiq.broker import broker
from src.models.dto import PlanSnapshotDto, ReferralRewardDto, SubscriptionDto, UserDto
from src.services.notification import NotificationService
from src.services.plan import PlanService
from src.services.referral import ReferralService
from src.services.remnawave import RemnawaveService
from src.services.subscription import SubscriptionService
from src.services.user import UserService


async def _grant_on_current_plan(
    user: UserDto,
    subscription: SubscriptionDto,
    days: int,
    billing: BillingClient,
    subscription_service: SubscriptionService,
) -> None:
    await billing.grant_subscription(
        telegram_id=user.telegram_id,
        plan_id=subscription.plan.id,
        duration_days=days,
        reason="referral_reward",
    )
    await subscription_service.clear_subscription_cache(subscription.id, user.telegram_id)


async def _provision_reward_subscription(
    user: UserDto,
    plan: PlanSnapshotDto,
    api_client: ApiClient,
    subscription_service: SubscriptionService,
) -> str:
    result = await api_client.provision_user(
        telegram_id=user.telegram_id,
        plan=plan,
        name=user.name,
        username=user.username,
        language=user.language.value if user.language else None,
    )
    await subscription_service.create(
        user,
        SubscriptionDto(
            user_remna_id=UUID(result.remnawave_user_id),
            status=SubscriptionStatus(result.status),
            traffic_limit=plan.traffic_limit,
            device_limit=plan.device_limit,
            traffic_limit_strategy=plan.traffic_limit_strategy,
            tag=plan.tag,
            internal_squads=plan.internal_squads,
            external_squad=plan.external_squad,
            expire_at=datetime.fromisoformat(result.expire_at),
            url=result.subscription_url,
            plan=plan,
        ),
    )
    return result.subscription_url


async def _upgrade_trial_to_reward_subscription(
    user: UserDto,
    trial: SubscriptionDto,
    plan: PlanSnapshotDto,
    subscription_service: SubscriptionService,
    remnawave_service: RemnawaveService,
) -> str:
    trial.status = SubscriptionStatus.DISABLED
    await subscription_service.update(trial)

    remaining_days = max((trial.expire_at - datetime_now()).total_seconds() / 86400, 0)
    expire_at = datetime_now() + timedelta(days=plan.duration + remaining_days)

    updated_user = await remnawave_service.updated_user(
        user=user,
        uuid=trial.user_remna_id,
        subscription=SubscriptionDto(
            user_remna_id=trial.user_remna_id,
            status=SubscriptionStatus.ACTIVE,
            traffic_limit=plan.traffic_limit,
            device_limit=plan.device_limit,
            traffic_limit_strategy=plan.traffic_limit_strategy,
            tag=plan.tag,
            internal_squads=plan.internal_squads,
            external_squad=plan.external_squad,
            expire_at=expire_at,
            url=trial.url,
            plan=plan,
        ),
        reset_traffic=True,
    )
    await subscription_service.create(
        user,
        SubscriptionDto(
            user_remna_id=updated_user.uuid,
            status=updated_user.status,
            traffic_limit=plan.traffic_limit,
            device_limit=plan.device_limit,
            traffic_limit_strategy=plan.traffic_limit_strategy,
            tag=plan.tag,
            internal_squads=plan.internal_squads,
            external_squad=plan.external_squad,
            expire_at=updated_user.expire_at,
            url=updated_user.subscription_url,
            plan=plan,
        ),
    )
    return updated_user.subscription_url


async def grant_extra_days(
    user: UserDto,
    days: int,
    subscription: Optional[SubscriptionDto],
    plan_service: PlanService,
    api_client: ApiClient,
    subscription_service: SubscriptionService,
    remnawave_service: RemnawaveService,
    billing: BillingClient,
) -> tuple[bool, Optional[str]]:
    """Give `days` of access whatever subscription state the referrer is in.

    Returns (granted, subscription_url); the url is set only when access was
    newly provisioned, so the caller can offer a connect link.
    """
    if subscription and not subscription.is_trial:
        await _grant_on_current_plan(user, subscription, days, billing, subscription_service)
        return True, None

    entry_plan = await plan_service.get_entry_plan()
    if not entry_plan:
        logger.warning(
            f"No entry plan available, cannot grant '{days}' referral days "
            f"to user '{user.telegram_id}'"
        )
        return False, None

    plan = PlanSnapshotDto.from_plan(entry_plan, days)
    if subscription:
        subscription_url = await _upgrade_trial_to_reward_subscription(
            user, subscription, plan, subscription_service, remnawave_service
        )
        logger.info(
            f"Upgraded trial to '{plan.name}' for '{days}' referral days "
            f"for user '{user.telegram_id}'"
        )
    else:
        subscription_url = await _provision_reward_subscription(
            user, plan, api_client, subscription_service
        )
        logger.info(
            f"Provisioned '{plan.name}' for '{days}' referral days for user '{user.telegram_id}'"
        )
    return True, subscription_url


@broker.task(retry_on_error=True)
@inject
async def give_referrer_reward_task(
    user_telegram_id: int,
    reward: ReferralRewardDto,
    referred_name: str,
    config: FromDishka[AppConfig],
    user_service: FromDishka[UserService],
    plan_service: FromDishka[PlanService],
    api_client: FromDishka[ApiClient],
    subscription_service: FromDishka[SubscriptionService],
    remnawave_service: FromDishka[RemnawaveService],
    notification_service: FromDishka[NotificationService],
    referral_service: FromDishka[ReferralService],
    billing: FromDishka[BillingClient],
) -> None:
    logger.info(
        f"Start applying reward of '{reward.amount}' '{reward.type}' to user '{user_telegram_id}'"
    )
    user = await user_service.get(user_telegram_id)

    if not user:
        raise ValueError(
            f"User '{user_telegram_id}' not found for applying "
            f"'{reward.amount}' '{reward.type.name}' reward"
        )

    connect_url: Optional[str] = None
    if reward.type == ReferralRewardType.POINTS:
        await user_service.add_points(user=user, points=reward.amount)
    elif reward.type == ReferralRewardType.EXTRA_DAYS:
        subscription = await subscription_service.get_current(user_telegram_id)
        granted, subscription_url = await grant_extra_days(
            user=user,
            days=reward.amount,
            subscription=subscription,
            plan_service=plan_service,
            api_client=api_client,
            subscription_service=subscription_service,
            remnawave_service=remnawave_service,
            billing=billing,
        )
        if not granted:
            await notification_service.notify_user(
                user=user,
                payload=MessagePayload.not_deleted(
                    i18n_key="ntf-event-user-referral-reward-error",
                    i18n_kwargs={
                        "name": referred_name,
                        "value": reward.amount,
                    },
                ),
                ntf_type=UserNotificationType.REFERRAL_REWARD,
            )
            return
        if subscription_url:
            connect_url = SubscriptionService.build_connect_url(
                subscription_url, config.website_url
            )
    else:
        raise ValueError(
            f"Failed to apply reward: unknown type '{reward.type}' for user '{user_telegram_id}'"
        )

    await notification_service.notify_user(
        user=user,
        payload=MessagePayload.not_deleted(
            i18n_key=(
                "ntf-event-user-referral-reward-subscription"
                if connect_url
                else "ntf-event-user-referral-reward"
            ),
            i18n_kwargs={
                "name": referred_name,
                "value": reward.amount,
                "reward_type": reward.type,
            },
            message_effect=MessageEffect.CONFETTI,
            reply_markup=get_connect_keyboard(connect_url) if connect_url else None,
        ),
        ntf_type=UserNotificationType.REFERRAL_REWARD,
    )
    await referral_service.mark_reward_as_issued(reward.id)  # type: ignore[arg-type]
    logger.info(f"Finished applying reward to user '{user_telegram_id}'")
    await referral_service.issue_pending_rewards(user_telegram_id)
