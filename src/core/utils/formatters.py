from __future__ import annotations

from typing import TYPE_CHECKING

from fluentogram import TranslatorRunner

from src.core.constants import UNLIMITED
from src.core.i18n_keys import ByteUnitKey, TimeUnitKey

if TYPE_CHECKING:
    from src.infrastructure.database.models.dto import UserDto

from math import ceil
from typing import Union


def format_log_user(user: UserDto) -> str:
    return f"[{user.role.upper()}:{user.telegram_id} ({user.name})]"


def format_bytes(
    value: int,
    i18n: TranslatorRunner,
    round_up: bool = False,
    min_unit: ByteUnitKey = ByteUnitKey.GIGABYTE,
) -> str:
    size = float(value)
    started = False

    for unit in ByteUnitKey:
        if unit == min_unit:
            started = True

        if not started:
            size /= 1024
            continue

        if size < 1024:
            if round_up and not size.is_integer():
                size = ceil(size)
            size_str = str(int(size)) if size.is_integer() else str(round(size, 2))
            unit_str = i18n.get(str(unit), {"value": float(size_str)})
            return f"{size_str} {unit_str}"

        size /= 1024

    size_str = str(int(size)) if size.is_integer() else str(round(size, 2))
    unit_str = i18n.get(str(ByteUnitKey.TERABYTE), {"value": float(size_str)})
    return f"{size_str} {unit_str}"


def format_percent(part: int, whole: int) -> str:
    if whole == 0:
        return "N/A"

    percent = (part / whole) * 100
    return f"{percent:.2f}"


def format_duration(
    seconds: Union[int, float],
    i18n: TranslatorRunner,
    round_up: bool = False,
) -> str:
    units = [
        (TimeUnitKey.DAY, 86400),
        (TimeUnitKey.HOUR, 3600),
        (TimeUnitKey.MINUTE, 60),
    ]

    remaining = int(seconds)

    for i, (unit, unit_seconds) in enumerate(units):
        value, mod = divmod(remaining, unit_seconds)
        if value > 0:
            if round_up:
                if mod > 0 or any(divmod(remaining, u[1])[0] > 0 for u in units[i + 1 :]):
                    value = ceil(remaining / unit_seconds)
                return i18n.get(unit, value=value)

            parts = [i18n.get(unit, value=value)]
            remaining %= unit_seconds
            for unit2, unit_seconds2 in units[i + 1 :]:
                value2, _ = divmod(remaining, unit_seconds2)
                if value2 > 0:
                    parts.append(i18n.get(unit2, value=value2))
                    remaining %= unit_seconds2
            return " ".join(parts)

    return i18n.get(TimeUnitKey.MINUTE, value=0)


def format_country_code(code: str) -> str:
    if not code.isalpha() or len(code) != 2:
        return "🏴‍☠️"

    return "".join(chr(ord("🇦") + ord(c.upper()) - ord("A")) for c in code)


def format_subscription_period(days: int, i18n: TranslatorRunner) -> str:
    if days == -1:
        return UNLIMITED

    if days % 365 == 0:
        value = days // 365
        return i18n.get(TimeUnitKey.YEAR, value=value)

    if days % 30 == 0:
        value = days // 30
        return i18n.get(TimeUnitKey.MONTH, value=value)

    return i18n.get(TimeUnitKey.DAY, value=days)
