from remnawave_api import RemnawaveSDK

from app.core.config import AppConfig


# TODO: Add logging and verify authentication for the Remnawave SDK
def create_remnawave(config: AppConfig) -> RemnawaveSDK:
    return RemnawaveSDK(
        base_url=config.remna.url.get_secret_value(),
        token=config.remna.token.get_secret_value(),
    )
