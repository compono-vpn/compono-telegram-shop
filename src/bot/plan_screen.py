"""Text and button labels of the plan list and the duration list (owner redesign 2026-11-18).

Pure functions, no fluent: fluent formats numbers with thin-space digit groups ("1 024 ГБ"),
so the plan screens build their strings here.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from html import escape
from typing import Optional

from aiogram.enums import ButtonStyle

from src.services.dedicated_ip import is_ultra_tag
from src.services.payment_nudge import format_price_text

MONTH_DAYS = 30
YEAR_DAYS = 365
DEDICATED_IP_LINE = "личный IP (Швеция или Нидерланды)"

# Every plan button gets a colour, so plans never look like the default (black in the dark theme)
# navigation buttons «Назад» / «Главное меню». Bot API has three styles only.
PLAN_STYLE_BY_ID = {
    1: ButtonStyle.SUCCESS.value,  # Старт: green
    2: ButtonStyle.PRIMARY.value,  # Про: blue
    3: ButtonStyle.DANGER.value,  # Макс: red
}
ULTRA_STYLE = ButtonStyle.PRIMARY.value  # Ультра: blue, never the default style
FALLBACK_STYLE = ButtonStyle.SUCCESS.value


def plural_ru(n: int, one: str, few: str, many: str) -> str:
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def format_traffic(gb: int) -> str:
    if gb is None or gb < 0 or gb == 0:
        return "безлимитный трафик"
    if gb >= 1024:
        tb = Decimal(gb) / Decimal(1024)
        text = f"{tb:.1f}".rstrip("0").rstrip(".")
        return f"{text} ТБ"
    return f"{gb} ГБ"


def format_devices(n: int) -> str:
    if n is None or n < 0:
        return "без лимита устройств"
    return f"{n} {plural_ru(n, 'устройство', 'устройства', 'устройств')}"


def format_period(days: int) -> str:
    if days == -1:
        return "Навсегда"
    if days % YEAR_DAYS == 0:
        years = days // YEAR_DAYS
        return f"{years} {plural_ru(years, 'год', 'года', 'лет')}"
    if days % MONTH_DAYS == 0:
        months = days // MONTH_DAYS
        return f"{months} {plural_ru(months, 'месяц', 'месяца', 'месяцев')}"
    return f"{days} {plural_ru(days, 'день', 'дня', 'дней')}"


def split_name(name: str) -> tuple[str, str]:
    """'⚡️ Старт' -> ('⚡', 'Старт'). A name without a leading emoji gives ('', name)."""
    head, _, rest = name.strip().partition(" ")
    if rest and not any(ch.isalnum() for ch in head):
        return head.replace("️", ""), rest.strip()
    return "", name.strip()


def _title(emoji: str, title: str) -> str:
    bold = f"<b>{escape(title)}</b>"
    return f"{emoji} {bold}" if emoji else bold


def plan_style(plan_id: Optional[int], tag: Optional[str]) -> str:
    if is_ultra_tag(tag):
        return ULTRA_STYLE
    return PLAN_STYLE_BY_ID.get(plan_id or 0, FALLBACK_STYLE)


def limits_line(traffic_gb: int, devices: int, ultra: bool) -> str:
    parts = [format_traffic(traffic_gb), format_devices(devices)]
    if ultra:
        parts.append(DEDICATED_IP_LINE)
    return " · ".join(parts)


def price_suffix(days: Optional[int]) -> str:
    if days == MONTH_DAYS:
        return "/мес"
    if days is None:
        return ""
    return f" / {format_period(days)}"


@dataclass
class PlanRow:
    plan_id: Optional[int]
    name: str
    tag: Optional[str]
    traffic_gb: int
    devices: int
    price: Optional[Decimal]  # final price for `days`, None when it could not be priced
    days: Optional[int]
    currency: str
    discount_percent: int = 0

    @property
    def ultra(self) -> bool:
        return is_ultra_tag(self.tag)

    def price_text(self) -> str:
        if self.price is None:
            return ""
        if self.price <= 0:
            return "бесплатно"
        return format_price_text(self.price, self.currency)

    def block(self) -> str:
        emoji, title = split_name(self.name)
        head = _title(emoji, title)
        price = self.price_text()
        if price:
            suffix = price_suffix(self.days) if self.price and self.price > 0 else ""
            head = f"{head} — {price}{suffix}"
        return f"{head}\n{limits_line(self.traffic_gb, self.devices, self.ultra)}"

    def button(self) -> str:
        emoji, title = split_name(self.name)
        label = f"{emoji} {title}" if emoji else title
        price = self.price_text()
        return f"{label} · {price}" if price else label


def discount_line(percents: list[int]) -> str:
    applied = sorted({p for p in percents if p > 0})
    if not applied:
        return ""
    if len(applied) == 1:
        return f"🎁 Ваша скидка {applied[0]}% уже учтена"
    return "🎁 Ваша скидка уже учтена"


def plans_text(rows: list[PlanRow]) -> str:
    lines = ["<b>Выберите тариф</b>"]
    discount = discount_line([r.discount_percent for r in rows])
    if discount:
        lines.append(discount)
    for row in rows:
        lines += ["", row.block()]
    return "\n".join(lines)


@dataclass
class DurationRow:
    days: int
    price: Decimal
    currency: str
    saving_percent: int = 0

    def button(self) -> str:
        period = format_period(self.days)
        if self.price <= 0:
            return f"{period} — 🎁 бесплатно"
        text = f"{period} — {format_price_text(self.price, self.currency)}"
        if self.saving_percent > 0:
            text = f"{text} (−{self.saving_percent}%)"
        return text


def saving_percent(days: int, price: Decimal, month_price: Optional[Decimal]) -> int:
    """How much cheaper per month this period is than paying for 1 month each time."""
    if not month_price or month_price <= 0 or days <= MONTH_DAYS or price <= 0:
        return 0
    months = Decimal(12) if days == YEAR_DAYS else Decimal(days) / Decimal(MONTH_DAYS)
    full = month_price * months
    if full <= 0:
        return 0
    percent = int(((full - price) / full * 100).to_integral_value(rounding="ROUND_HALF_UP"))
    return percent if percent > 0 else 0


def duration_text(plan: PlanRow, discount_percent: int) -> str:
    emoji, title = split_name(plan.name)
    head = _title(emoji, title)
    lines = ["<b>Выберите срок</b>"]
    discount = discount_line([discount_percent])
    if discount:
        lines.append(discount)
    lines += ["", head, limits_line(plan.traffic_gb, plan.devices, plan.ultra)]
    return "\n".join(lines)
