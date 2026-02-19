import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

import orjson
from aiogram import Bot
from fastapi import Request
from httpx import AsyncClient, HTTPStatusError
from loguru import logger

from src.core.config import AppConfig
from src.core.enums import Currency, TransactionStatus
from src.infrastructure.database.models.dto import (
    PaymentGatewayDto,
    PaymentResult,
    PlategaGatewaySettingsDto,
)

from .base import BasePaymentGateway


class PlategaGateway(BasePaymentGateway):
    _client: AsyncClient

    API_BASE = "https://app.platega.io"
    CURRENCY = Currency.RUB

    def __init__(self, gateway: PaymentGatewayDto, bot: Bot, config: AppConfig) -> None:
        super().__init__(gateway, bot, config)

        if not isinstance(self.data.settings, PlategaGatewaySettingsDto):
            raise TypeError(
                f"Invalid settings type: expected {PlategaGatewaySettingsDto.__name__}, "
                f"got {type(self.data.settings).__name__}"
            )

        self._client = self._make_client(
            base_url=self.API_BASE,
            headers={
                "X-MerchantId": self.data.settings.merchant_id,  # type: ignore[dict-item]
                "X-Secret": self.data.settings.api_key.get_secret_value(),  # type: ignore[union-attr]
            },
        )

    async def handle_create_payment(self, amount: Decimal, details: str) -> PaymentResult:
        payment_id = str(uuid.uuid4())
        payload = await self._create_payment_payload(amount, payment_id, details)

        try:
            response = await self._client.post("/api/Transaction/Create", json=payload)
            response.raise_for_status()
            data = orjson.loads(response.content)
            return self._get_payment_data(data, payment_id)

        except HTTPStatusError as exception:
            logger.error(
                f"HTTP error creating payment. "
                f"Status: '{exception.response.status_code}', Body: {exception.response.text}"
            )
            raise
        except (KeyError, orjson.JSONDecodeError) as exception:
            logger.error(f"Failed to parse response. Error: {exception}")
            raise
        except Exception as exception:
            logger.exception(f"An unexpected error occurred while creating payment: {exception}")
            raise

    async def handle_webhook(self, request: Request) -> tuple[UUID, TransactionStatus]:
        logger.debug(f"Received {self.__class__.__name__} webhook request")
        webhook_data = await self._get_webhook_data(request)

        payment_id_str = webhook_data.get("payload")

        if not payment_id_str:
            raise ValueError("Required field 'payload' is missing")

        status = webhook_data.get("status")
        payment_id = UUID(payment_id_str)

        match status:
            case "CONFIRMED":
                transaction_status = TransactionStatus.COMPLETED
            case "CANCELED":
                transaction_status = TransactionStatus.CANCELED
            case _:
                raise ValueError(f"Unsupported status: {status}")

        return payment_id, transaction_status

    async def _create_payment_payload(
        self, amount: Decimal, order_id: str, details: str
    ) -> dict[str, Any]:
        settings: PlategaGatewaySettingsDto = self.data.settings  # type: ignore[assignment]
        return {
            "paymentMethod": settings.payment_method,
            "paymentDetails": {
                "amount": float(amount),
                "currency": self.CURRENCY.value,
            },
            "description": details,
            "return": await self._get_bot_redirect_url(),
            "failedUrl": await self._get_bot_redirect_url(),
            "callbackUrl": self.config.get_webhook(self.data.type),
            "payload": order_id,
        }

    def _get_payment_data(self, data: dict[str, Any], order_id: str) -> PaymentResult:
        redirect_url = data.get("redirect")

        if not redirect_url:
            raise KeyError("Invalid response from API: missing 'redirect'")

        return PaymentResult(id=UUID(order_id), url=str(redirect_url))
