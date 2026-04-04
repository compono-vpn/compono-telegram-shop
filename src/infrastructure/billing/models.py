"""Response models for the compono-billing Go service.

The Go service serializes domain types using Go's default JSON encoding
(PascalCase field names, no json tags). These Pydantic models map those
responses so the Python bot can consume them.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

# --- Plans ---


class BillingPlanPrice(BaseModel):
    """Maps domain.PlanPrice from billing API."""

    ID: int = 0
    DurationID: int = 0
    Currency: str = ""
    Price: str = "0"


class BillingPlanDuration(BaseModel):
    """Maps domain.PlanDuration from billing API."""

    ID: int = 0
    PlanID: int = 0
    Days: int = 0
    Prices: list[BillingPlanPrice] = Field(default_factory=list)


class BillingPlan(BaseModel):
    """Maps domain.Plan from billing API."""

    ID: int = 0
    OrderIndex: int = 0
    IsActive: bool = True
    Type: str = ""
    Availability: str = ""
    Name: str = ""
    Description: Optional[str] = None
    Tag: Optional[str] = None
    TrafficLimit: int = 0
    DeviceLimit: int = 0
    TrafficLimitStrategy: str = ""
    AllowedUserIDs: Optional[list[int]] = None
    InternalSquads: Optional[list[str]] = None
    ExternalSquad: Optional[str] = None
    Durations: list[BillingPlanDuration] = Field(default_factory=list)
    CreatedAt: Optional[datetime] = None
    UpdatedAt: Optional[datetime] = None


class BillingPlanSnapshot(BaseModel):
    """Maps domain.PlanSnapshot from billing API (uses explicit json tags)."""

    id: int = 0
    name: str = ""
    tag: Optional[str] = None
    type: str = ""
    traffic_limit: int = 0
    device_limit: int = 0
    duration: int = 0
    traffic_limit_strategy: str = ""
    internal_squads: Optional[list[str]] = None
    external_squad: Optional[str] = None


# --- Users ---


class BillingUser(BaseModel):
    """Maps domain.User from billing API."""

    ID: int = 0
    TelegramID: int = 0
    Username: Optional[str] = None
    ReferralCode: str = ""
    Name: str = ""
    Role: str = ""
    Language: str = ""
    PersonalDiscount: int = 0
    PurchaseDiscount: int = 0
    PurchaseDiscountMaxDays: int = 0
    Points: int = 0
    Source: Optional[str] = None
    IsBlocked: bool = False
    IsBotBlocked: bool = False
    IsRulesAccepted: bool = False
    CurrentSubscriptionID: Optional[int] = None
    CreatedAt: Optional[datetime] = None
    UpdatedAt: Optional[datetime] = None


# --- Subscriptions ---


class BillingSubscription(BaseModel):
    """Maps domain.Subscription from billing API."""

    ID: int = 0
    UserRemnaID: str = ""
    UserTelegramID: int = 0
    Status: str = ""
    IsTrial: bool = False
    TrafficLimit: int = 0
    DeviceLimit: int = 0
    TrafficLimitStrategy: str = ""
    Tag: Optional[str] = None
    InternalSquads: Optional[list[str]] = None
    ExternalSquad: Optional[str] = None
    ExpireAt: Optional[datetime] = None
    URL: str = ""
    Plan: Optional[BillingPlanSnapshot] = None
    CreatedAt: Optional[datetime] = None
    UpdatedAt: Optional[datetime] = None


# --- Transactions ---


class BillingPriceDetails(BaseModel):
    """Maps domain.PriceDetails from billing API (uses explicit json tags)."""

    original_amount: str = "0"
    discount_percent: int = 0
    final_amount: str = "0"


class BillingTransaction(BaseModel):
    """Maps domain.Transaction from billing API."""

    ID: int = 0
    PaymentID: str = ""
    UserTelegramID: int = 0
    Status: str = ""
    IsTest: bool = False
    PurchaseType: str = ""
    GatewayType: str = ""
    Pricing: Optional[BillingPriceDetails] = None
    Currency: str = ""
    Plan: Optional[BillingPlanSnapshot] = None
    CreatedAt: Optional[datetime] = None
    UpdatedAt: Optional[datetime] = None


# --- Promocodes ---


class BillingPromocodeActivation(BaseModel):
    """Maps domain.PromocodeActivation from billing API."""

    ID: int = 0
    PromocodeID: int = 0
    UserTelegramID: int = 0
    ActivatedAt: Optional[datetime] = None


class BillingPromocode(BaseModel):
    """Maps domain.Promocode from billing API."""

    ID: int = 0
    Code: str = ""
    IsActive: bool = True
    Availability: str = ""
    RewardType: str = ""
    Reward: Optional[int] = None
    Plan: Optional[BillingPlanSnapshot] = None
    PurchaseDiscountMaxDays: Optional[int] = None
    Lifetime: int = -1
    MaxActivations: int = -1
    AllowedTelegramIDs: Optional[list[int]] = None
    Activations: Optional[list[BillingPromocodeActivation]] = Field(default_factory=list)
    CreatedAt: Optional[datetime] = None
    UpdatedAt: Optional[datetime] = None


# --- Settings ---


class BillingSettings(BaseModel):
    """Maps domain.Settings from billing API."""

    ID: int = 0
    RulesRequired: bool = False
    ChannelRequired: bool = False
    RulesLink: str = ""
    ChannelID: Optional[int] = None
    ChannelLink: str = ""
    AccessMode: str = ""
    PurchasesAllowed: bool = True
    RegistrationAllowed: bool = True
    DefaultCurrency: str = ""
    UserNotifications: Optional[Any] = None
    SystemNotifications: Optional[Any] = None
    Referral: Optional[Any] = None


# --- Payment Gateways ---


class BillingPaymentGateway(BaseModel):
    """Maps domain.PaymentGateway from billing API."""

    ID: int = 0
    OrderIndex: int = 0
    Type: str = ""
    Channel: str = "ALL"
    Currency: str = ""
    IsActive: bool = True
    Settings: Optional[Any] = None


class BillingPaymentResult(BaseModel):
    """Maps domain.PaymentResult from billing API."""

    ID: str = ""
    URL: Optional[str] = None


# --- Referrals ---


class BillingReferralInfo(BaseModel):
    """Maps the referral info response from billing API."""

    referrer_telegram_id: Optional[int] = None
    referral_code: str = ""
    referrals_count: int = 0
    rewards: list[Any] = Field(default_factory=list)


class BillingReferral(BaseModel):
    """Maps domain.Referral from billing API (PascalCase, no json tags)."""

    ID: int = 0
    ReferrerTelegramID: int = 0
    ReferredTelegramID: int = 0
    Level: str = ""
    CreatedAt: Optional[datetime] = None
    UpdatedAt: Optional[datetime] = None


class BillingReferralReward(BaseModel):
    """Maps domain.ReferralReward from billing API (PascalCase, no json tags)."""

    ID: int = 0
    ReferralID: int = 0
    UserTelegramID: int = 0
    Type: str = ""
    Amount: int = 0
    IsIssued: bool = False
    CreatedAt: Optional[datetime] = None
    UpdatedAt: Optional[datetime] = None


# --- Statistics ---


class BillingStatistics(BaseModel):
    """Maps StatisticsResult from billing API."""

    total_users: int = 0
    total_subscriptions: int = 0
    total_revenue: str = "0"
    active_subscriptions: int = 0
    trial_users: int = 0
    today_transactions: int = 0


# --- Web Orders ---


class BillingWebOrder(BaseModel):
    """Maps domain.WebOrder from billing API."""

    ID: int = 0
    PaymentID: str = ""
    ShortID: str = ""
    Email: Optional[str] = None
    Status: str = ""
    IsTrial: bool = False
    PlanDurationDays: int = 0
    PlanSnapshot: Optional[dict[str, Any]] = None
    SubscriptionURL: Optional[str] = None
    ClaimedByTelegramID: Optional[int] = None
    CustomerID: Optional[int] = None
    CreatedAt: Optional[datetime] = None
    UpdatedAt: Optional[datetime] = None


class BillingWebOrderResult(BaseModel):
    """Maps the web order claim response."""

    status: str = ""
    order: Optional[BillingWebOrder] = None


# --- Customers ---


class BillingCustomer(BaseModel):
    """Maps domain.Customer from billing API."""

    ID: int = 0
    TelegramID: Optional[int] = None
    Email: Optional[str] = None
    RemnaUserUUID: Optional[str] = None
    RemnaUsername: Optional[str] = None
    SubscriptionURL: Optional[str] = None
    CreatedAt: Optional[datetime] = None
    UpdatedAt: Optional[datetime] = None


# --- Portal ---


class BillingPortalLookup(BaseModel):
    """Maps the portal lookup response."""

    has_subscription: bool = False
    subscription_url: Optional[str] = None
    plan_name: Optional[str] = None


# --- TG Proxies ---


class BillingTGProxy(BaseModel):
    """Maps domain.TGProxy from billing API (lowercase JSON keys)."""

    model_config = ConfigDict(populate_by_name=True)

    id: int = Field(0, alias="id")
    server: str = Field("", alias="server")
    port: int = Field(0, alias="port")
    secret: str = Field("", alias="secret")
    link: str = Field("", alias="link")
