import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from loguru import logger
from redis.asyncio import Redis

from src.bot.keyboards import get_payment_nudge_keyboard, get_recovery_offer_keyboard
from src.core.enums import Currency, TransactionStatus
from src.core.metrics import PAYMENT_NUDGE_SENT_TOTAL, RECOVERY_OFFER_SENT_TOTAL
from src.core.storage.keys import (
    PaymentNudgeDataKey,
    PaymentNudgeLatestKey,
    PaymentNudgeSentKey,
    PaymentNudgeUserKey,
    PendingPaymentNudgesKey,
    PendingRecoveryOffersKey,
)
from src.core.utils.message_payload import MessagePayload
from src.infrastructure.billing import BillingClient
from src.services.bot_payments import (
    is_bot_payment_gateway,
    is_stars_gateway,
    ruble_payments_enabled,
)
from src.services.notification import NotificationService
from src.services.recovery_offer import claim_offer, release_offer
from src.services.reminder_delivery import can_receive_reminders
from src.services.stars_charges import first_charge
from src.services.user import UserService

NUDGE_DELAY_SECONDS = 5 * 60
OFFER_DELAY_SECONDS = 15 * 60
MAX_LATENESS_SECONDS = 15 * 60
RETRY_DELAY_SECONDS = 60
DATA_TTL_SECONDS = 2 * 24 * 60 * 60
SENT_TTL_SECONDS = 7 * 24 * 60 * 60
USER_WINDOW_SECONDS = 30 * 60

_QUEUE_KEY = PendingPaymentNudgesKey()
_OFFER_QUEUE_KEY = PendingRecoveryOffersKey()


def format_price_text(amount: Decimal | str, currency_code: str) -> str:
    try:
        currency = Currency(currency_code)
    except (KeyError, ValueError):
        return f"{amount} {currency_code}"
    value = Decimal(str(amount))
    if currency in (Currency.RUB, Currency.XTR):
        return f"{int(value)} {currency.symbol}"
    return f"{value:.2f} {currency.symbol}"


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


async def schedule_payment_nudge(
    redis_client: Redis,
    *,
    payment_id: str,
    telegram_id: int,
    payment_url: str,
    plan_name: str,
    price_text: str,
    now: Optional[float] = None,
) -> None:
    if not payment_url:
        return
    created = time.time() if now is None else now
    data = {"url": payment_url, "plan": plan_name, "price": price_text}
    await redis_client.set(
        PaymentNudgeDataKey(payment_id=payment_id).pack(),
        json.dumps(data, ensure_ascii=False),
        ex=DATA_TTL_SECONDS,
    )
    await redis_client.set(
        PaymentNudgeLatestKey(telegram_id=telegram_id).pack(),
        payment_id,
        ex=DATA_TTL_SECONDS,
    )
    await redis_client.zadd(
        _QUEUE_KEY.pack(),
        {f"{payment_id}:{telegram_id}": created + NUDGE_DELAY_SECONDS},
        nx=True,
    )
    await redis_client.zadd(
        _OFFER_QUEUE_KEY.pack(),
        {f"{payment_id}:{telegram_id}": created + OFFER_DELAY_SECONDS},
        nx=True,
    )
    logger.debug(f"Scheduled payment nudge for payment '{payment_id}'")


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _paid_since(
    billing: BillingClient, telegram_id: int, created: Optional[datetime]
) -> bool:
    started = _as_utc(created)
    for transaction in await billing.list_transactions(telegram_id):
        if transaction.Status != TransactionStatus.COMPLETED.value:
            continue
        finished = _as_utc(transaction.CreatedAt)
        if started is None or finished is None or finished >= started:
            return True
    return False


async def _eligible(
    *,
    payment_id: str,
    telegram_id: int,
    redis_client: Redis,
    billing: BillingClient,
) -> Optional[tuple[dict[str, str], Any]]:
    latest = await redis_client.get(PaymentNudgeLatestKey(telegram_id=telegram_id).pack())
    if latest is not None and _text(latest) != payment_id:
        logger.debug(f"Payment nudge for '{payment_id}' skipped: a newer payment exists")
        return None

    raw = await redis_client.get(PaymentNudgeDataKey(payment_id=payment_id).pack())
    if not raw:
        return None

    transaction = await billing.get_transaction(UUID(payment_id))
    if not transaction or transaction.Status != TransactionStatus.PENDING.value:
        return None
    if not is_bot_payment_gateway(transaction.GatewayType):
        # A method the bot does not sell with now (e.g. Platega while rubles are off).
        logger.info(
            f"Payment nudge for '{payment_id}' skipped: '{transaction.GatewayType}' is not offered"
        )
        return None
    if await first_charge(redis_client, payment_id) is not None:
        logger.info(f"Payment nudge for '{payment_id}' skipped: paid, billing is completing it")
        return None
    if await _paid_since(billing, telegram_id, transaction.CreatedAt):
        return None
    return json.loads(_text(raw)), transaction


async def _claim(
    redis_client: Redis, payment_id: str, telegram_id: int
) -> Optional[tuple[str, str]]:
    sent_key = PaymentNudgeSentKey(payment_id=payment_id).pack()
    user_key = PaymentNudgeUserKey(telegram_id=telegram_id).pack()
    if not await redis_client.set(sent_key, "1", nx=True, ex=SENT_TTL_SECONDS):
        return None
    if not await redis_client.set(user_key, "1", nx=True, ex=USER_WINDOW_SECONDS):
        return None
    return sent_key, user_key


