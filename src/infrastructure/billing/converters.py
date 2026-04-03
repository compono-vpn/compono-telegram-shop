"""Converters between BillingClient response models and bot DTO types.

Maps the PascalCase Billing API responses to the snake_case DTO objects
that templates and handlers expect.
"""

from decimal import Decimal
from typing import Optional
from uuid import UUID

from src.core.enums import (
    AccessMode,
    BroadcastAudience,
    BroadcastMessageStatus,
    BroadcastStatus,
    Currency,
    GatewayChannel,
    PaymentGatewayType,
    PlanAvailability,
    PlanType,
    PromocodeAvailability,
    PromocodeRewardType,
    ReferralAccrualStrategy,
    ReferralLevel,
    ReferralRewardStrategy,
    ReferralRewardType,
    SubscriptionStatus,
    TransactionStatus,
    PurchaseType,
)

from remnapy.enums.users import TrafficLimitStrategy

from src.models.dto import (
    PlanDto,
    PlanDurationDto,
    PlanPriceDto,
    PlanSnapshotDto,
    PriceDetailsDto,
    PromocodeActivationDto,
    PromocodeDto,
    ReferralDto,
    ReferralRewardDto,
    SettingsDto,
    ReferralSettingsDto,
    SystemNotificationDto,
    UserNotificationDto,
    SubscriptionDto,
    TransactionDto,
    PaymentGatewayDto,
    BaseTransactionDto,
)
from src.models.dto.settings import ReferralRewardSettingsDto

from src.models.dto.user import UserDto
from src.core.enums import UserRole, Locale

from .models import (
    BillingBroadcast,
    BillingBroadcastMessage,
    BillingUser,
    BillingReferral,
    BillingReferralReward,
    BillingSettings,
    BillingPaymentGateway,
    BillingPlan,
    BillingPlanDuration,
    BillingPlanPrice,
    BillingPlanSnapshot,
    BillingPriceDetails,
    BillingPromocode,
    BillingPromocodeActivation,
    BillingSubscription,
    BillingTransaction,
)


# ------------------------------------------------------------------ #
# Plans
# ------------------------------------------------------------------ #


def _parse_uuids(raw: Optional[list[str]]) -> list[UUID]:
    """Convert a list of UUID strings to UUID objects, handling None."""
    if not raw:
        return []
    result = []
    for s in raw:
        try:
            result.append(UUID(s))
        except (ValueError, TypeError):
            continue
    return result


def _parse_uuid(raw: Optional[str]) -> Optional[UUID]:
    if not raw:
        return None
    try:
        return UUID(raw)
    except (ValueError, TypeError):
        return None


def billing_plan_price_to_dto(bp: BillingPlanPrice) -> PlanPriceDto:
    return PlanPriceDto(
        id=bp.ID if bp.ID else None,
        currency=Currency(bp.Currency),
        price=Decimal(bp.Price),
    )


def billing_plan_duration_to_dto(bd: BillingPlanDuration) -> PlanDurationDto:
    return PlanDurationDto(
        id=bd.ID if bd.ID else None,
        days=bd.Days,
        prices=[billing_plan_price_to_dto(p) for p in bd.Prices],
    )


def billing_plan_to_dto(bp: BillingPlan) -> PlanDto:
    return PlanDto(
        id=bp.ID if bp.ID else None,
        order_index=bp.OrderIndex,
        is_active=bp.IsActive,
        type=PlanType(bp.Type) if bp.Type else PlanType.BOTH,
        availability=PlanAvailability(bp.Availability) if bp.Availability else PlanAvailability.ALL,
        name=bp.Name,
        description=bp.Description,
        tag=bp.Tag,
        traffic_limit=bp.TrafficLimit,
        device_limit=bp.DeviceLimit,
        traffic_limit_strategy=TrafficLimitStrategy(bp.TrafficLimitStrategy) if bp.TrafficLimitStrategy else TrafficLimitStrategy.NO_RESET,
        allowed_user_ids=bp.AllowedUserIDs or [],
        internal_squads=_parse_uuids(bp.InternalSquads),
        external_squad=_parse_uuid(bp.ExternalSquad) if bp.ExternalSquad else None,
        durations=[billing_plan_duration_to_dto(d) for d in bp.Durations],
    )


