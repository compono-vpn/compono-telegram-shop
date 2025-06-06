from math import ceil
from typing import Union

from app.bot.middlewares.i18n import I18nFormatter

from .enums import ByteUnit, TimeUnit


def format_bytes(
    value: int,
    i18n_format: I18nFormatter,
    round_up: bool = False,
    min_unit: ByteUnit = ByteUnit.GIGABYTE,
) -> str:
    size = float(value)
    started = False

    for unit in ByteUnit:
        if unit == min_unit:
            started = True

        if not started:
            size /= 1024
            continue

        if size < 1024:
            if round_up and not size.is_integer():
                size = ceil(size)
            size_str = str(int(size)) if size.is_integer() else str(round(size, 2))
            unit_str = i18n_format(str(unit), {"value": float(size_str)})
            return f"{size_str} {unit_str}"

        size /= 1024

    size_str = str(int(size)) if size.is_integer() else str(round(size, 2))
    unit_str = i18n_format(str(ByteUnit.TERABYTE), {"value": float(size_str)})
    return f"{size_str} {unit_str}"


def format_percent(part: int, whole: int) -> str:
    if whole == 0:
        return "N/A"

    percent = (part / whole) * 100
    return f"{percent:.2f}"


def format_duration(
    seconds: Union[int, float],
    i18n_format: I18nFormatter,
    round_up: bool = False,
) -> str:
    units = [
        (TimeUnit.DAY, 86400),
        (TimeUnit.HOUR, 3600),
        (TimeUnit.MINUTE, 60),
    ]

    remaining = int(seconds)

    for i, (unit, unit_seconds) in enumerate(units):
        value, mod = divmod(remaining, unit_seconds)
        if value > 0:
            if round_up:
                if mod > 0 or any(divmod(remaining, u[1])[0] > 0 for u in units[i + 1 :]):
                    value = ceil(remaining / unit_seconds)
                return f"{value} {i18n_format(unit.value, {'value': value})}"

            parts = [f"{value} {i18n_format(unit.value, {'value': value})}"]
            remaining %= unit_seconds
            for unit2, unit_seconds2 in units[i + 1 :]:
                value2, _ = divmod(remaining, unit_seconds2)
                if value2 > 0:
                    parts.append(f"{value2} {i18n_format(unit2.value, {'value': value2})}")
                    remaining %= unit_seconds2
            return " ".join(parts)

    return f"0 {i18n_format(TimeUnit.MINUTE.value, {'value': 0})}"


def format_country_code(code: str) -> str:
    if not code.isalpha() or len(code) != 2:
        return "🏴‍☠️"

    return "".join(chr(ord("🇦") + ord(c.upper()) - ord("A")) for c in code)