async def _send_one(
    *,
    member: str,
    due_at: float,
    now: float,
    redis_client: Redis,
    billing: BillingClient,
    user_service: UserService,
    notification_service: NotificationService,
) -> bool:
    payment_id, _, telegram_id_raw = member.partition(":")
    telegram_id = int(telegram_id_raw)

    if now - due_at > MAX_LATENESS_SECONDS:
        logger.debug(f"Payment nudge for '{payment_id}' is too late; dropped")
        return False

    found = await _eligible(
        payment_id=payment_id,
        telegram_id=telegram_id,
        redis_client=redis_client,
        billing=billing,
    )
    if found is None:
        return False
    data, transaction = found

    user = await user_service.get(telegram_id)
    if user is None or not can_receive_reminders(user):
        return False

    claimed = await _claim(redis_client, payment_id, telegram_id)
    if claimed is None:
        return False

    stars = is_stars_gateway(transaction.GatewayType)
    # «Другой способ» only when the bot offers more than Stars.
    stars_only = not ruble_payments_enabled()
    try:
        message = await notification_service.notify_user(
            user=user,
            payload=MessagePayload(
                i18n_key="ntf-payment-nudge",
                i18n_kwargs={"plan": data["plan"], "price": data["price"], "stars": int(stars)},
                reply_markup=get_payment_nudge_keyboard(
                    data["url"],
                    payment_id=None if stars_only else payment_id,
                    stars=stars,
                ),
                auto_delete_after=None,
                add_close_button=False,
            ),
        )
    except Exception:
        await redis_client.delete(*claimed)
        await redis_client.zadd(_QUEUE_KEY.pack(), {member: now + RETRY_DELAY_SECONDS}, nx=True)
        logger.opt(exception=True).warning(
            f"Payment nudge for '{payment_id}' failed to send; will retry"
        )
        return False

    if message is None:
        return False

    PAYMENT_NUDGE_SENT_TOTAL.labels(gateway=transaction.GatewayType or "UNKNOWN").inc()
    logger.info(f"Sent payment nudge for '{payment_id}' to '{telegram_id}'")
    return True


async def process_due_payment_nudges(
    *,
    redis_client: Redis,
    billing: BillingClient,
    user_service: UserService,
    notification_service: NotificationService,
    now: Optional[float] = None,
) -> int:
    current = time.time() if now is None else now
    key = _QUEUE_KEY.pack()
    due = await redis_client.zrangebyscore(key, "-inf", current, withscores=True)
    sent = 0
    for raw_member, due_at in due:
        member = _text(raw_member)
        await redis_client.zrem(key, member)
        try:
            sent += await _send_one(
                member=member,
                due_at=float(due_at),
                now=current,
                redis_client=redis_client,
                billing=billing,
                user_service=user_service,
                notification_service=notification_service,
            )
        except Exception:
            logger.opt(exception=True).warning(f"Payment nudge '{member}' failed; skipping")
    return sent


async def _offer_one(
    *,
    member: str,
    due_at: float,
    now: float,
    redis_client: Redis,
    billing: BillingClient,
    user_service: UserService,
    notification_service: NotificationService,
) -> bool:
    payment_id, _, telegram_id_raw = member.partition(":")
    telegram_id = int(telegram_id_raw)

    if now - due_at > MAX_LATENESS_SECONDS:
        return False

    latest = await redis_client.get(PaymentNudgeLatestKey(telegram_id=telegram_id).pack())
    if latest is not None and _text(latest) != payment_id:
        return False

    transaction = await billing.get_transaction(UUID(payment_id))
    if not transaction or transaction.Status not in (
        TransactionStatus.PENDING.value,
        TransactionStatus.CANCELED.value,
    ):
        return False
    if await first_charge(redis_client, payment_id) is not None:
        # Paid: billing is still completing it, or it was refunded and the user knows why.
        logger.info(f"Recovery offer for '{payment_id}' skipped: the payment was charged")
        return False

    user = await user_service.get(telegram_id)
    if user is None or not can_receive_reminders(user):
        return False

    if not await claim_offer(billing, user):
        return False

    try:
        message = await notification_service.notify_user(
            user=user,
            payload=MessagePayload(
                i18n_key="ntf-recovery-offer",
                i18n_kwargs={"stars_only": int(not ruble_payments_enabled())},
                reply_markup=get_recovery_offer_keyboard(payment_id),
                auto_delete_after=None,
                add_close_button=False,
            ),
        )
    except Exception:
        await release_offer(billing, telegram_id)
        await redis_client.zadd(
            _OFFER_QUEUE_KEY.pack(), {member: now + RETRY_DELAY_SECONDS}, nx=True
        )
        logger.opt(exception=True).warning(
            f"Recovery offer for '{payment_id}' failed to send; will retry"
        )
        return False

    if message is None:
        return False

    RECOVERY_OFFER_SENT_TOTAL.labels(source="payment").inc()
    logger.info(f"Sent the recovery offer for '{payment_id}' to '{telegram_id}'")
    return True


async def process_due_payment_offers(
    *,
    redis_client: Redis,
    billing: BillingClient,
    user_service: UserService,
    notification_service: NotificationService,
    now: Optional[float] = None,
) -> int:
    current = time.time() if now is None else now
    key = _OFFER_QUEUE_KEY.pack()
    due = await redis_client.zrangebyscore(key, "-inf", current, withscores=True)
    sent = 0
    for raw_member, due_at in due:
        member = _text(raw_member)
        await redis_client.zrem(key, member)
        try:
            sent += await _offer_one(
                member=member,
                due_at=float(due_at),
                now=current,
                redis_client=redis_client,
                billing=billing,
                user_service=user_service,
                notification_service=notification_service,
            )
        except Exception:
            logger.opt(exception=True).warning(f"Recovery offer '{member}' failed; skipping")
    return sent
