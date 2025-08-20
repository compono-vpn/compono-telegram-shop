from abc import ABC, abstractmethod

from fastapi import Request, Response


class PaymentGateway(ABC):
    @abstractmethod
    async def create_payment(self, amount: int) -> str:
        pass

    @abstractmethod
    async def handle_webhook(self, request: Request) -> Response:
        pass
