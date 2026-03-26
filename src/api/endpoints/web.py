import time
import uuid
from decimal import ROUND_DOWN, Decimal
from urllib.parse import urlparse
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from loguru import logger
from pydantic import BaseModel, EmailStr

from src.core.config import AppConfig
from src.core.constants import API_V1
from src.core.enums import (
    Currency,
    PaymentGatewayType,
    PlanAvailability,
    PromocodeAvailability,
    PromocodeRewardType,
    TransactionStatus,
)
from src.infrastructure.database import UnitOfWork
from src.infrastructure.database.models.dto import PromocodeDto
from src.infrastructure.database.models.sql.web_order import WebOrder
from src.infrastructure.taskiq.tasks.payments import handle_web_order_task
from src.services.payment_gateway import PaymentGatewayService

router = APIRouter(prefix=API_V1 + "/web")

TRIAL_AMOUNT = Decimal("5")
TRIAL_DURATION_DAYS = 3
TRIAL_RETURN_URL = "https://componovps.com/trial/success"
TRIAL_FAILED_URL = "https://componovps.com/trial/failed"

CURRENCY_TO_GATEWAY = {
    Currency.RUB: PaymentGatewayType.PLATEGA,
    Currency.USD: PaymentGatewayType.CRYPTOMUS,
}


class TrialRequest(BaseModel):
    email: EmailStr


class TrialResponse(BaseModel):
    payment_url: str
    payment_id: str
    timing: dict[str, float] | None = None


class TrialStatusResponse(BaseModel):
    status: str
    subscription_url: str | None = None


class PromocodeValidateRequest(BaseModel):
    code: str
    plan_id: int
    duration_days: int
    currency: Currency


class PromocodeValidateResponse(BaseModel):
    valid: bool
    discount_percent: int = 0
    original_amount: float = 0
    final_amount: float = 0
    error: str | None = None


class PurchaseRequest(BaseModel):
    email: EmailStr
    plan_id: int
    duration_days: int
    currency: Currency
    lang: str = "en"
    return_url: str | None = None
    failed_url: str | None = None
    promocode: str | None = None


class PurchaseResponse(BaseModel):
    payment_url: str
    payment_id: str


class PlanDurationResponse(BaseModel):
    days: int
    prices: dict[str, float]


class PlanResponse(BaseModel):
    id: int
    name: str
    type: str
    traffic_limit: int
    device_limit: int
    durations: list[PlanDurationResponse]


class PlansResponse(BaseModel):
    plans: list[PlanResponse]


WEB_DISCOUNT_REWARD_TYPES = {PromocodeRewardType.PERSONAL_DISCOUNT, PromocodeRewardType.PURCHASE_DISCOUNT}
WEB_DISCOUNT_AVAILABILITIES = {PromocodeAvailability.ALL, PromocodeAvailability.NEW}


def _apply_currency_rules(amount: Decimal, currency: Currency) -> Decimal:
    match currency:
        case Currency.RUB:
            amount = amount.to_integral_value(rounding=ROUND_DOWN)
            min_amount = Decimal(1)
        case _:
            amount = amount.quantize(Decimal("0.01"))
            min_amount = Decimal("0.01")

    if amount < min_amount:
        amount = min_amount

    return amount


