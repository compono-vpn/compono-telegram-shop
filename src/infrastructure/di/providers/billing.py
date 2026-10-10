from dishka import Provider, Scope, provide

from src.core.config import AppConfig
from src.infrastructure.billing import BillingClient


class BillingProvider(Provider):
    scope = Scope.APP

    @provide
    def billing_client(self, config: AppConfig) -> BillingClient:
        return BillingClient(
            base_url=config.api_url,
            internal_secret=config.api_internal_secret.get_secret_value(),
            direct_base_url=config.billing_url,
            direct_internal_secret=config.billing_internal_secret.get_secret_value(),
        )
