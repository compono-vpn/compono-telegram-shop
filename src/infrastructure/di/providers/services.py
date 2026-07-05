from dishka import Provider, Scope, provide
from redis.asyncio import Redis

from src.core.config import AppConfig
from src.services.access import AccessService
from src.services.channel_incentive import ChannelIncentiveService
from src.services.command import CommandService
from src.services.experiment import ExperimentService
from src.services.loyalty_reward import LoyaltyRewardService
from src.services.notification import NotificationService
from src.services.payment_gateway import PaymentGatewayService
from src.services.plan import PlanService
from src.services.referral import ReferralService
from src.services.remnawave import RemnawaveService
from src.services.settings import SettingsService
from src.services.subscription import SubscriptionService
from src.services.transaction import TransactionService
from src.services.user import UserService
from src.services.webhook import WebhookService


class ServicesProvider(Provider):
    scope = Scope.APP

    command_service = provide(source=CommandService)

    @provide(scope=Scope.REQUEST)
    def get_experiment_service(self, config: AppConfig, redis_client: Redis) -> ExperimentService:
        return ExperimentService(config=config, redis_client=redis_client)

    access_service = provide(source=AccessService, scope=Scope.REQUEST)
    notification_service = provide(source=NotificationService, scope=Scope.REQUEST)
    plan_service = provide(source=PlanService, scope=Scope.REQUEST)
    remnawave_service = provide(source=RemnawaveService, scope=Scope.REQUEST)
    subscription_service = provide(source=SubscriptionService, scope=Scope.REQUEST)
    user_service = provide(source=UserService, scope=Scope.REQUEST)
    webhook_service = provide(source=WebhookService)
    settings_service = provide(source=SettingsService, scope=Scope.REQUEST)
    payment_gateway_service = provide(source=PaymentGatewayService, scope=Scope.REQUEST)
    transaction_service = provide(
        source=TransactionService, scope=Scope.REQUEST
    )  # uses BillingClient (HTTP API)
    referral_service = provide(source=ReferralService, scope=Scope.REQUEST)
    channel_incentive_service = provide(source=ChannelIncentiveService, scope=Scope.REQUEST)
    loyalty_reward_service = provide(source=LoyaltyRewardService, scope=Scope.REQUEST)