async def _validate_promocode_for_web(
    uow: UnitOfWork,
    code: str,
    plan_id: int,
    duration_days: int,
    currency: Currency,
) -> PromocodeValidateResponse:
    """Validate a promocode for web purchase, returning price details."""
    normalized = code.strip().upper()

    async with uow:
        db_promocode = await uow.repository.promocodes.get_by_code(normalized)

    if not db_promocode:
        return PromocodeValidateResponse(valid=False, error="Code not found")

    promocode = PromocodeDto.from_model(db_promocode)

    if not promocode or not promocode.is_active:
        return PromocodeValidateResponse(valid=False, error="Code not found")

    if promocode.is_expired:
        return PromocodeValidateResponse(valid=False, error="Code expired")

    # Check depletion: count both PromocodeActivation records and web orders
    if promocode.max_activations is not None and promocode.max_activations >= 0:
        async with uow:
            web_order_count = await uow.repository.web_orders.count_by_promocode_id(promocode.id)
        total_activations = len(promocode.activations) + web_order_count
        if total_activations >= promocode.max_activations:
            return PromocodeValidateResponse(valid=False, error="Code fully used")

    if promocode.reward_type not in WEB_DISCOUNT_REWARD_TYPES:
        return PromocodeValidateResponse(valid=False, error="Code not applicable")

    if promocode.availability not in WEB_DISCOUNT_AVAILABILITIES:
        return PromocodeValidateResponse(valid=False, error="Code not applicable")

    # For PURCHASE_DISCOUNT: check max_days constraint
    if promocode.reward_type == PromocodeRewardType.PURCHASE_DISCOUNT:
        max_days = promocode.purchase_discount_max_days or 0
        if max_days > 0 and duration_days > max_days:
            return PromocodeValidateResponse(
                valid=False, error="Code not applicable for this duration"
            )

    # Look up plan and price
    async with uow:
        db_plan = await uow.repository.plans.get(plan_id)

    if not db_plan or not db_plan.is_active:
        return PromocodeValidateResponse(valid=False, error="Plan not found")

    duration = next((d for d in db_plan.durations if d.days == duration_days), None)
    if not duration:
        return PromocodeValidateResponse(valid=False, error="Duration not available")

    price_obj = next((p for p in duration.prices if p.currency == currency), None)
    if not price_obj:
        return PromocodeValidateResponse(valid=False, error="Currency not available")

    original_amount = price_obj.price
    discount_percent = min(promocode.reward or 0, 100)

    if discount_percent >= 100:
        return PromocodeValidateResponse(
            valid=True,
            discount_percent=100,
            original_amount=float(original_amount),
            final_amount=0,
        )

    discounted = original_amount * (Decimal(100) - Decimal(discount_percent)) / Decimal(100)
    final_amount = _apply_currency_rules(discounted, currency)

    if final_amount == original_amount:
        discount_percent = 0

    return PromocodeValidateResponse(
        valid=True,
        discount_percent=discount_percent,
        original_amount=float(original_amount),
        final_amount=float(final_amount),
    )


@router.post("/promocode/validate")
@inject
async def validate_promocode(
    body: PromocodeValidateRequest,
    uow: FromDishka[UnitOfWork],
) -> PromocodeValidateResponse:
    return await _validate_promocode_for_web(
        uow=uow,
        code=body.code,
        plan_id=body.plan_id,
        duration_days=body.duration_days,
        currency=body.currency,
    )


@router.get("/plans")
@inject
async def get_plans(
    uow: FromDishka[UnitOfWork],
) -> PlansResponse:
    async with uow:
        db_plans = await uow.repository.plans.filter_active(is_active=True)

    plans = []
    for plan in db_plans:
        if plan.availability not in (PlanAvailability.ALL,):
            continue

        durations = []
        for duration in plan.durations:
            prices = {}
            for price in duration.prices:
                prices[price.currency.value] = float(price.price)
            durations.append(PlanDurationResponse(days=duration.days, prices=prices))

        plans.append(
            PlanResponse(
                id=plan.id,
                name=plan.name,
                type=plan.type.value,
                traffic_limit=plan.traffic_limit,
                device_limit=plan.device_limit,
                durations=durations,
            )
        )

    return PlansResponse(plans=plans)


