from dishka import Provider, Scope, provide

from src.core.config import AppConfig
from src.infrastructure.api import ApiIdentityClient


class ApiIdentityProvider(Provider):
    scope = Scope.APP

    @provide
    def api_identity_client(self, config: AppConfig) -> ApiIdentityClient:
        return ApiIdentityClient(
            base_url=config.api_url,
            internal_secret=config.api_internal_secret.get_secret_value(),
        )
