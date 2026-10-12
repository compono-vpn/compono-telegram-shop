import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger

from src.core.utils.time import MSK
from src.infrastructure.billing import BillingClient
from src.infrastructure.billing.models import BillingTGProxy

PAID_PROXY_PLAN_IDS = frozenset({1, 2, 3})
SOURCE_VPN_PLAN = "vpn_plan"
SOURCE_PROXY_PLAN = "proxy_plan"
STRIKETHROUGH_PRICE_RUB = 49
PROXY_DURATION_DAYS = 30
DEVICES_LINE = "Ссылки только ваши — до 3 устройств одновременно."
CLOSING = "Нажмите на ссылку, прокси подключится автоматически."
VPN_WARNING = (
    "⚠️ <b>Важно:</b> подключайте прокси с"
    " <b>выключенным VPN</b> — иначе соединение"
    " может не установиться."
)
INTRO = (
    "Telegram-прокси позволяет пользоваться мессенджером"
    " даже без включённого VPN. Полезно, когда VPN"
    " недоступен или вы хотите сэкономить трафик."
)


@dataclass
class ProxyView:
    proxies: list[dict[str, Any]] = field(default_factory=list)
    entitled: bool = False
    source: str | None = None
    expires_at: datetime | None = None
    proxy_plan_id: int = 0
    price_rub: float | None = None
    personal_loaded: bool = False
    legacy_paid: bool = False
    vpn_blocked: bool = False

    @property
    def has_price(self) -> bool:
        return self.proxy_plan_id > 0 and self.price_rub is not None and self.price_rub > 0

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
        return format_price(self.price_rub)

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


def has_active_paid_vpn(user: Any) -> bool:
    subscription = user.current_subscription
    return bool(subscription and subscription.is_active and not subscription.is_trial)


def serialize_proxies(proxies: list[BillingTGProxy]) -> list[dict[str, Any]]:
    return [
        {
            "id": str(p.id),
            "server": p.server,
            "port": p.port,
            "link": p.link,
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
        return ProxyView(
            proxies=serialize_proxies(personal.proxies),
            entitled=personal.entitled,
            source=personal.source,
            expires_at=personal.expires_at,
            proxy_plan_id=personal.proxy_plan_id or 0,
            price_rub=personal.price_rub,
            personal_loaded=True,
            vpn_blocked=has_active_paid_vpn(user),
        )
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


def _link(p: dict[str, Any], with_port: bool) -> str:
    target = f"{p['server']}:{p['port']}" if with_port else p["server"]
    return f'<a href="{p["link"]}">Подключить {target}</a>'


def _label(rows: list[dict[str, Any]]) -> str:
    return "личный" if any(p["is_personal"] for p in rows) else "стабильный"


def _phone_lines(phone: list[dict[str, Any]], empty_text: str) -> list[str]:
    lines = ["📱 <b>Телефон</b>"]
    if not phone:
        lines.append(empty_text)
        return lines
    label = _label(phone)
    stable = [p for p in phone if not p["is_public"]]
    backup = [p for p in phone if p["is_public"]]
    for p in stable:
        lines.append(f"▸ {_link(p, True)} — {label}")
    if stable and backup:
        lines.append(f"Запасные, если {label} не подключается:")
    for p in backup:
        lines.append(f"▸ {_link(p, True)}")
    return lines


def _desktop_lines(desktop: list[dict[str, Any]]) -> list[str]:
    label = _label(desktop)
    stable = [p for p in desktop if not p["is_public"]]
    backup = [p for p in desktop if p["is_public"]]
    lines = ["", "💻 <b>Компьютер</b> (Telegram Desktop 7.1.1 и новее)"]
    for p in stable:
        lines.append(f"▸ {_link(p, False)} — {label}")
    if stable and backup:
        lines.append(f"Запасные, если {label} не подключается:")
    for p in backup:
        lines.append(f"▸ {_link(p, False)}")
    if not stable and len(desktop) > 1:
        lines.append("Если один не подключается — попробуйте другой.")
    return lines


def _links_block(view: ProxyView) -> list[str]:
    phone = [p for p in view.proxies if p["kind"] != "WEB"]
    desktop = [p for p in view.proxies if p["kind"] == "WEB"]
    unavailable = "▸ Прокси для телефона временно недоступны — на телефоне используйте VPN."
    if view.personal_loaded:
        empty = "▸ Общих прокси для телефона нет — личный ниже." if view.can_buy else unavailable
    else:
        empty = unavailable if view.legacy_paid else "▸ Общих прокси для телефона сейчас нет."
    lines = _phone_lines(phone, empty)
    if desktop:
        lines.extend(_desktop_lines(desktop))
    return lines


def offer_lines(price_text: str) -> list[str]:
    return [
        "",
        "🚀 <b>Личный прокси</b>",
        "Быстрый прокси только для вас: своя ссылка для телефона и своя для компьютера,"
        " до 3 устройств одновременно.",
        f"<s>{STRIKETHROUGH_PRICE_RUB} ₽</s> <b>{price_text} ₽</b> в месяц — только до 31 октября.",
        "🎁 Подписчикам Compono VPN — бесплатно.",
    ]


def status_lines(view: ProxyView) -> list[str]:
    if not view.entitled:
        return []
    personal = view.has_personal
    if view.source == SOURCE_VPN_PLAN:
        head = (
            "🎁 Личный прокси бесплатно входит в вашу подписку Compono VPN."
            if personal
            else "🎁 Прокси бесплатно входит в вашу подписку Compono VPN."
        )
        return ["", head] + ([DEVICES_LINE] if personal else [])
    until = format_date(view.expires_at)
    noun = "Личный прокси" if personal else "Прокси"
    head = f"✅ {noun} действует до {until}." if until else f"✅ {noun} подключён."
    return ["", head] + ([DEVICES_LINE] if personal else [])


def build_proxy_message(view: ProxyView) -> str:
    lines = ["<b>📡 Прокси для Telegram</b>\n"]
    if not view.proxies and not view.can_buy:
        lines.append("Нет доступных прокси.")
        return "\n".join(lines)
    lines.append(INTRO + "\n")
    lines.append(VPN_WARNING)
    lines.extend(status_lines(view))
    lines.append("")
    lines.extend(_links_block(view))
    lines.append("\n" + CLOSING)
    if view.can_buy:
        lines.extend(offer_lines(view.price_text))
    return "\n".join(lines)


def build_success_message(view: ProxyView) -> str:
    lines = ["<b>✅ Оплата прошла успешно!</b>\n"]
    if not view.entitled:
        lines.append(
            "Личный прокси скоро появится. Откройте «📡 Прокси для Telegram»"
            " в главном меню через минуту."
        )
        return "\n".join(lines)
    until = format_date(view.expires_at)
    noun = "Личный прокси" if view.has_personal else "Прокси"
    if until:
        lines.append(f"{noun} действует до {until}.")
    if view.has_personal:
        lines.append(DEVICES_LINE)
    lines.append("")
    lines.append(VPN_WARNING + "\n")
    lines.extend(_links_block(view))
    lines.append("\n" + CLOSING)
    return "\n".join(lines)