def billing_plan_snapshot_to_dto(bs: BillingPlanSnapshot) -> PlanSnapshotDto:
    return PlanSnapshotDto(
        id=bs.id,
        name=bs.name,
        tag=bs.tag,
        type=PlanType(bs.type) if bs.type else PlanType.BOTH,
        traffic_limit=bs.traffic_limit,
        device_limit=bs.device_limit,
        duration=bs.duration,
        traffic_limit_strategy=TrafficLimitStrategy(bs.traffic_limit_strategy) if bs.traffic_limit_strategy else TrafficLimitStrategy.NO_RESET,
        internal_squads=_parse_uuids(bs.internal_squads),
        external_squad=_parse_uuid(bs.external_squad) if bs.external_squad else None,
    )


# ------------------------------------------------------------------ #
# Subscriptions
# ------------------------------------------------------------------ #


def billing_subscription_to_dto(bs: BillingSubscription) -> SubscriptionDto:
    plan_snapshot = billing_plan_snapshot_to_dto(bs.Plan) if bs.Plan else PlanSnapshotDto.test()
    return SubscriptionDto(
        id=bs.ID if bs.ID else None,
        user_remna_id=UUID(bs.UserRemnaID) if bs.UserRemnaID else UUID(int=0),
        status=SubscriptionStatus(bs.Status) if bs.Status else SubscriptionStatus.ACTIVE,
        is_trial=bs.IsTrial,
        traffic_limit=bs.TrafficLimit,
        device_limit=bs.DeviceLimit,
        traffic_limit_strategy=TrafficLimitStrategy(bs.TrafficLimitStrategy) if bs.TrafficLimitStrategy else TrafficLimitStrategy.NO_RESET,
        tag=bs.Tag,
        internal_squads=_parse_uuids(bs.InternalSquads),
        external_squad=_parse_uuid(bs.ExternalSquad) if bs.ExternalSquad else None,
        expire_at=bs.ExpireAt,
        url=bs.URL,
        plan=plan_snapshot,
        created_at=bs.CreatedAt,
        updated_at=bs.UpdatedAt,
    )


# ------------------------------------------------------------------ #
# Transactions
# ------------------------------------------------------------------ #


def billing_price_details_to_dto(bp: BillingPriceDetails) -> PriceDetailsDto:
    return PriceDetailsDto(
        original_amount=Decimal(bp.original_amount),
        discount_percent=bp.discount_percent,
        final_amount=Decimal(bp.final_amount),
    )


def billing_transaction_to_dto(bt: BillingTransaction) -> TransactionDto:
    plan_snapshot = billing_plan_snapshot_to_dto(bt.Plan) if bt.Plan else PlanSnapshotDto.test()
    pricing = billing_price_details_to_dto(bt.Pricing) if bt.Pricing else PriceDetailsDto()
    return TransactionDto(
        id=bt.ID if bt.ID else None,
        payment_id=UUID(bt.PaymentID) if bt.PaymentID else UUID(int=0),
        status=TransactionStatus(bt.Status) if bt.Status else TransactionStatus.PENDING,
        is_test=bt.IsTest,
        purchase_type=PurchaseType(bt.PurchaseType) if bt.PurchaseType else PurchaseType.NEW,
        gateway_type=PaymentGatewayType(bt.GatewayType) if bt.GatewayType else PaymentGatewayType.TELEGRAM_STARS,
        pricing=pricing,
        currency=Currency(bt.Currency) if bt.Currency else Currency.USD,
        plan=plan_snapshot,
        created_at=bt.CreatedAt,
        updated_at=bt.UpdatedAt,
    )


# ------------------------------------------------------------------ #
# Promocodes
# ------------------------------------------------------------------ #


def billing_promocode_activation_to_dto(ba: BillingPromocodeActivation) -> PromocodeActivationDto:
    return PromocodeActivationDto(
        id=ba.ID if ba.ID else None,
        promocode_id=ba.PromocodeID,
        user_telegram_id=ba.UserTelegramID,
        activated_at=ba.ActivatedAt,
    )


