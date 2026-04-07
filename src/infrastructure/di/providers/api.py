from dishka import Provider, Scope, provide

from src.core.config import AppConfig
from src.infrastructure.api import ApiClient


class ApiProvider(Provider):
    scope = Scope.APP

    @provide
    def api_client(self, config: AppConfig) -> ApiClient:
        return ApiClient(
            base_url=config.api_url,
            internal_secret=config.api_internal_secret.get_secret_value(),
        )