@router.post("/purchase")
@inject
async def create_purchase(
    body: PurchaseRequest,
    payment_gateway_service: FromDishka[PaymentGatewayService],
    uow: FromDishka[UnitOfWork],
    config: FromDishka[AppConfig],
) -> PurchaseResponse:
    # Look up plan
    async with uow:
        db_plan = await uow.repository.plans.get(body.plan_id)

    if not db_plan or not db_plan.is_active:
        raise HTTPException(status_code=404, detail="Plan not found or inactive")

    if db_plan.availability not in (PlanAvailability.ALL,):
        raise HTTPException(status_code=400, detail="Plan not available for web purchase")

    # Find the requested duration
    duration = next((d for d in db_plan.durations if d.days == body.duration_days), None)
    if not duration:
        raise HTTPException(status_code=400, detail="Duration not available for this plan")

    # Find the price for the requested currency
    price_obj = next((p for p in duration.prices if p.currency == body.currency), None)
    if not price_obj:
        raise HTTPException(status_code=400, detail="Currency not available for this duration")

    amount = price_obj.price
    promocode_id: int | None = None
    discount_percent: int | None = None

    # Apply promocode discount if provided
    if body.promocode:
        promo_result = await _validate_promocode_for_web(
            uow=uow,
            code=body.promocode,
            plan_id=body.plan_id,
            duration_days=body.duration_days,
            currency=body.currency,
        )
        if not promo_result.valid:
            raise HTTPException(status_code=400, detail=promo_result.error or "Invalid promocode")

        if promo_result.discount_percent > 0:
            amount = Decimal(str(promo_result.final_amount))
            discount_percent = promo_result.discount_percent

            # Resolve promocode_id for the order record
            normalized_code = body.promocode.strip().upper()
            async with uow:
                db_promo = await uow.repository.promocodes.get_by_code(normalized_code)
            if db_promo:
                promocode_id = db_promo.id

    # Build plan snapshot for order record
    plan_snapshot = {
        "id": db_plan.id,
        "name": db_plan.name,
        "type": db_plan.type.value,
        "traffic_limit": db_plan.traffic_limit,
        "device_limit": db_plan.device_limit,
        "duration_days": body.duration_days,
        "traffic_limit_strategy": db_plan.traffic_limit_strategy.value,
        "internal_squads": [str(s) for s in (db_plan.internal_squads or [])],
        "external_squad": str(db_plan.external_squad) if db_plan.external_squad else None,
    }

    if discount_percent:
        plan_snapshot["promocode_code"] = body.promocode.strip().upper()
        plan_snapshot["discount_percent"] = discount_percent

    # Handle free purchase (100% discount)
    if amount <= 0:
        free_payment_id = uuid.uuid4()

        async with uow:
            await uow.repository.web_orders.create(
                WebOrder(
                    email=body.email,
                    payment_id=free_payment_id,
                    status="pending",
                    amount=Decimal(0),
                    plan_duration_days=body.duration_days,
                    plan_id=body.plan_id,
                    plan_snapshot=plan_snapshot,
                    gateway_type=None,
                    currency=body.currency.value,
                    is_trial=False,
                    promocode_id=promocode_id,
                    discount_percent=discount_percent,
                )
            )

        # Immediately enqueue completion task
        await handle_web_order_task.kiq(free_payment_id, TransactionStatus.COMPLETED)

        logger.info(
            f"Free web purchase (100% discount) for '{body.email}', "
            f"plan='{db_plan.name}', duration={body.duration_days}d, "
            f"payment_id='{free_payment_id}'"
        )
        return PurchaseResponse(payment_url="", payment_id=str(free_payment_id))

    # Determine gateway from currency
    gateway_type = CURRENCY_TO_GATEWAY.get(body.currency)
    if not gateway_type:
        raise HTTPException(status_code=400, detail="Unsupported currency")

    try:
        gateway_instance = await payment_gateway_service._get_gateway_instance(gateway_type)
    except ValueError:
        logger.error(f"Gateway '{gateway_type}' not configured")
        raise HTTPException(status_code=503, detail="Payment gateway not available")

    # Use client-provided return URLs if they come from a trusted origin
    allowed_origins = config.hydra_allowed_origins
    def validate_return_url(url: str | None, default: str) -> str:
        if not url:
            return default
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        return url if origin in allowed_origins else default

    default_origin = f"https://{config.hydra_primary_domain}"
    return_url = validate_return_url(
        body.return_url, f"{default_origin}/{body.lang}/purchase/success"
    )
    failed_url = validate_return_url(
        body.failed_url, f"{default_origin}/{body.lang}/purchase/failed"
    )

    details = f"Compono VPN — {db_plan.name} ({body.duration_days} days)"

    # Platega supports return_url/failed_url; Cryptomus does not
    if gateway_type == PaymentGatewayType.PLATEGA:
        payment = await gateway_instance.handle_create_payment(
            amount=amount,
            details=details,
            return_url=return_url,
            failed_url=failed_url,
        )
    else:
        payment = await gateway_instance.handle_create_payment(
            amount=amount,
            details=details,
        )

    async with uow:
        await uow.repository.web_orders.create(
            WebOrder(
                email=body.email,
                payment_id=payment.id,
                status="pending",
                amount=amount,
                plan_duration_days=body.duration_days,
                plan_id=body.plan_id,
                plan_snapshot=plan_snapshot,
                gateway_type=gateway_type.value,
                currency=body.currency.value,
                is_trial=False,
                promocode_id=promocode_id,
                discount_percent=discount_percent,
            )
        )

    logger.info(
        f"Web purchase order created for '{body.email}', "
        f"plan='{db_plan.name}', duration={body.duration_days}d, "
        f"amount={amount} {body.currency.value}, payment_id='{payment.id}'"
        f"{f', promocode_id={promocode_id}, discount={discount_percent}%' if promocode_id else ''}"
    )
    return PurchaseResponse(payment_url=str(payment.url), payment_id=str(payment.id))


