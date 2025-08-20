from fastapi import Request, Response, status

from .base import PaymentGateway


class YookassaGateway(PaymentGateway):
    async def create_payment(self, amount: int) -> str:
        # TODO: Use Yookassa API
        return "https://yookassa.ru/"

    async def handle_webhook(self, request: Request) -> Response:
        body = await request.json()
        # TODO: validate signature
        print("Yookassa webhook:", body)

        return Response(status_code=status.HTTP_200_OK)