def billing_promocode_to_dto(bp: BillingPromocode) -> PromocodeDto:
    plan_snapshot = billing_plan_snapshot_to_dto(bp.Plan) if bp.Plan else None
    return PromocodeDto(
        id=bp.ID if bp.ID else None,
        code=bp.Code,
        is_active=bp.IsActive,
        availability=PromocodeAvailability(bp.Availability) if bp.Availability else PromocodeAvailability.ALL,
        reward_type=PromocodeRewardType(bp.RewardType) if bp.RewardType else PromocodeRewardType.PERSONAL_DISCOUNT,
        reward=bp.Reward,
        plan=plan_snapshot,
        purchase_discount_max_days=bp.PurchaseDiscountMaxDays,
        lifetime=bp.Lifetime,
        max_activations=bp.MaxActivations,
        allowed_telegram_ids=bp.AllowedTelegramIDs,
        activations=[billing_promocode_activation_to_dto(a) for a in (bp.Activations or [])],
        created_at=bp.CreatedAt,
        updated_at=bp.UpdatedAt,
    )


# ------------------------------------------------------------------ #
# Payment Gateways
# ------------------------------------------------------------------ #


def billing_gateway_to_dto(bg: BillingPaymentGateway) -> PaymentGatewayDto:
    """Convert BillingPaymentGateway to PaymentGatewayDto.

    Note: The billing API does not expose gateway settings (secrets).
    The returned DTO will have settings=None. This is fine for listing/display
    but gateway setting edits still go through the local PaymentGatewayService.
    """
    return PaymentGatewayDto(
        id=bg.ID if bg.ID else None,
        order_index=bg.OrderIndex,
        type=PaymentGatewayType(bg.Type) if bg.Type else PaymentGatewayType.TELEGRAM_STARS,
        channel=GatewayChannel(bg.Channel) if bg.Channel else GatewayChannel.ALL,
        currency=Currency(bg.Currency) if bg.Currency else Currency.USD,
        is_active=bg.IsActive,
        settings=None,
    )


# ------------------------------------------------------------------ #
# Users
# ------------------------------------------------------------------ #


def billing_user_to_dto(bu: BillingUser) -> UserDto:
    return UserDto(
        id=bu.ID if bu.ID else None,
        telegram_id=bu.TelegramID,
        username=bu.Username,
        referral_code=bu.ReferralCode,
        name=bu.Name,
        role=UserRole(bu.Role) if bu.Role else UserRole.USER,
        language=(bu.Language or "ru").lower(),
        personal_discount=bu.PersonalDiscount,
        purchase_discount=bu.PurchaseDiscount,
        purchase_discount_max_days=bu.PurchaseDiscountMaxDays,
        points=bu.Points,
        source=bu.Source,
        is_blocked=bu.IsBlocked,
        is_bot_blocked=bu.IsBotBlocked,
        is_rules_accepted=bu.IsRulesAccepted,
        created_at=bu.CreatedAt,
        updated_at=bu.UpdatedAt,
    )


# ------------------------------------------------------------------ #
# Settings
# ------------------------------------------------------------------ #


def billing_settings_to_dto(bs: BillingSettings) -> SettingsDto:
    sys_ntf = SystemNotificationDto()
    if bs.SystemNotifications and isinstance(bs.SystemNotifications, dict):
        for k, v in bs.SystemNotifications.items():
            key = k.lower() if isinstance(k, str) else k
            if hasattr(sys_ntf, key):
                setattr(sys_ntf, key, bool(v))

    user_ntf = UserNotificationDto()
    if bs.UserNotifications and isinstance(bs.UserNotifications, dict):
        for k, v in bs.UserNotifications.items():
            key = k.lower() if isinstance(k, str) else k
            if hasattr(user_ntf, key):
                setattr(user_ntf, key, bool(v))

    referral = ReferralSettingsDto()
    if bs.Referral and isinstance(bs.Referral, dict):
        referral.enable = bs.Referral.get("Enable", bs.Referral.get("enable", True))
        level_val = bs.Referral.get("Level", bs.Referral.get("level", "FIRST"))
        referral.level = ReferralLevel(level_val) if level_val else ReferralLevel.FIRST
        accrual = bs.Referral.get("AccrualStrategy", bs.Referral.get("accrual_strategy", "ON_FIRST_PAYMENT"))
        referral.accrual_strategy = ReferralAccrualStrategy(accrual) if accrual else ReferralAccrualStrategy.ON_FIRST_PAYMENT
        reward_data = bs.Referral.get("Reward", bs.Referral.get("reward"))
        if reward_data and isinstance(reward_data, dict):
            rtype = reward_data.get("Type", reward_data.get("type", "EXTRA_DAYS"))
            rstrategy = reward_data.get("Strategy", reward_data.get("strategy", "AMOUNT"))
            rconfig = reward_data.get("Config", reward_data.get("config", {}))
            parsed_config = {}
            for rk, rv in (rconfig or {}).items():
                try:
                    parsed_config[ReferralLevel(rk)] = int(rv)
                except (ValueError, TypeError):
                    pass
            referral.reward = ReferralRewardSettingsDto(
                type=ReferralRewardType(rtype) if rtype else ReferralRewardType.EXTRA_DAYS,
                strategy=ReferralRewardStrategy(rstrategy) if rstrategy else ReferralRewardStrategy.AMOUNT,
                config=parsed_config or {ReferralLevel.FIRST: 5},
            )

    return SettingsDto(
        id=bs.ID if bs.ID else None,
        rules_required=bs.RulesRequired,
        channel_required=bs.ChannelRequired,
        rules_link=bs.RulesLink or "https://telegram.org/tos/",
        channel_id=bs.ChannelID,
        channel_link=bs.ChannelLink or "@remna_shop",
        access_mode=AccessMode(bs.AccessMode) if bs.AccessMode else AccessMode.PUBLIC,
        purchases_allowed=bs.PurchasesAllowed,
        registration_allowed=bs.RegistrationAllowed,
        default_currency=Currency(bs.DefaultCurrency) if bs.DefaultCurrency else Currency.XTR,
        user_notifications=user_ntf,
        system_notifications=sys_ntf,
        referral=referral,
    )


