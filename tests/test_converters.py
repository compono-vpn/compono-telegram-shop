"""Tests for billing API converters -- verify correct mapping from billing models to DTOs."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
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
    PurchaseType,
    ReferralAccrualStrategy,
    ReferralLevel,
    ReferralRewardStrategy,
    ReferralRewardType,
    SubscriptionStatus,
    TransactionStatus,
    UserRole,
)
from remnapy.enums.users import TrafficLimitStrategy

from src.infrastructure.billing.converters import (
    billing_broadcast_message_to_dto,
    billing_broadcast_to_dto,
    billing_gateway_to_dto,
    billing_plan_duration_to_dto,
    billing_plan_price_to_dto,
    billing_plan_snapshot_to_dto,
    billing_plan_to_dto,
    billing_price_details_to_dto,
    billing_promocode_to_dto,
    billing_referral_reward_to_dto,
    billing_referral_to_dto,
    billing_settings_to_dto,
    billing_subscription_to_dto,
    billing_transaction_to_dto,
    billing_user_to_dto,
)
from src.infrastructure.billing.models import (
    BillingBroadcast,
    BillingBroadcastMessage,
    BillingPaymentGateway,
    BillingPlan,
    BillingPlanDuration,
    BillingPlanPrice,
    BillingPlanSnapshot,
    BillingPriceDetails,
    BillingPromocode,
    BillingPromocodeActivation,
    BillingReferral,
    BillingReferralReward,
    BillingSettings,
    BillingSubscription,
    BillingTransaction,
    BillingUser,
)
from src.models.dto.plan import PlanDto, PlanDurationDto, PlanPriceDto, PlanSnapshotDto
from src.models.dto.settings import (
    ReferralRewardSettingsDto,
    ReferralSettingsDto,
    SettingsDto,
    SystemNotificationDto,
    UserNotificationDto,
)
from src.models.dto.user import UserDto


# ---------------------------------------------------------------------------
# Plan converters
# ---------------------------------------------------------------------------


class TestBillingPlanPriceToDto:

    def test_basic_conversion(self):
        bp = BillingPlanPrice(ID=1, DurationID=10, Currency="RUB", Price="119")
        dto = billing_plan_price_to_dto(bp)

        assert dto.id == 1
        assert dto.currency == Currency.RUB
        assert dto.price == Decimal("119")

    def test_zero_id(self):
        bp = BillingPlanPrice(ID=0, Currency="USD", Price="5.99")
        dto = billing_plan_price_to_dto(bp)

        # ID=0 is falsy, so converter sets None
        assert dto.id is None

    def test_star_currency(self):
        bp = BillingPlanPrice(ID=2, Currency="XTR", Price="100")
        dto = billing_plan_price_to_dto(bp)

        assert dto.currency == Currency.XTR
        assert dto.price == Decimal("100")


class TestBillingPlanDurationToDto:

    def test_basic_conversion(self):
        bd = BillingPlanDuration(
            ID=1,
            PlanID=42,
            Days=30,
            Prices=[
                BillingPlanPrice(ID=1, DurationID=1, Currency="RUB", Price="119"),
                BillingPlanPrice(ID=2, DurationID=1, Currency="USD", Price="1.99"),
            ],
        )
        dto = billing_plan_duration_to_dto(bd)

        assert dto.id == 1
        assert dto.days == 30
        assert len(dto.prices) == 2
        assert dto.prices[0].currency == Currency.RUB
        assert dto.prices[1].currency == Currency.USD

    def test_empty_prices(self):
        bd = BillingPlanDuration(ID=1, PlanID=42, Days=7, Prices=[])
        dto = billing_plan_duration_to_dto(bd)

        assert dto.days == 7
        assert dto.prices == []


class TestBillingPlanToDto:

    def test_full_conversion(self):
        bp = BillingPlan(
            ID=42,
            OrderIndex=1,
            IsActive=True,
            Type="BOTH",
            Availability="ALL",
            Name="Pro Plan",
            Description="Best plan",
            Tag="pro",
            TrafficLimit=300,
            DeviceLimit=6,
            TrafficLimitStrategy="MONTH",
            AllowedUserIDs=[111, 222],
            InternalSquads=["550e8400-e29b-41d4-a716-446655440000"],
            ExternalSquad="550e8400-e29b-41d4-a716-446655440001",
            Durations=[
                BillingPlanDuration(
                    ID=1,
                    PlanID=42,
                    Days=30,
                    Prices=[BillingPlanPrice(ID=1, DurationID=1, Currency="RUB", Price="119")],
                ),
            ],
        )
        dto = billing_plan_to_dto(bp)

        assert isinstance(dto, PlanDto)
        assert dto.id == 42
        assert dto.order_index == 1
        assert dto.is_active is True
        assert dto.type == PlanType.BOTH
        assert dto.availability == PlanAvailability.ALL
        assert dto.name == "Pro Plan"
        assert dto.description == "Best plan"
        assert dto.tag == "pro"
        assert dto.traffic_limit == 300
        assert dto.device_limit == 6
        assert dto.traffic_limit_strategy == TrafficLimitStrategy.MONTH
        assert dto.allowed_user_ids == [111, 222]
        assert len(dto.internal_squads) == 1
        assert dto.internal_squads[0] == UUID("550e8400-e29b-41d4-a716-446655440000")
        assert dto.external_squad == UUID("550e8400-e29b-41d4-a716-446655440001")
        assert len(dto.durations) == 1
        assert dto.durations[0].days == 30

    def test_empty_type_defaults_to_both(self):
        bp = BillingPlan(ID=1, Name="Minimal", Type="", Availability="")
        dto = billing_plan_to_dto(bp)

        assert dto.type == PlanType.BOTH
        assert dto.availability == PlanAvailability.ALL

    def test_none_squads(self):
        bp = BillingPlan(ID=1, Name="Test", InternalSquads=None, ExternalSquad=None)
        dto = billing_plan_to_dto(bp)

        assert dto.internal_squads == []
        assert dto.external_squad is None

    def test_invalid_uuid_in_squads_skipped(self):
        bp = BillingPlan(ID=1, Name="Test", InternalSquads=["not-a-uuid", "550e8400-e29b-41d4-a716-446655440000"])
        dto = billing_plan_to_dto(bp)

        assert len(dto.internal_squads) == 1


class TestBillingPlanSnapshotToDto:

    def test_basic_conversion(self):
        bs = BillingPlanSnapshot(
            id=42,
            name="Pro Plan",
            tag="pro",
            type="BOTH",
            traffic_limit=300,
            device_limit=6,
            duration=30,
            traffic_limit_strategy="MONTH",
            internal_squads=["550e8400-e29b-41d4-a716-446655440000"],
            external_squad="550e8400-e29b-41d4-a716-446655440001",
        )
        dto = billing_plan_snapshot_to_dto(bs)

        assert isinstance(dto, PlanSnapshotDto)
        assert dto.id == 42
        assert dto.name == "Pro Plan"
        assert dto.type == PlanType.BOTH
        assert dto.duration == 30
        assert dto.traffic_limit_strategy == TrafficLimitStrategy.MONTH
        assert len(dto.internal_squads) == 1
        assert dto.external_squad == UUID("550e8400-e29b-41d4-a716-446655440001")

    def test_empty_type_defaults(self):
        bs = BillingPlanSnapshot(id=1, name="Test", type="", traffic_limit_strategy="")
        dto = billing_plan_snapshot_to_dto(bs)

        assert dto.type == PlanType.BOTH
        assert dto.traffic_limit_strategy == TrafficLimitStrategy.NO_RESET


# ---------------------------------------------------------------------------
# Subscription converter
# ---------------------------------------------------------------------------


class TestBillingSubscriptionToDto:

    def test_full_conversion(self):
        now = datetime(2025, 6, 1, tzinfo=timezone.utc)
        expire = datetime(2025, 7, 1, tzinfo=timezone.utc)
        bs = BillingSubscription(
            ID=10,
            UserRemnaID="550e8400-e29b-41d4-a716-446655440000",
            UserTelegramID=123456789,
            Status="ACTIVE",
            IsTrial=False,
            TrafficLimit=300,
            DeviceLimit=6,
            TrafficLimitStrategy="MONTH",
            Tag="pro",
            InternalSquads=[],
            ExternalSquad=None,
            ExpireAt=expire,
            URL="https://panel.example.com/sub/abc",
            Plan=BillingPlanSnapshot(id=42, name="Pro", type="BOTH", duration=30, traffic_limit_strategy="MONTH"),
            CreatedAt=now,
            UpdatedAt=now,
        )
        dto = billing_subscription_to_dto(bs)

        assert dto.id == 10
        assert dto.user_remna_id == UUID("550e8400-e29b-41d4-a716-446655440000")
        assert dto.status == SubscriptionStatus.ACTIVE
        assert dto.is_trial is False
        assert dto.traffic_limit == 300
        assert dto.device_limit == 6
        assert dto.tag == "pro"
        assert dto.expire_at == expire
        assert dto.url == "https://panel.example.com/sub/abc"
        assert dto.plan.name == "Pro"
        assert dto.created_at == now

    def test_no_plan_uses_test_snapshot(self):
        expire = datetime(2025, 7, 1, tzinfo=timezone.utc)
        bs = BillingSubscription(ID=1, Status="ACTIVE", Plan=None, ExpireAt=expire)
        dto = billing_subscription_to_dto(bs)

        # Should use PlanSnapshotDto.test() fallback
        assert dto.plan is not None
        assert dto.plan.name != ""

    def test_empty_remna_id_gives_zero_uuid(self):
        expire = datetime(2025, 7, 1, tzinfo=timezone.utc)
        bs = BillingSubscription(ID=1, UserRemnaID="", Status="ACTIVE", ExpireAt=expire)
        dto = billing_subscription_to_dto(bs)

        assert dto.user_remna_id == UUID(int=0)


# ---------------------------------------------------------------------------
# Transaction converter
# ---------------------------------------------------------------------------


class TestBillingTransactionToDto:

    def test_full_conversion(self):
        now = datetime(2025, 6, 1, tzinfo=timezone.utc)
        bt = BillingTransaction(
            ID=5,
            PaymentID="550e8400-e29b-41d4-a716-446655440001",
            UserTelegramID=123456789,
            Status="COMPLETED",
            IsTest=False,
            PurchaseType="NEW",
            GatewayType="TELEGRAM_STARS",
            Pricing=BillingPriceDetails(original_amount="100", discount_percent=10, final_amount="90"),
            Currency="XTR",
            Plan=BillingPlanSnapshot(id=42, name="Pro", type="BOTH", duration=30, traffic_limit_strategy="MONTH"),
            CreatedAt=now,
            UpdatedAt=now,
        )
        dto = billing_transaction_to_dto(bt)

        assert dto.id == 5
        assert dto.payment_id == UUID("550e8400-e29b-41d4-a716-446655440001")
        assert dto.status == TransactionStatus.COMPLETED
        assert dto.is_test is False
        assert dto.purchase_type == PurchaseType.NEW
        assert dto.gateway_type == PaymentGatewayType.TELEGRAM_STARS
        assert dto.pricing.original_amount == Decimal("100")
        assert dto.pricing.discount_percent == 10
        assert dto.pricing.final_amount == Decimal("90")
        assert dto.currency == Currency.XTR
        assert dto.plan.name == "Pro"

    def test_no_pricing_uses_defaults(self):
        bt = BillingTransaction(ID=1, Status="PENDING", Pricing=None)
        dto = billing_transaction_to_dto(bt)

        assert dto.pricing is not None
        assert dto.pricing.discount_percent == 0

    def test_no_plan_uses_test_snapshot(self):
        bt = BillingTransaction(ID=1, Status="PENDING", Plan=None)
        dto = billing_transaction_to_dto(bt)

        assert dto.plan is not None

    def test_empty_payment_id_gives_zero_uuid(self):
        bt = BillingTransaction(ID=1, PaymentID="", Status="PENDING")
        dto = billing_transaction_to_dto(bt)

        assert dto.payment_id == UUID(int=0)


class TestBillingPriceDetailsToDto:

    def test_basic_conversion(self):
        bp = BillingPriceDetails(original_amount="199.50", discount_percent=15, final_amount="169.57")
        dto = billing_price_details_to_dto(bp)

        assert dto.original_amount == Decimal("199.50")
        assert dto.discount_percent == 15
        assert dto.final_amount == Decimal("169.57")


# ---------------------------------------------------------------------------
# User converter
# ---------------------------------------------------------------------------


class TestBillingUserToDto:

    def test_full_conversion(self):
        now = datetime(2025, 1, 1, tzinfo=timezone.utc)
        bu = BillingUser(
            ID=1,
            TelegramID=123456789,
            Username="testuser",
            ReferralCode="REF123",
            Name="Test User",
            Role="USER",
            Language="RU",
            PersonalDiscount=5,
            PurchaseDiscount=10,
            PurchaseDiscountMaxDays=30,
            Points=100,
            Source="organic",
            IsBlocked=False,
            IsBotBlocked=False,
            IsRulesAccepted=True,
            CreatedAt=now,
            UpdatedAt=now,
        )
        dto = billing_user_to_dto(bu)

        assert isinstance(dto, UserDto)
        assert dto.id == 1
        assert dto.telegram_id == 123456789
        assert dto.username == "testuser"
        assert dto.referral_code == "REF123"
        assert dto.name == "Test User"
        assert dto.role == UserRole.USER
        assert dto.personal_discount == 5
        assert dto.purchase_discount == 10
        assert dto.purchase_discount_max_days == 30
        assert dto.points == 100
        assert dto.source == "organic"
        assert dto.is_blocked is False
        assert dto.is_bot_blocked is False
        assert dto.is_rules_accepted is True
        assert dto.created_at == now
        assert dto.updated_at == now

    def test_language_lowercased(self):
        bu = BillingUser(TelegramID=1, Name="Test", Language="RU")
        dto = billing_user_to_dto(bu)

        assert dto.language == "ru"

    def test_language_already_lowercase(self):
        bu = BillingUser(TelegramID=1, Name="Test", Language="en")
        dto = billing_user_to_dto(bu)

        assert dto.language == "en"

    def test_none_language_defaults_to_ru(self):
        bu = BillingUser(TelegramID=1, Name="Test", Language="")
        dto = billing_user_to_dto(bu)

        # (bu.Language or "ru").lower() -> "" is falsy -> "ru"
        assert dto.language == "ru"

    def test_admin_role(self):
        bu = BillingUser(TelegramID=1, Name="Admin", Role="ADMIN")
        dto = billing_user_to_dto(bu)

        assert dto.role == UserRole.ADMIN

    def test_zero_id_maps_to_none(self):
        bu = BillingUser(ID=0, TelegramID=1, Name="Test")
        dto = billing_user_to_dto(bu)

        assert dto.id is None


# ---------------------------------------------------------------------------
# Settings converter
# ---------------------------------------------------------------------------


class TestBillingSettingsToDto:

    def test_full_conversion(self):
        bs = BillingSettings(
            ID=1,
            RulesRequired=True,
            ChannelRequired=False,
            RulesLink="https://example.com/rules",
            ChannelID=-1001234567890,
            ChannelLink="@test_channel",
            AccessMode="PUBLIC",
            PurchasesAllowed=True,
            RegistrationAllowed=True,
            DefaultCurrency="XTR",
            UserNotifications={"expires_in_3_days": True, "expired": False},
            SystemNotifications={"user_registered": True, "subscription": False},
            Referral={
                "Enable": True,
                "Level": 1,
                "AccrualStrategy": "ON_FIRST_PAYMENT",
                "Reward": {"Type": "EXTRA_DAYS", "Strategy": "AMOUNT", "Config": {1: 5}},
            },
        )
        dto = billing_settings_to_dto(bs)

        assert isinstance(dto, SettingsDto)
        assert dto.id == 1
        assert dto.rules_required is True
        assert dto.channel_required is False
        assert dto.rules_link.get_secret_value() == "https://example.com/rules"
        assert dto.channel_id == -1001234567890
        assert dto.channel_link.get_secret_value() == "@test_channel"
        assert dto.access_mode == AccessMode.PUBLIC
        assert dto.purchases_allowed is True
        assert dto.default_currency == Currency.XTR

    def test_user_notifications_mapping(self):
        bs = BillingSettings(
            UserNotifications={"expires_in_3_days": True, "expired": False, "limited": True},
        )
        dto = billing_settings_to_dto(bs)

        assert dto.user_notifications.expires_in_3_days is True
        assert dto.user_notifications.expired is False
        assert dto.user_notifications.limited is True

    def test_system_notifications_mapping(self):
        bs = BillingSettings(
            SystemNotifications={"user_registered": False, "subscription": True, "node_status": False},
        )
        dto = billing_settings_to_dto(bs)

        assert dto.system_notifications.user_registered is False
        assert dto.system_notifications.subscription is True
        assert dto.system_notifications.node_status is False

    def test_referral_settings_mapping(self):
        bs = BillingSettings(
            Referral={
                "Enable": True,
                "Level": 1,
                "AccrualStrategy": "ON_EACH_PAYMENT",
                "Reward": {
                    "Type": "POINTS",
                    "Strategy": "PERCENT",
                    "Config": {"1": 10, "2": 5},
                },
            },
        )
        dto = billing_settings_to_dto(bs)

        assert dto.referral.enable is True
        assert dto.referral.level == ReferralLevel.FIRST
        assert dto.referral.accrual_strategy == ReferralAccrualStrategy.ON_EACH_PAYMENT
        assert dto.referral.reward.type == ReferralRewardType.POINTS
        assert dto.referral.reward.strategy == ReferralRewardStrategy.PERCENT
        assert dto.referral.reward.config[ReferralLevel.FIRST] == 10
        assert dto.referral.reward.config[ReferralLevel.SECOND] == 5

    def test_none_notifications_gives_defaults(self):
        bs = BillingSettings(
            UserNotifications=None,
            SystemNotifications=None,
            Referral=None,
        )
        dto = billing_settings_to_dto(bs)

        # Defaults should be all True
        assert dto.user_notifications.expires_in_3_days is True
        assert dto.system_notifications.user_registered is True
        assert dto.referral.enable is True

    def test_empty_access_mode_defaults(self):
        bs = BillingSettings(AccessMode="", DefaultCurrency="")
        dto = billing_settings_to_dto(bs)

        assert dto.access_mode == AccessMode.PUBLIC
        assert dto.default_currency == Currency.XTR

    def test_referral_lowercase_keys(self):
        """The billing API may return lowercase keys in referral settings."""
        bs = BillingSettings(
            Referral={
                "enable": False,
                "level": 2,
                "accrual_strategy": "ON_FIRST_PAYMENT",
                "reward": {
                    "type": "EXTRA_DAYS",
                    "strategy": "AMOUNT",
                    "config": {"1": 3},
                },
            },
        )
        dto = billing_settings_to_dto(bs)

        assert dto.referral.enable is False
        assert dto.referral.level == ReferralLevel.SECOND
        assert dto.referral.reward.type == ReferralRewardType.EXTRA_DAYS


# ---------------------------------------------------------------------------
# Gateway converter
# ---------------------------------------------------------------------------


class TestBillingGatewayToDto:

    def test_full_conversion(self):
        bg = BillingPaymentGateway(
            ID=3,
            OrderIndex=1,
            Type="PLATEGA",
            Channel="ALL",
            Currency="RUB",
            IsActive=True,
            Settings={"api_key": "secret123"},
        )
        dto = billing_gateway_to_dto(bg)

        assert dto.id == 3
        assert dto.order_index == 1
        assert dto.type == PaymentGatewayType.PLATEGA
        assert dto.channel == GatewayChannel.ALL
        assert dto.currency == Currency.RUB
        assert dto.is_active is True
        # Settings should always be None (secrets not exposed)
        assert dto.settings is None

    def test_empty_type_defaults(self):
        bg = BillingPaymentGateway(ID=1, Type="", Currency="", Channel="")
        dto = billing_gateway_to_dto(bg)

        assert dto.type == PaymentGatewayType.TELEGRAM_STARS
        assert dto.currency == Currency.USD
        assert dto.channel == GatewayChannel.ALL

    def test_bot_channel(self):
        bg = BillingPaymentGateway(ID=1, Type="YOOKASSA", Channel="BOT", Currency="RUB")
        dto = billing_gateway_to_dto(bg)

        assert dto.channel == GatewayChannel.BOT


# ---------------------------------------------------------------------------
# Referral converters
# ---------------------------------------------------------------------------


class TestBillingReferralToDto:

    def test_empty_level_defaults_to_first(self):
        now = datetime(2025, 6, 1, tzinfo=timezone.utc)
        br = BillingReferral(
            ID=7,
            ReferrerTelegramID=111111,
            ReferredTelegramID=222222,
            Level="",
            CreatedAt=now,
            UpdatedAt=now,
        )
        dto = billing_referral_to_dto(br)

        assert dto.id == 7
        assert dto.level == ReferralLevel.FIRST
        assert dto.referrer.telegram_id == 111111
        assert dto.referred.telegram_id == 222222
        assert dto.created_at == now

    def test_stub_users_have_telegram_id(self):
        br = BillingReferral(ID=1, ReferrerTelegramID=111, ReferredTelegramID=222, Level="")
        dto = billing_referral_to_dto(br)

        assert dto.referrer.telegram_id == 111
        assert dto.referred.telegram_id == 222
        assert dto.referrer.name == ""
        assert dto.referred.name == ""

    def test_integer_level_works(self):
        """ReferralLevel is IntEnum; if Level field happens to contain an int, it works."""
        br = BillingReferral(ID=1, ReferrerTelegramID=111, ReferredTelegramID=222, Level="")
        # Manually set Level to int to bypass Pydantic str coercion
        object.__setattr__(br, "Level", 1)
        dto = billing_referral_to_dto(br)

        assert dto.level == ReferralLevel.FIRST


class TestBillingReferralRewardToDto:

    def test_full_conversion(self):
        now = datetime(2025, 6, 1, tzinfo=timezone.utc)
        brr = BillingReferralReward(
            ID=9,
            ReferralID=7,
            UserTelegramID=111111,
            Type="EXTRA_DAYS",
            Amount=5,
            IsIssued=False,
            CreatedAt=now,
            UpdatedAt=now,
        )
        dto = billing_referral_reward_to_dto(brr)

        assert dto.id == 9
        assert dto.type == ReferralRewardType.EXTRA_DAYS
        assert dto.amount == 5
        assert dto.is_issued is False
        assert dto.created_at == now

    def test_points_type(self):
        brr = BillingReferralReward(ID=1, Type="POINTS", Amount=100, IsIssued=True)
        dto = billing_referral_reward_to_dto(brr)

        assert dto.type == ReferralRewardType.POINTS
        assert dto.is_issued is True

    def test_empty_type_defaults(self):
        brr = BillingReferralReward(ID=1, Type="", Amount=0)
        dto = billing_referral_reward_to_dto(brr)

        assert dto.type == ReferralRewardType.EXTRA_DAYS


# ---------------------------------------------------------------------------
# Promocode converter
# ---------------------------------------------------------------------------


class TestBillingPromocodeToDto:

    def test_full_conversion(self):
        now = datetime(2025, 1, 1, tzinfo=timezone.utc)
        bp = BillingPromocode(
            ID=15,
            Code="WELCOME10",
            IsActive=True,
            Availability="ALL",
            RewardType="PERSONAL_DISCOUNT",
            Reward=10,
            Plan=BillingPlanSnapshot(id=42, name="Pro", type="BOTH", duration=30, traffic_limit_strategy="MONTH"),
            PurchaseDiscountMaxDays=30,
            Lifetime=-1,
            MaxActivations=100,
            AllowedTelegramIDs=[111, 222],
            Activations=[
                BillingPromocodeActivation(ID=1, PromocodeID=15, UserTelegramID=111, ActivatedAt=now),
            ],
            CreatedAt=now,
            UpdatedAt=now,
        )
        dto = billing_promocode_to_dto(bp)

        assert dto.id == 15
        assert dto.code == "WELCOME10"
        assert dto.is_active is True
        assert dto.availability == PromocodeAvailability.ALL
        assert dto.reward_type == PromocodeRewardType.PERSONAL_DISCOUNT
        assert dto.reward == 10
        assert dto.plan is not None
        assert dto.plan.name == "Pro"
        assert dto.purchase_discount_max_days == 30
        assert dto.lifetime == -1
        assert dto.max_activations == 100
        assert dto.allowed_telegram_ids == [111, 222]
        assert len(dto.activations) == 1
        assert dto.activations[0].user_telegram_id == 111

    def test_no_plan(self):
        bp = BillingPromocode(ID=1, Code="FREE", Plan=None)
        dto = billing_promocode_to_dto(bp)

        assert dto.plan is None

    def test_no_activations(self):
        bp = BillingPromocode(ID=1, Code="NEW", Activations=None)
        dto = billing_promocode_to_dto(bp)

        assert dto.activations == []


# ---------------------------------------------------------------------------
# Broadcast converters
# ---------------------------------------------------------------------------


class TestBillingBroadcastMessageToDto:

    def test_full_conversion(self):
        bm = BillingBroadcastMessage(
            ID=1,
            BroadcastID=20,
            UserID=111,
            MessageID=999,
            Status="SENT",
        )
        dto = billing_broadcast_message_to_dto(bm)

        assert dto.id == 1
        assert dto.user_id == 111
        assert dto.message_id == 999
        assert dto.status == BroadcastMessageStatus.SENT

    def test_pending_status(self):
        bm = BillingBroadcastMessage(ID=2, UserID=222, Status="PENDING")
        dto = billing_broadcast_message_to_dto(bm)

        assert dto.status == BroadcastMessageStatus.PENDING
        assert dto.message_id is None

    def test_empty_status_defaults(self):
        bm = BillingBroadcastMessage(ID=1, UserID=111, Status="")
        dto = billing_broadcast_message_to_dto(bm)

        assert dto.status == BroadcastMessageStatus.PENDING


class TestBillingBroadcastToDto:

    def test_full_conversion(self):
        now = datetime(2025, 6, 1, tzinfo=timezone.utc)
        bb = BillingBroadcast(
            ID=20,
            TaskID="550e8400-e29b-41d4-a716-446655440002",
            Status="COMPLETED",
            Audience="ALL",
            TotalCount=100,
            SuccessCount=95,
            FailedCount=5,
            Payload={"i18n_key": "ntf-broadcast-test"},
            Messages=[
                BillingBroadcastMessage(ID=1, BroadcastID=20, UserID=111, MessageID=999, Status="SENT"),
            ],
            CreatedAt=now,
            UpdatedAt=now,
        )
        dto = billing_broadcast_to_dto(bb)

        assert dto.id == 20
        assert dto.task_id == UUID("550e8400-e29b-41d4-a716-446655440002")
        assert dto.status == BroadcastStatus.COMPLETED
        assert dto.audience == BroadcastAudience.ALL
        assert dto.total_count == 100
        assert dto.success_count == 95
        assert dto.failed_count == 5
        assert dto.payload.i18n_key == "ntf-broadcast-test"
        assert len(dto.messages) == 1
        assert dto.messages[0].user_id == 111
        assert dto.created_at == now

    def test_no_payload_gives_default(self):
        bb = BillingBroadcast(ID=1, Status="PROCESSING", Payload=None)
        dto = billing_broadcast_to_dto(bb)

        assert dto.payload.i18n_key == "ntf-broadcast-preview"

    def test_no_messages(self):
        bb = BillingBroadcast(ID=1, Status="PROCESSING", Messages=None)
        dto = billing_broadcast_to_dto(bb)

        assert dto.messages == []

    def test_empty_task_id_gives_zero_uuid(self):
        bb = BillingBroadcast(ID=1, TaskID="", Status="PROCESSING")
        dto = billing_broadcast_to_dto(bb)

        assert dto.task_id == UUID(int=0)

    def test_empty_status_defaults(self):
        bb = BillingBroadcast(ID=1, Status="", Audience="")
        dto = billing_broadcast_to_dto(bb)

        assert dto.status == BroadcastStatus.PROCESSING
        assert dto.audience == BroadcastAudience.ALL
