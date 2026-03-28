from typing import Any, Optional

from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.common import ManagedScroll
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from fluentogram import TranslatorRunner

from src.core.enums import PromocodeRewardType
from src.infrastructure.billing import (
    BillingClient,
    billing_plan_to_dto,
    billing_promocode_to_dto,
)
from src.infrastructure.database.models.dto import (
    PromocodeDto,
)


@inject
async def statistics_getter(
    dialog_manager: DialogManager,
    i18n: FromDishka[TranslatorRunner],
    billing: FromDishka[BillingClient],
    **kwargs: Any,
) -> dict[str, Any]:
    widget: Optional[ManagedScroll] = dialog_manager.find("statistics")

    if not widget:
        raise ValueError()

    current_page = await widget.get_page()

    # For pages that need detailed data, we fetch from billing API
    # and convert to DTOs that the existing stat functions expect.
    # Page 0 (users) is the most complex - we use the billing statistics
    # endpoint for aggregate data.

    match current_page:
        case 0:
            stats = await billing.get_statistics()
            statistics = {
                "total_users": stats.total_users,
                "new_users_daily": 0,
                "new_users_weekly": 0,
                "new_users_monthly": 0,
                "users_with_subscription": stats.active_subscriptions,
                "users_without_subscription": stats.total_users - stats.active_subscriptions,
                "users_with_trial": stats.trial_users,
                "blocked_users": 0,
                "bot_blocked_users": 0,
                "user_conversion": 0,
                "trial_conversion": 0,
            }
            template = "msg-statistics-users"
        case 1:
            stats = await billing.get_statistics()
            statistics = {
                "total_transactions": stats.today_transactions,
                "completed_transactions": stats.today_transactions,
                "free_transactions": 0,
                "popular_gateway": False,
                "payment_gateways": f"Total revenue: {stats.total_revenue}",
            }
            template = "msg-statistics-transactions"
        case 2:
            stats = await billing.get_statistics()
            statistics = {
                "total_active_subscriptions": stats.active_subscriptions,
                "total_expire_subscriptions": stats.total_subscriptions - stats.active_subscriptions,
                "active_trial_subscriptions": stats.trial_users,
                "expiring_subscriptions": 0,
                "total_unlimited": 0,
                "total_traffic": 0,
                "total_devices": 0,
            }
            template = "msg-statistics-subscriptions"
        case 3:
            billing_plans = await billing.list_plans()
            plans = [billing_plan_to_dto(bp) for bp in billing_plans]
            statistics = {"plans": "\n\n".join(
                f"{p.name}: active" for p in plans
            ) or "-"}
            template = "msg-statistics-plans"
        case 4:
            billing_promos = await billing.list_promocodes()
            promocodes = [billing_promocode_to_dto(bp) for bp in billing_promos]
            statistics = get_promocodes_statistics(promocodes)
            template = "msg-statistics-promocodes"
        case 5:
            template = "msg-statistics-referrals"
        case _:
            raise ValueError(f"Invalid statistics page index: '{current_page}'")

    formatted_message = i18n.get(template, **statistics)

    return {
        "pages": 4,
        "current_page": current_page + 1,
        "statistics": formatted_message,
    }


def get_promocodes_statistics(promocodes: list[PromocodeDto]) -> dict[str, Any]:
    total_promo_activations = sum(len(p.activations) for p in promocodes)
    most_popular_promo = max(promocodes, key=lambda p: len(p.activations), default=None)

    total_promo_days = 0
    total_promo_traffic = 0
    total_promo_subscriptions = 0
    total_promo_personal_discounts = 0
    total_promo_purchase_discounts = 0

    for p in promocodes:
        times_used = len(p.activations)
        reward_value = p.reward or 0

        if p.reward_type == PromocodeRewardType.DURATION:
            total_promo_days += reward_value * times_used
        elif p.reward_type == PromocodeRewardType.TRAFFIC:
            total_promo_traffic += reward_value * times_used
        elif p.reward_type == PromocodeRewardType.SUBSCRIPTION:
            total_promo_subscriptions += reward_value * times_used
        elif p.reward_type == PromocodeRewardType.PERSONAL_DISCOUNT:
            total_promo_personal_discounts += reward_value * times_used
        elif p.reward_type == PromocodeRewardType.PURCHASE_DISCOUNT:
            total_promo_purchase_discounts += reward_value * times_used

    return {
        "total_promo_activations": total_promo_activations,
        "most_popular_promo": most_popular_promo.code if most_popular_promo else "-",
        "total_promo_days": total_promo_days,
        "total_promo_traffic": total_promo_traffic,
        "total_promo_subscriptions": total_promo_subscriptions,
        "total_promo_personal_discounts": total_promo_personal_discounts,
        "total_promo_purchase_discounts": total_promo_purchase_discounts,
    }