# ------------------------------------------------------------------ #
# Referrals
# ------------------------------------------------------------------ #


def _stub_user(telegram_id: int) -> "BaseUserDto":
    """Create a minimal BaseUserDto from just a telegram ID.

    The billing API only returns telegram IDs for referrer/referred,
    not full user objects. This stub is sufficient for the referral
    service which only accesses telegram_id on these objects.
    """
    from src.models.dto.user import BaseUserDto  # noqa: PLC0415

    return BaseUserDto(telegram_id=telegram_id, name="")


def billing_referral_to_dto(br: BillingReferral) -> ReferralDto:
    return ReferralDto(
        id=br.ID if br.ID else None,
        level=ReferralLevel(br.Level) if br.Level else ReferralLevel.FIRST,
        referrer=_stub_user(br.ReferrerTelegramID),
        referred=_stub_user(br.ReferredTelegramID),
        created_at=br.CreatedAt,
        updated_at=br.UpdatedAt,
    )


def billing_referral_reward_to_dto(brr: BillingReferralReward) -> ReferralRewardDto:
    return ReferralRewardDto(
        id=brr.ID if brr.ID else None,
        type=ReferralRewardType(brr.Type) if brr.Type else ReferralRewardType.EXTRA_DAYS,
        amount=brr.Amount,
        is_issued=brr.IsIssued,
        created_at=brr.CreatedAt,
        updated_at=brr.UpdatedAt,
    )


# ------------------------------------------------------------------ #
# Broadcasts
# ------------------------------------------------------------------ #


def billing_broadcast_message_to_dto(bm: BillingBroadcastMessage) -> "BroadcastMessageDto":
    from src.models.dto import BroadcastMessageDto  # noqa: PLC0415

    return BroadcastMessageDto(
        id=bm.ID if bm.ID else None,
        user_id=bm.UserID,
        message_id=bm.MessageID,
        status=BroadcastMessageStatus(bm.Status) if bm.Status else BroadcastMessageStatus.PENDING,
    )


def billing_broadcast_to_dto(bb: BillingBroadcast) -> "BroadcastDto":
    from src.models.dto import BroadcastDto  # noqa: PLC0415
    from src.core.utils.message_payload import MessagePayload  # noqa: PLC0415

    payload = MessagePayload.model_validate(bb.Payload) if bb.Payload else MessagePayload(
        i18n_key="ntf-broadcast-preview",
    )
    messages = [billing_broadcast_message_to_dto(m) for m in (bb.Messages or [])]

    return BroadcastDto(
        id=bb.ID if bb.ID else None,
        task_id=UUID(bb.TaskID) if bb.TaskID else UUID(int=0),
        status=BroadcastStatus(bb.Status) if bb.Status else BroadcastStatus.PROCESSING,
        audience=BroadcastAudience(bb.Audience) if bb.Audience else BroadcastAudience.ALL,
        total_count=bb.TotalCount,
        success_count=bb.SuccessCount,
        failed_count=bb.FailedCount,
        payload=payload,
        messages=messages,
        created_at=bb.CreatedAt,
        updated_at=bb.UpdatedAt,
    )
