import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from aiogram import Bot
from aiogram.methods import TelegramMethod
from aiogram.types import Message
from aiogram_dialog import BgManagerFactory, ShowMode, StartMode
from fluentogram import TranslatorHub
from loguru import logger
from redis.asyncio import Redis

from src.bot.states import Subscription
from src.core.config import AppConfig
from src.core.enums import PaymentGatewayType, PlanAvailability, PlanType, PurchaseType
from src.core.utils.time import datetime_now
from src.infrastructure.billing.client import BillingClient
from src.infrastructure.billing.converters import billing_plan_to_dto, billing_price_details_to_dto
from src.infrastructure.taskiq.tasks.cancel_survey import schedule_cancel_survey_check
from src.models.dto.plan import PlanDto
from src.models.dto.subscription import BaseSubscriptionDto
from src.models.dto.user import BaseUserDto, UserDto
from src.services.remnawave import RemnawaveService
from src.services.stars_invoice import create_stars_invoice_link
from src.services.subscription import SubscriptionService
from src.services.trial_activation import is_connected
from src.services.user import UserService

CARDS = Path(__file__).with_name("widget_cards")
CONNECT_HTML = (CARDS / "connect.html").read_text(encoding="utf-8")
STATUS_HTML = (CARDS / "status.html").read_text(encoding="utf-8")
PLANS_HTML = (CARDS / "plans.html").read_text(encoding="utf-8")
CARD_WIDTH = 340
STATE_LIMIT = 1024
ANSWER_LIMIT = 1024
WIDGET_QUERY_UPDATE = "widget_query"
GIB = 1024**3


class SendWidget(TelegramMethod[Message]):
    __returning__ = Message
    __api_method__ = "sendWidget"

    chat_id: int
    html: str
    width: Optional[int] = None
    chat_data: Optional[str] = None
    caption: Optional[str] = None
    allow_queries: Optional[bool] = None


class EditMessageWidgetData(TelegramMethod[bool]):
    __returning__ = bool
    __api_method__ = "editMessageWidgetData"

    chat_id: int
    message_id: int
    chat_data: Optional[str] = None


class AnswerWidgetQuery(TelegramMethod[bool]):
    __returning__ = bool
    __api_method__ = "answerWidgetQuery"

    widget_query_id: str
    data: Optional[str] = None


@dataclass(frozen=True)
class WidgetQuery:
    id: str
    user_id: int
    chat_id: Optional[int]
    message_id: Optional[int]
    data: str


def parse_widget_query(raw: Any) -> Optional[WidgetQuery]:
    if not isinstance(raw, dict):
        return None
    sender = raw.get("from") or {}
    chat = raw.get("chat") or {}
    if not raw.get("id") or not isinstance(sender.get("id"), int):
        return None
    return WidgetQuery(
        id=str(raw["id"]),
        user_id=sender["id"],
        chat_id=chat.get("id"),
        message_id=raw.get("message_id"),
        data=str(raw.get("data") or ""),
    )


def pack(state: dict[str, Any], limit: int = STATE_LIMIT) -> str:
    packed = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    if len(packed.encode()) > limit:
        raise ValueError(f"widget state is {len(packed.encode())} bytes, over the {limit} limit")
    return packed


def _date(value: Optional[datetime]) -> Optional[str]:
    if not value or value.year >= 2099:
        return None
    return value.strftime("%d.%m.%Y")


def connect_state(
    *, connected: bool, connect_url: str, subscription_url: str, expire_at: Optional[datetime]
) -> dict[str, Any]:
    state: dict[str, Any] = {"c": int(connected), "u": connect_url, "s": subscription_url}
    if expiry := _date(expire_at):
        state["e"] = expiry
    return state


