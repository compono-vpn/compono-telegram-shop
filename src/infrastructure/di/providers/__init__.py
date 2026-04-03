from dishka import Provider
from dishka.integrations.aiogram import AiogramProvider

from .billing import BillingProvider
from .bot import BotProvider
from .config import ConfigProvider
from .i18n import I18nProvider
from .payment_gateways import PaymentGatewaysProvider
from .redis import RedisProvider
from .remnawave import RemnawaveProvider
from .services import ServicesProvider


def get_providers() -> list[Provider]:
    return [
        AiogramProvider(),
        BillingProvider(),
        BotProvider(),
        ConfigProvider(),
        I18nProvider(),
        RedisProvider(),
        RemnawaveProvider(),
        ServicesProvider(),
        PaymentGatewaysProvider(),
    ]
