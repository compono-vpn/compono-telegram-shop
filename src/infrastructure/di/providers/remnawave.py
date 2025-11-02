from dishka import Provider, Scope, provide
from httpx import AsyncClient, Timeout
from loguru import logger
from remnawave import RemnawaveSDK

from src.core.config import AppConfig


class RemnawaveProvider(Provider):
    scope = Scope.APP

    @provide
    def get_remnawave(self, config: AppConfig) -> RemnawaveSDK:
        logger.debug("[REMNAWAVE] Initializing RemnawaveSDK")

        # Oh, what is all this garbage, what's the point???

        client = AsyncClient(
            base_url=config.remnawave.url.get_secret_value() + "/api",
            headers={
                "Authorization": f"Bearer {config.remnawave.token.get_secret_value()}",
                "X-Api-Key": config.remnawave.caddy_token.get_secret_value(),
                "x-forwarded-proto": "https",
                "x-forwarded-for": "127.0.0.1",
            },
            verify=True,
            timeout=Timeout(
                connect=15.0,
                read=25.0,
                write=10.0,
                pool=5.0,
            ),
        )

        return RemnawaveSDK(client)
