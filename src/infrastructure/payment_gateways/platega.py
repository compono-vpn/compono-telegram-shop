from decimal import Decimal
from typing import Any
from uuid import UUID

import hmac
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
        payload = await self._create_payment_payload(amount, details)

        try:
            response = await self._client.post("/transaction/process", json=payload)
            response.raise_for_status()
            data = orjson.loads(response.content)
            return self._get_payment_data(data)

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

        if not self._verify_webhook(request):
            raise PermissionError("Webhook verification failed")

        webhook_data = await self._get_webhook_data(request)

        payment_id_str = webhook_data.get("id")

        if not payment_id_str:
            raise ValueError("Required field 'id' is missing")

        status = webhook_data.get("status")
        payment_id = UUID(payment_id_str)

        match status:
            case "CONFIRMED":
                transaction_status = TransactionStatus.COMPLETED
            case "CANCELED":
                transaction_status = TransactionStatus.CANCELED
            case "CHARGEBACK":
                transaction_status = TransactionStatus.REFUNDED
            case _:
                raise ValueError(f"Unsupported status: {status}")

        return payment_id, transaction_status

    async def _create_payment_payload(self, amount: Decimal, details: str) -> dict[str, Any]:
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
        }

    def _verify_webhook(self, request: Request) -> bool:
        settings: PlategaGatewaySettingsDto = self.data.settings  # type: ignore[assignment]

        merchant_id = request.headers.get("X-MerchantId", "")
        secret = request.headers.get("X-Secret", "")

        merchant_ok = hmac.compare_digest(merchant_id, settings.merchant_id or "")
        secret_ok = hmac.compare_digest(secret, settings.api_key.get_secret_value() if settings.api_key else "")  # type: ignore[arg-type]

        if not (merchant_ok and secret_ok):
            logger.warning("Platega webhook verification failed: credentials mismatch")
            return False

        return True

    def _get_payment_data(self, data: dict[str, Any]) -> PaymentResult:
        transaction_id = data.get("transactionId")

        if not transaction_id:
            raise KeyError("Invalid response from API: missing 'transactionId'")

        redirect_url = data.get("redirect")

        if not redirect_url:
            raise KeyError("Invalid response from API: missing 'redirect'")

        return PaymentResult(id=UUID(transaction_id), url=str(redirect_url))