def status_state(
    subscription: BaseSubscriptionDto, used_bytes: Optional[int], now: datetime
) -> dict[str, Any]:
    left = subscription.expire_at - now
    state: dict[str, Any] = {
        "n": subscription.plan.name,
        "d": max(0, left.days + (1 if left.seconds else 0)) if left.total_seconds() > 0 else 0,
    }
    if expiry := _date(subscription.expire_at):
        state["e"] = expiry
    if subscription.traffic_limit and subscription.traffic_limit > 0:
        state["l"] = subscription.traffic_limit
        state["u"] = round((used_bytes or 0) / GIB, 1)
    return state


def duration_label(days: int) -> str:
    months = {30: "1 месяц", 90: "3 месяца", 180: "6 месяцев", 365: "1 год"}
    return months.get(days, f"{days} дн.")


def _limits(plan: PlanDto) -> str:
    traffic = "без лимита трафика" if plan.is_unlimited_traffic else f"{plan.traffic_limit} ГБ"
    devices = "" if plan.is_unlimited_devices else f" · до {plan.device_limit} устройств"
    return f"{traffic}{devices} в месяц"


def sellable(plans: list[PlanDto]) -> list[PlanDto]:
    keep = [
        p
        for p in plans
        if p.is_active
        and p.type != PlanType.PROXY
        and p.availability != PlanAvailability.TRIAL
        and any(d.days > 0 for d in p.durations)
    ]
    return sorted(keep, key=lambda p: (p.order_index, p.id or 0))


def plans_state(plans: list[PlanDto], selected: Optional[int], currency: str = "RUB") -> dict:
    rows = []
    for plan in sellable(plans):
        durations = []
        for d in sorted(plan.durations, key=lambda d: d.days):
            price = next((p.price for p in d.prices if p.currency == currency), None)
            if d.days <= 0 or price is None:
                continue
            durations.append([d.days, int(Decimal(price)), duration_label(d.days)])
        if durations:
            rows.append({"i": plan.id, "n": plan.name, "d": durations, "f": _limits(plan)})
    state: dict[str, Any] = {"p": rows}
    if selected and any(r["i"] == selected for r in rows):
        state["s"] = selected
    return state


def purchase_type(subscription: Optional[BaseSubscriptionDto], plan_id: int) -> PurchaseType:
    if not subscription or subscription.is_trial or not subscription.is_active:
        return PurchaseType.NEW
    return PurchaseType.RENEW if subscription.plan.id == plan_id else PurchaseType.CHANGE


def pick_gateway(gateways: list[Any], stars: bool) -> Optional[Any]:
    """Stars, or the first active ruble gateway for the bot (Platega in prod, YooKassa on stage)."""
    usable = [g for g in gateways if g.IsActive and g.Channel in ("BOT", "ALL")]
    if stars:
        return next((g for g in usable if g.Type == PaymentGatewayType.TELEGRAM_STARS.value), None)
    rubles = [
        g
        for g in usable
        if g.Currency == "RUB" and g.Type != PaymentGatewayType.TELEGRAM_STARS.value
    ]
    rubles.sort(key=lambda g: (g.Type != PaymentGatewayType.PLATEGA.value, g.OrderIndex))
    return rubles[0] if rubles else None


