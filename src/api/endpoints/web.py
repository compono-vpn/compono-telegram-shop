import time
from decimal import Decimal
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, EmailStr

from src.core.constants import API_V1
from src.core.enums import PaymentGatewayType
from src.infrastructure.database import UnitOfWork
from src.infrastructure.database.models.sql.web_order import WebOrder
from src.services.payment_gateway import PaymentGatewayService

router = APIRouter(prefix=API_V1 + "/web")

TRIAL_AMOUNT = Decimal("5")
TRIAL_DURATION_DAYS = 3
TRIAL_RETURN_URL = "https://componovps.com/trial/success"
TRIAL_FAILED_URL = "https://componovps.com/trial/failed"


class TrialRequest(BaseModel):
    email: EmailStr


class TrialResponse(BaseModel):
    payment_url: str
    payment_id: str
    timing: dict[str, float] | None = None


class TrialStatusResponse(BaseModel):
    status: str
    subscription_url: str | None = None


@router.post("/trial")
@inject
async def create_trial(
    body: TrialRequest,
    payment_gateway_service: FromDishka[PaymentGatewayService],
    uow: FromDishka[UnitOfWork],
) -> TrialResponse:
    timing: dict[str, float] = {}
    t0 = time.monotonic()

    try:
        gateway_instance = await payment_gateway_service._get_gateway_instance(
            PaymentGatewayType.PLATEGA
        )
    except ValueError:
        logger.error("Platega gateway not configured")
        raise HTTPException(status_code=503, detail="Payment gateway not available")

    timing["gateway_init_ms"] = round((time.monotonic() - t0) * 1000, 1)
    t1 = time.monotonic()

    payment = await gateway_instance.handle_create_payment(
        amount=TRIAL_AMOUNT,
        details="Compono VPS — пробный период 3 дня",
        return_url=TRIAL_RETURN_URL,
        failed_url=TRIAL_FAILED_URL,
    )

    timing["platega_api_ms"] = round((time.monotonic() - t1) * 1000, 1)
    t2 = time.monotonic()

    async with uow:
        await uow.repository.web_orders.create(
            WebOrder(
                email=body.email,
                payment_id=payment.id,
                status="pending",
                amount=TRIAL_AMOUNT,
                plan_duration_days=TRIAL_DURATION_DAYS,
            )
        )

    timing["db_write_ms"] = round((time.monotonic() - t2) * 1000, 1)
    timing["total_ms"] = round((time.monotonic() - t0) * 1000, 1)

    logger.info(
        f"Web trial order created for '{body.email}', payment_id='{payment.id}', timing={timing}"
    )
    return TrialResponse(
        payment_url=str(payment.url), payment_id=str(payment.id), timing=timing
    )


@router.get("/trial/{payment_id}")
@inject
async def get_trial_status(
    payment_id: UUID,
    uow: FromDishka[UnitOfWork],
) -> JSONResponse:
    async with uow:
        order = await uow.repository.web_orders.get_by_payment_id(payment_id)

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return JSONResponse(
        content={"status": order.status, "subscription_url": order.subscription_url},
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )
