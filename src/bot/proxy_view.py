import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from loguru import logger

from src.core.utils.time import MSK
from src.infrastructure.billing import BillingClient
from src.infrastructure.billing.models import BillingPlan, BillingTGProxy
from src.services.bot_payments import BOT_CURRENCY, ruble_payments_enabled

PAID_PROXY_PLAN_IDS = frozenset({1, 2, 3, 38})
SOURCE_VPN_PLAN = "vpn_plan"
SOURCE_PROXY_PLAN = "proxy_plan"
PROXY_DURATION_DAYS = 30
TITLE = "📡 <b>Прокси для Telegram</b>"
NO_VPN = "Telegram работает без VPN."
VPN_OFF = "⚠️ Перед подключением выключите VPN."
UNAVAILABLE = "Сейчас прокси недоступны. Попробуйте позже."
FREE_LINE = "🆓 <b>Бесплатный</b> — общий, при нагрузке скорость снижается."
DEVICES_SENTENCE = "До 3 устройств одновременно."


@dataclass
class ProxyView:
    proxies: list[dict[str, Any]] = field(default_factory=list)
    entitled: bool = False
    source: str | None = None
    expires_at: datetime | None = None
    proxy_plan_id: int = 0
    price_rub: float | None = None
    price_stars: Decimal | None = None
    personal_loaded: bool = False
    legacy_paid: bool = False
    vpn_blocked: bool = False
    # Sold for rubles (Platega) when APP_BOT_RUBLE_PAYMENTS is on and billing has a ruble price.
    rubles: bool = False

    @property
    def has_price(self) -> bool:
        if self.proxy_plan_id <= 0:
            return False
        if self.rubles:
            return self.price_rub is not None and self.price_rub > 0
        # Stars only: the proxy is sellable only with a Stars price.
        return self.price_stars is not None and self.price_stars > 0

    @property
    def has_personal(self) -> bool:
        return any(p["is_personal"] for p in self.proxies)

    @property
    def can_buy(self) -> bool:
        return (
            self.personal_loaded and not self.entitled and not self.vpn_blocked and self.has_price
        )

    @property
    def price_text(self) -> str:
        if self.rubles:
            return format_rub(self.price_rub)
        return format_stars(self.price_stars)

    @property
    def can_renew(self) -> bool:
        return (
            self.personal_loaded
            and self.entitled
            and self.source == SOURCE_PROXY_PLAN
            and self.has_price
        )


def format_price(value: float | None) -> str:
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def format_rub(value: Decimal | float | None) -> str:
    if value is None:
        return ""
    return f"{format_price(float(value))} ₽"


def format_stars(value: Decimal | float | None) -> str:
    if value is None:
        return ""
    return f"{format_price(float(value))} ★"


def stars_price(plan: Optional[BillingPlan], days: int) -> Decimal | None:
    if plan is None:
        return None
    for duration in plan.Durations:
        if duration.Days != days:
            continue
        for price in duration.Prices:
            if price.Currency != BOT_CURRENCY:
                continue
            try:
                return Decimal(price.Price)
            except InvalidOperation:
                return None
    return None


async def load_stars_price(billing: BillingClient, plan_id: int) -> Decimal | None:
    if plan_id <= 0:
        return None
    try:
        return stars_price(await billing.get_plan(plan_id), PROXY_DURATION_DAYS)
    except Exception:
        logger.opt(exception=True).warning(
            f"Could not read the Stars price of proxy plan {plan_id}"
        )
        return None


def has_active_paid_vpn(user: Any) -> bool:
    subscription = user.current_subscription
    return bool(subscription and subscription.is_active and not subscription.is_trial)


def to_https_link(link: str) -> str:
    if link.startswith("tg://proxy?"):
        return "https://t.me/proxy?" + link.removeprefix("tg://proxy?")
    return link


def serialize_proxies(proxies: list[BillingTGProxy]) -> list[dict[str, Any]]:
    return [
        {
            "id": str(p.id),
            "url": to_https_link(p.link),
            "kind": p.kind,
            "is_public": p.is_public,
            "is_personal": p.id < 0,
        }
        for p in proxies
    ]


def legacy_proxy_plan_id(user: Any) -> int:
    subscription = user.current_subscription
    if (
        subscription
        and subscription.is_active
        and not subscription.is_trial
        and subscription.plan
        and subscription.plan.id in PAID_PROXY_PLAN_IDS
    ):
        return subscription.plan.id
    return 0


