import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

import jwt
from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from pydantic import BaseModel, EmailStr
from redis.asyncio import Redis
from remnapy import RemnawaveSDK
from remnapy.exceptions import NotFoundError

from src.core.config import AppConfig
from src.core.constants import API_V1
from src.core.storage.keys import OtpKey, OtpRateLimitKey
from src.infrastructure.billing import BillingClient
from src.services.email import EmailService

router = APIRouter(prefix=API_V1 + "/app")

bearer_scheme = HTTPBearer()


# --- Request / Response models ---


class SendOtpRequest(BaseModel):
    email: EmailStr


class VerifyOtpRequest(BaseModel):
    email: EmailStr
    code: str


class SubscriptionResponse(BaseModel):
    status: str
    plan_name: str
    expires_at: Optional[str] = None
    days_remaining: Optional[int] = None
    traffic_used_bytes: int = 0
    traffic_limit_bytes: int = 0
    device_limit: int = 0
    subscription_url: str
    short_uuid: str


class MeResponse(BaseModel):
    email: str
    subscription: Optional[SubscriptionResponse] = None
    has_subscription: bool = False


# --- JWT helpers ---


def create_jwt(email: str, secret: str, expiry_days: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "email": email,
        "iat": now,
        "exp": now + timedelta(days=expiry_days),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_jwt(token: str, secret: str) -> dict:
    return jwt.decode(token, secret, algorithms=["HS256"])


# --- Endpoints ---


@router.post("/auth/send")
@inject
async def auth_send(
    body: SendOtpRequest,
    redis_client: FromDishka[Redis],
    email_service: FromDishka[EmailService],
    config: FromDishka[AppConfig],
) -> JSONResponse:
    email = body.email.lower()

    rate_key = OtpRateLimitKey(email=email).pack()
    if await redis_client.exists(rate_key):
        raise HTTPException(status_code=429, detail="RATE_LIMITED")

    code = str(secrets.randbelow(900000) + 100000)

    otp_key = OtpKey(email=email).pack()
    otp_data = json.dumps({"code": code, "attempts": 0})
    await redis_client.setex(otp_key, config.otp_ttl_seconds, otp_data)
    await redis_client.setex(rate_key, 60, "1")

    await email_service.send_otp_code(email, code)
    logger.info(f"OTP sent to '{email}'")

    return JSONResponse(content={"ok": True})


@router.post("/auth/verify")
@inject
async def auth_verify(
    body: VerifyOtpRequest,
    redis_client: FromDishka[Redis],
    config: FromDishka[AppConfig],
) -> JSONResponse:
    email = body.email.lower()
    jwt_secret = config.jwt_secret.get_secret_value()

    if not jwt_secret:
        raise HTTPException(status_code=500, detail="AUTH_NOT_CONFIGURED")

    otp_key = OtpKey(email=email).pack()
    raw = await redis_client.get(otp_key)

    if not raw:
        raise HTTPException(status_code=400, detail="CODE_EXPIRED")

    otp_data = json.loads(raw)

    if otp_data["attempts"] >= config.otp_max_attempts:
        await redis_client.delete(otp_key)
        raise HTTPException(status_code=400, detail="MAX_ATTEMPTS")

    if otp_data["code"] != body.code.strip():
        otp_data["attempts"] += 1
        await redis_client.setex(
            otp_key,
            await redis_client.ttl(otp_key),
            json.dumps(otp_data),
        )
        raise HTTPException(status_code=400, detail="INVALID_CODE")

    await redis_client.delete(otp_key)

    token = create_jwt(email, jwt_secret, config.jwt_expiry_days)
    return JSONResponse(content={"token": token})


@router.get("/me")
@inject
async def me(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    *,
    config: FromDishka[AppConfig],
    billing: FromDishka[BillingClient],
    remnawave: FromDishka[RemnawaveSDK],
) -> JSONResponse:
    jwt_secret = config.jwt_secret.get_secret_value()
    if not jwt_secret:
        raise HTTPException(status_code=500, detail="AUTH_NOT_CONFIGURED")

    try:
        payload = decode_jwt(credentials.credentials, jwt_secret)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="TOKEN_EXPIRED")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="INVALID_TOKEN")

    email = payload["email"]

    lookup = await billing.portal_lookup(email)

    if not lookup or not lookup.has_subscription or not lookup.subscription_url:
        return JSONResponse(
            content=MeResponse(email=email, has_subscription=False).model_dump()
        )

    parsed = urlparse(lookup.subscription_url)
    short_uuid = parsed.path.rstrip("/").split("/")[-1]

    plan_name = lookup.plan_name or "VPN"

    sub_response = SubscriptionResponse(
        status="unknown",
        plan_name=plan_name,
        subscription_url=lookup.subscription_url,
        short_uuid=short_uuid,
    )

    try:
        remna_user = await remnawave.users.get_user_by_short_uuid(short_uuid)
        sub_response.status = remna_user.status.value if remna_user.status else "active"
        sub_response.traffic_used_bytes = remna_user.used_traffic_bytes or 0
        sub_response.traffic_limit_bytes = remna_user.traffic_limit_bytes or 0
        sub_response.device_limit = remna_user.hwid_device_limit or 0

        if remna_user.expire_at:
            expire_dt = remna_user.expire_at
            sub_response.expires_at = expire_dt.isoformat()
            delta = expire_dt - datetime.now(timezone.utc)
            sub_response.days_remaining = max(0, delta.days)
    except NotFoundError:
        logger.warning(f"Remnawave user not found for short_uuid '{short_uuid}'")
        sub_response.status = "unknown"
    except Exception as e:
        logger.error(f"Failed to fetch Remnawave user '{short_uuid}': {e}")
        sub_response.status = "unknown"

    return JSONResponse(
        content=MeResponse(
            email=email,
            subscription=sub_response.model_dump(),
            has_subscription=True,
        ).model_dump()
    )