@router.get("/purchase/{payment_id}")
@inject
async def get_purchase_status(
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


@router.post("/trial")
@inject
async def create_trial(
    body: TrialRequest,
    payment_gateway_service: FromDishka[PaymentGatewayService],
    uow: FromDishka[UnitOfWork],
) -> TrialResponse:
    # One trial per unique email
    async with uow:
        already_used = await uow.repository.web_orders.exists_by_email(body.email)
    if already_used:
        raise HTTPException(status_code=409, detail="Trial already used for this email")

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


# --- Portal: subscription lookup by email ---


class PortalLookupRequest(BaseModel):
    email: EmailStr


@router.post("/portal/lookup")
@inject
async def portal_lookup(
    body: PortalLookupRequest,
    uow: FromDishka[UnitOfWork],
) -> JSONResponse:
    async with uow:
        order = await uow.repository.web_orders.get_latest_completed_by_email(body.email)

    if not order or not order.subscription_url:
        raise HTTPException(status_code=404, detail="NOT_FOUND")

    return JSONResponse(content={"subscription_url": order.subscription_url})


# --- Mirrors page: branded HTML showing active/blocked domains ---

BLOCKED_DOMAINS = ["componovpn.com"]

MIRRORS_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Compono VPN — Зеркала / Mirrors</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700;900&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Inter',sans-serif;background:#0f172a;color:#f5f0e8;min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:2rem 1rem}}
.container{{max-width:640px;width:100%}}
.logo{{text-align:center;margin-bottom:2rem}}
.logo h1{{font-size:2.5rem;font-weight:900;letter-spacing:-0.02em}}
.logo span{{color:#fde047}}
.subtitle{{text-align:center;color:#94a3b8;margin-bottom:2.5rem;font-size:1.05rem;line-height:1.6}}
.section{{margin-bottom:2rem}}
.section-title{{font-size:0.85rem;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:0.75rem;padding-left:0.25rem}}
.section-title.active{{color:#4ade80}}
.section-title.blocked{{color:#f87171}}
.domain-list{{display:flex;flex-direction:column;gap:0.5rem}}
.domain{{display:flex;align-items:center;justify-content:space-between;background:#1e293b;border:2px solid #334155;border-radius:0.5rem;padding:0.85rem 1rem;transition:border-color 0.15s,transform 0.1s}}
.domain.active:hover{{border-color:#4ade80;transform:translateY(-1px)}}
.domain.blocked{{opacity:0.5;border-color:#475569}}
.domain-name{{font-weight:700;font-size:1.05rem}}
.domain-name a{{color:#f5f0e8;text-decoration:none}}
.domain.active .domain-name a:hover{{color:#fde047}}
.badge{{font-size:0.7rem;font-weight:700;text-transform:uppercase;letter-spacing:0.05em;padding:0.2rem 0.6rem;border-radius:9999px}}
.badge.ok{{background:#064e3b;color:#4ade80}}
.badge.blocked{{background:#450a0a;color:#f87171}}
.footer{{text-align:center;color:#475569;font-size:0.8rem;margin-top:3rem;line-height:1.6}}
.portal-link{{display:block;text-align:center;margin-top:2rem;padding:0.85rem;background:#fde047;color:#0f172a;font-weight:900;border-radius:0.5rem;text-decoration:none;font-size:1rem;border:2px solid #fde047;transition:background 0.15s}}
.portal-link:hover{{background:#fbbf24}}
</style>
</head>
<body>
<div class="container">
<div class="logo"><h1><span>C</span>ompono VPN</h1></div>
<p class="subtitle">
Если основной сайт <strong>componovpn.com</strong> заблокирован, используйте любое из зеркал ниже.<br>
If the main site is blocked, use any mirror below.
</p>
<div class="section">
<div class="section-title active">&#9679; Рабочие зеркала / Active mirrors</div>
<div class="domain-list">{active_domains}</div>
</div>
<div class="section">
<div class="section-title blocked">&#9679; Заблокированы / Blocked</div>
<div class="domain-list">{blocked_domains}</div>
</div>
<a class="portal-link" href="https://{primary_domain}/portal">
&#128274; Найти подписку по email / Find subscription by email
</a>
<div class="footer">
Compono VPN &mdash; быстрый и надежный VPN<br>
Telegram: <a href="https://t.me/compono_bot" style="color:#64748b">@compono_bot</a>
</div>
</div>
</body>
</html>"""


@router.get("/mirrors")
@inject
async def mirrors_page(
    config: FromDishka[AppConfig],
) -> HTMLResponse:
    active = [d for d in config.hydra_domains if d and d not in BLOCKED_DOMAINS]
    blocked = [d for d in BLOCKED_DOMAINS]
    primary = config.hydra_primary_domain

    active_html = "\n".join(
        f'<div class="domain active">'
        f'<span class="domain-name"><a href="https://{d}/" target="_blank">{d}</a></span>'
        f'<span class="badge ok">OK</span>'
        f'</div>'
        for d in active
    )

    blocked_html = "\n".join(
        f'<div class="domain blocked">'
        f'<span class="domain-name">{d}</span>'
        f'<span class="badge blocked">blocked</span>'
        f'</div>'
        for d in blocked
    )

    html = MIRRORS_HTML_TEMPLATE.format(
        active_domains=active_html,
        blocked_domains=blocked_html,
        primary_domain=primary,
    )

    return HTMLResponse(content=html)