async def load_proxy_view(billing: BillingClient, user: Any) -> ProxyView:
    try:
        personal = await billing.get_personal_tg_proxies(user.telegram_id)
        view = ProxyView(
            proxies=serialize_proxies(personal.proxies),
            entitled=personal.entitled,
            source=personal.source,
            expires_at=personal.expires_at,
            proxy_plan_id=personal.proxy_plan_id or 0,
            price_rub=personal.price_rub,
            personal_loaded=True,
            vpn_blocked=has_active_paid_vpn(user),
        )
        if not view.entitled or view.source == SOURCE_PROXY_PLAN:
            if ruble_payments_enabled() and view.price_rub is not None and view.price_rub > 0:
                view.rubles = True
            else:
                view.price_stars = await load_stars_price(billing, view.proxy_plan_id)
        return view
    except Exception:
        logger.opt(exception=True).warning("Failed to fetch personal TG proxies, using public list")
    plan_id = legacy_proxy_plan_id(user)
    try:
        proxies = await billing.get_tg_proxies(plan_id)
    except Exception:
        logger.opt(exception=True).warning("Failed to fetch TG proxies")
        proxies = []
    return ProxyView(proxies=serialize_proxies(proxies), legacy_paid=plan_id != 0)


async def await_entitlement(
    billing: BillingClient, user: Any, attempts: int = 5, delay: float = 0.6
) -> ProxyView:
    view = await load_proxy_view(billing, user)
    for _ in range(attempts - 1):
        if view.entitled:
            break
        await asyncio.sleep(delay)
        view = await load_proxy_view(billing, user)
    return view


def format_date(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        return value.strftime("%d.%m.%Y")
    return value.astimezone(MSK).strftime("%d.%m.%Y")


PHONE_LINKS_ENABLED = False
UPDATE_HINT = "📲 Не подключается? Обновите Telegram до последней версии."


def _is_web(p: dict[str, Any]) -> bool:
    return p["kind"] == "WEB"


def primary_phone_url(view: ProxyView) -> str:
    if not PHONE_LINKS_ENABLED:
        return ""
    for p in view.proxies:
        if not p["is_public"] and not _is_web(p):
            return p["url"]
    return ""


def primary_desktop_url(view: ProxyView) -> str:
    for p in view.proxies:
        if not p["is_public"] and _is_web(p):
            return p["url"]
    return ""


def free_url(view: ProxyView) -> str:
    for p in view.proxies:
        if p["is_public"] and _is_web(p):
            return p["url"]
    return ""


def fallback_buttons(view: ProxyView) -> list[dict[str, str]]:
    ordered = sorted(view.proxies, key=lambda p: p["is_public"])
    result = []
    seen = {"web": 0, "phone": 0}
    for p in ordered:
        kind = "web" if _is_web(p) else "phone"
        seen[kind] += 1
        icon = "💻" if kind == "web" else "📱"
        if seen[kind] == 1:
            where = "компьютере" if kind == "web" else "телефоне"
            label = f"{icon} Подключить на {where}"
        else:
            label = f"{icon} Запасной {seen[kind] - 1}"
        result.append({"id": f"{kind}{seen[kind]}", "label": label, "url": p["url"]})
    return result


def build_proxy_message(view: ProxyView) -> str:
    if not view.personal_loaded:
        if not view.proxies:
            return f"{TITLE}\n{UNAVAILABLE}"
        return f"{TITLE}\n{NO_VPN}\n\n{VPN_OFF}"
    if view.entitled:
        return _entitled_message(view)
    return _offer_message(view)


def _status(view: ProxyView) -> str:
    if view.source == SOURCE_VPN_PLAN:
        return "Входит в подписку Compono VPN."
    until = format_date(view.expires_at)
    return f"Действует до {until}." if until else ""


def _entitled_message(view: ProxyView) -> str:
    status = _status(view)
    if view.has_personal:
        title = "⭐ <b>Ваш Pro-прокси</b>"
        second = "Личный и быстрый, до 3 устройств."
    else:
        title = "⭐ <b>Стабильный прокси</b>"
        second = "Стабильное подключение."
    if status:
        second = f"{second} {status}"
    return f"{title}\n{second}\n\n{VPN_OFF}\n{UPDATE_HINT}"


def _offer_message(view: ProxyView) -> str:
    lines = [TITLE, NO_VPN, ""]
    if view.can_buy:
        lines.extend(
            [
                FREE_LINE,
                "⭐ <b>Pro</b> — личный и быстрый, до 3 устройств."
                f" <b>{view.price_text} в месяц</b>.",
                "🎁 С подпиской Compono VPN — Pro бесплатно.",
            ]
        )
    elif free_url(view):
        lines.append(FREE_LINE)
    else:
        lines.append(UNAVAILABLE)
    lines.extend(["", VPN_OFF])
    return "\n".join(lines)


def build_success_message(view: ProxyView) -> str:
    if not view.entitled:
        return (
            "✅ <b>Оплата прошла</b>\nPro скоро появится — откройте «Прокси» в меню через минуту."
        )
    until = format_date(view.expires_at)
    personal = view.has_personal
    title = "✅ <b>Pro подключён</b>" if personal else "✅ <b>Стабильный прокси подключён</b>"
    parts = []
    if until:
        parts.append(f"Действует до {until}.")
    if personal:
        parts.append(DEVICES_SENTENCE)
    body = f"\n{' '.join(parts)}" if parts else ""
    return f"{title}{body}\n\n{VPN_OFF}\n{UPDATE_HINT}"
