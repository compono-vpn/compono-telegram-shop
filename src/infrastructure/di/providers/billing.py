from dishka import Provider, Scope, provide

from src.core.config.app import AppConfig
from src.infrastructure.billing.client import BillingClient


class BillingProvider(Provider):
    scope = Scope.APP

    @provide
    def get_billing_client(self, config: AppConfig) -> BillingClient:
        return BillingClient(config)
