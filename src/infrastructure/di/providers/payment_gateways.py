from __future__ import annotations

from typing import Type

from aiogram import Bot
from dishka import Provider, Scope, provide
from loguru import logger

from src.core.config import AppConfig
from src.core.enums import GatewayChannel, PaymentGatewayType
from src.infrastructure.database.models.dto import PaymentGatewayDto
from src.infrastructure.payment_gateways import (
    BasePaymentGateway,
    CryptomusGateway,
    HeleketGateway,
    PaymentGatewayFactory,
    PlategaGateway,
    TelegramStarsGateway,
    YookassaGateway,
    YoomoneyGateway,
)

GATEWAY_MAP: dict[PaymentGatewayType, Type[BasePaymentGateway]] = {
    PaymentGatewayType.TELEGRAM_STARS: TelegramStarsGateway,
    PaymentGatewayType.YOOKASSA: YookassaGateway,
    PaymentGatewayType.YOOMONEY: YoomoneyGateway,
    PaymentGatewayType.CRYPTOMUS: CryptomusGateway,
    PaymentGatewayType.HELEKET: HeleketGateway,
    PaymentGatewayType.PLATEGA: PlategaGateway,
}


class PaymentGatewaysProvider(Provider):
    scope = Scope.APP
    _cached_gateways: dict[tuple[PaymentGatewayType, GatewayChannel], BasePaymentGateway] = {}

    @provide()
    def get_gateway_factory(self, bot: Bot, config: AppConfig) -> PaymentGatewayFactory:
        def create_gateway(gateway: PaymentGatewayDto) -> BasePaymentGateway:
            cache_key = (gateway.type, gateway.channel)

            if cache_key in self._cached_gateways:
                cached_gateway = self._cached_gateways[cache_key]

                if cached_gateway.data != gateway:
                    logger.warning(
                        f"Gateway '{gateway.type}' channel='{gateway.channel}' data changed. Re-initializing instance"
                    )
                    del self._cached_gateways[cache_key]

            if cache_key not in self._cached_gateways:
                gateway_instance = GATEWAY_MAP.get(gateway.type)

                if not gateway_instance:
                    raise ValueError(f"Unknown gateway type '{gateway.type}'")

                self._cached_gateways[cache_key] = gateway_instance(
                    gateway=gateway, bot=bot, config=config
                )
                logger.debug(f"Initialized new gateway '{gateway.type}' channel='{gateway.channel}' instance")

            return self._cached_gateways[cache_key]

        return create_gateway
