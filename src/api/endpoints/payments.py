from fastapi import APIRouter, Request

from src.core.constants import YOOKASSA_WEBHOOK_PATH
from src.payment_gateways.yookassa import YookassaGateway

router = APIRouter()


@router.post(YOOKASSA_WEBHOOK_PATH)
async def yookassa_webhook(request: Request):
    return await YookassaGateway().handle_webhook(request)