class WidgetService:
    def __init__(
        self,
        config: AppConfig,
        bot: Bot,
        redis_client: Redis,
        translator_hub: TranslatorHub,
        billing: BillingClient,
        user_service: UserService,
        subscription_service: SubscriptionService,
        remnawave_service: RemnawaveService,
        bg_manager_factory: BgManagerFactory,
    ) -> None:
        self.config = config
        self.bot = bot
        self.redis_client = redis_client
        self.translator_hub = translator_hub
        self.billing = billing
        self.user_service = user_service
        self.subscription_service = subscription_service
        self.remnawave_service = remnawave_service
        self.bg_manager_factory = bg_manager_factory

    @property
    def enabled(self) -> bool:
        return self.config.widgets_enabled

    def _caption(self, user: BaseUserDto) -> str:
        i18n = self.translator_hub.get_translator_by_locale(locale=user.language)
        return i18n.get("msg-widget-card-caption")

    async def _send(self, user: BaseUserDto, html: str, state: dict[str, Any]) -> Message:
        return await self.bot(
            SendWidget(
                chat_id=user.telegram_id,
                html=html,
                width=CARD_WIDTH,
                chat_data=pack(state),
                caption=self._caption(user),
                allow_queries=True,
            )
        )

    async def _connected(self, user: UserDto, subscription: BaseSubscriptionDto) -> bool:
        devices = await self.remnawave_service.get_devices_user(user, subscription=subscription)
        if devices:
            return True
        try:
            remote = await self.remnawave_service.get_user(subscription.user_remna_id)
        except Exception:
            logger.warning(f"Could not read RemnaUser for '{user.telegram_id}' (widget)")
            return False
        return is_connected(remote, devices)

    async def _used_bytes(self, subscription: BaseSubscriptionDto) -> Optional[int]:
        try:
            remote = await self.remnawave_service.get_user(subscription.user_remna_id)
        except Exception:
            return None
        traffic = getattr(remote, "user_traffic", None)
        used = getattr(traffic, "used_traffic_bytes", None)
        return used if isinstance(used, int) else None

    def _connect_state(self, subscription: BaseSubscriptionDto, connected: bool) -> dict:
        return connect_state(
            connected=connected,
            connect_url=SubscriptionService.build_connect_url(
                subscription.url, self.config.website_url
            ),
            subscription_url=subscription.url,
            expire_at=subscription.expire_at,
        )

    async def send_connect(self, user: UserDto, subscription: BaseSubscriptionDto) -> Message:
        connected = await self._connected(user, subscription)
        message = await self._send(user, CONNECT_HTML, self._connect_state(subscription, connected))
        logger.info(f"Sent connect card to '{user.telegram_id}' (connected={connected})")
        return message

    async def send_status(self, user: BaseUserDto, subscription: BaseSubscriptionDto) -> Message:
        state = status_state(subscription, await self._used_bytes(subscription), datetime_now())
        message = await self._send(user, STATUS_HTML, state)
        logger.info(f"Sent subscription status card to '{user.telegram_id}'")
        return message

    async def _plans(self, telegram_id: int) -> list[PlanDto]:
        return [billing_plan_to_dto(p) for p in await self.billing.get_available_plans(telegram_id)]

    async def send_plans(self, user: BaseUserDto) -> Optional[Message]:
        plans = await self._plans(user.telegram_id)
        subscription = await self.subscription_service.get_current(user.telegram_id)
        selected = subscription.plan.id if subscription and not subscription.is_trial else None
        state = plans_state(plans, selected)
        if not state["p"]:
            logger.warning(f"No sellable plans for '{user.telegram_id}', plan card not sent")
            return None
        message = await self._send(user, PLANS_HTML, state)
        logger.info(f"Sent plan card to '{user.telegram_id}' ({len(state['p'])} plans)")
        return message

    async def send_subscription(self, user: UserDto) -> Optional[Message]:
        subscription = await self.subscription_service.get_current(user.telegram_id)
        if subscription and not subscription.is_trial:
            return await self.send_status(user, subscription)
        return await self.send_plans(user)

    async def handle_query(self, raw: Any) -> None:
        query = parse_widget_query(raw)
        if not query:
            logger.warning("Ignoring a widget query without an id or sender")
            return
        reply: dict[str, Any] = {}
        try:
            reply = await self._answer(query)
        except Exception:
            logger.opt(exception=True).warning(
                f"Widget query '{query.data}' from '{query.user_id}' failed"
            )
            reply = {"m": "Не получилось. Попробуйте ещё раз."}
        await self.bot(AnswerWidgetQuery(widget_query_id=query.id, data=pack(reply, ANSWER_LIMIT)))

    async def _answer(self, query: WidgetQuery) -> dict[str, Any]:
        action, _, rest = query.data.partition(":")
        user = await self.user_service.get(query.user_id)
        if not user:
            return {"m": "Нажмите /start и попробуйте снова."}
        subscription = await self.subscription_service.get_current(query.user_id)
        if action == "chk":
            return await self._check(query, user, subscription)
        if action == "st":
            if not subscription:
                return {}
            used = await self._used_bytes(subscription)
            return {"s": status_state(subscription, used, datetime_now())}
        if action == "buy":
            await self.send_plans(user)
            return {"m": "Тарифы ниже"}
        if action == "menu":
            manager = self.bg_manager_factory.bg(
                bot=self.bot, user_id=user.telegram_id, chat_id=user.telegram_id
            )
            await manager.start(
                Subscription.MAIN, mode=StartMode.RESET_STACK, show_mode=ShowMode.SEND
            )
            return {}
        if action in ("pay", "star"):
            plan_id, _, days = rest.partition(":")
            if not plan_id.isdigit() or not days.isdigit():
                return {"m": "Не получилось. Попробуйте ещё раз."}
            return await self._pay(user, subscription, int(plan_id), int(days), action == "star")
        logger.warning(f"Unknown widget query '{query.data}' from '{query.user_id}'")
        return {}

    async def _check(
        self, query: WidgetQuery, user: UserDto, subscription: Optional[BaseSubscriptionDto]
    ) -> dict[str, Any]:
        if not subscription or not subscription.is_active:
            return {"c": 0}
        connected = await self._connected(user, subscription)
        if connected and query.chat_id and query.message_id:
            await self.bot(
                EditMessageWidgetData(
                    chat_id=query.chat_id,
                    message_id=query.message_id,
                    chat_data=pack(self._connect_state(subscription, True)),
                )
            )
        return {"c": int(connected)}

    async def _pay(
        self,
        user: UserDto,
        subscription: Optional[BaseSubscriptionDto],
        plan_id: int,
        days: int,
        stars: bool,
    ) -> dict[str, Any]:
        plans = await self._plans(user.telegram_id)
        plan = next((p for p in sellable(plans) if p.id == plan_id), None)
        duration = plan.get_duration(days) if plan else None
        if not plan or not duration:
            return {"m": "Этот тариф сейчас недоступен."}
        gateway = pick_gateway(await self.billing.list_active_gateways(), stars)
        if not gateway:
            return {"m": "Этот способ оплаты сейчас недоступен."}
        gateway_type = gateway.Type
        kind = purchase_type(subscription, plan_id)
        result = await self.billing.create_payment(
            telegram_id=user.telegram_id,
            plan_id=plan_id,
            duration_days=days,
            currency=gateway.Currency,
            gateway_type=gateway_type,
            purchase_type=kind.value,
            is_test=user.is_dev,
        )
        pricing = billing_price_details_to_dto(
            await self.billing.calculate_price(
                telegram_id=user.telegram_id,
                plan_id=plan_id,
                duration_days=days,
                currency=gateway.Currency,
            )
        )
        await schedule_cancel_survey_check(
            redis_client=self.redis_client,
            payment_id=result.ID,
            telegram_id=user.telegram_id,
            gateway_type=gateway_type,
        )
        amount = int(pricing.final_amount)
        logger.info(
            f"Widget payment '{result.ID}' for '{user.telegram_id}': plan {plan.id}, {days} days, "
            f"{gateway_type}, {kind.value}"
        )
        if stars:
            link = result.URL or await create_stars_invoice_link(
                self.bot,
                payment_id=UUID(str(result.ID)),
                title=plan.name,
                description=f"{plan.name} · {days} дн.",
                amount=pricing.final_amount,
            )
            return {"t": link, "a": f"{amount} ⭐"}
        if not result.URL:
            return {"m": "Не получилось создать платёж. Попробуйте ещё раз."}
        return {"u": result.URL, "a": f"{amount} ₽"}
