from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any, Callable, Optional

START_PREFIX = "source-"
START_VERSION_TAG = "a1"

CHANNEL_CODES = {
    "g": "google",
    "y": "yandex",
    "b": "bing",
    "dd": "duckduckgo",
    "tg": "telegram",
    "vk": "vk",
    "dr": "direct",
    "ot": "other",
}

CHANNEL_LABELS = {
    "google": "Google",
    "yandex": "Yandex",
    "bing": "Bing",
    "duckduckgo": "DuckDuckGo",
    "telegram": "Telegram",
    "vk": "VK",
}

LABEL_DIRECT = "Прямой заход"


@dataclass(frozen=True)
class DecodedStart:
    version: int
    slot: str
    channel: str = "direct"
    paid: bool = False
    landing_path: Optional[str] = None
    campaign: Optional[str] = None
    utm_source: Optional[str] = None
    host: Optional[str] = None


def _decode_host(value: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(value):
        if value[i] == "-":
            if i + 1 < len(value) and value[i + 1] == "-":
                out.append("-")
                i += 2
                continue
            out.append(".")
        else:
            out.append(value[i])
        i += 1
    return "".join(out)


def _path_of_slug(value: str) -> str:
    if value == "home":
        return "/"
    return "/" + "/".join(value.split("--"))


_SEGMENT_PARSERS: dict[str, tuple[str, Callable[[str], Any]]] = {
    "l": ("landing_path", _path_of_slug),
    "r": ("channel", lambda v: CHANNEL_CODES.get(v, "other")),
    "m": ("paid", lambda v: v == "p"),
    "c": ("campaign", lambda v: v),
    "s": ("utm_source", lambda v: v),
    "h": ("host", _decode_host),
}


def decode_start_param(param: Optional[str]) -> Optional[DecodedStart]:
    """Decode a `/start` payload produced by the landing (see compono-landing
    src/lib/attribution-core.ts). Legacy payloads (`source-home-hero`) decode
    to version 0 with the whole tag as the slot. Anything not starting with
    `source-` is not an attribution payload and returns None."""
    if not param:
        return None
    raw = param.strip()
    if not raw.startswith(START_PREFIX):
        return None
    body = raw[len(START_PREFIX) :]
    if not body:
        return None
    segments = body.split("_")
    if segments[0] != START_VERSION_TAG:
        return DecodedStart(version=0, slot=body)
    if len(segments) < 2 or not segments[1]:
        return None

    fields: dict[str, Any] = {"slot": segments[1]}
    for segment in segments[2:]:
        key, value = segment[:1], segment[1:]
        parser = _SEGMENT_PARSERS.get(key)
        if value and parser:
            name, convert = parser
            fields[name] = convert(value)
    return DecodedStart(version=1, **fields)


def touch_from_decoded(decoded: DecodedStart) -> dict[str, Any]:
    """Billing `AttributionTouch` JSON for a decoded start payload."""
    touch: dict[str, Any] = {"ref": decoded.slot}
    if decoded.version == 0:
        return touch
    touch["channel"] = decoded.channel
    if decoded.landing_path:
        touch["landing_path"] = decoded.landing_path
    if decoded.campaign:
        touch["utm_campaign"] = decoded.campaign
    if decoded.utm_source:
        touch["utm_source"] = decoded.utm_source
    if decoded.paid:
        touch["utm_medium"] = "paid"
    if decoded.host:
        touch["referrer_host"] = decoded.host
    return touch


def attribution_from_touch(touch: dict[str, Any]) -> dict[str, Any]:
    return {"first_touch": touch, "last_touch": touch}


def legacy_line(tag: str) -> str:
    if tag.startswith("channel_"):
        return f"Telegram → пост в канале ({tag})"
    if tag.startswith("utm_telegram_paid"):
        return f"Telegram (реклама) → {tag}"
    if tag.startswith(("home-", "site-")):
        return f"Сайт → {tag}"
    if tag.startswith("aff-"):
        return f"Партнёр → {tag}"
    return f"Метка → {tag}"


def human_line(
    *,
    channel: str = "",
    paid: bool = False,
    host: str = "",
    landing_path: str = "",
    cta: str = "",
    campaign: str = "",
    legacy_tag: str = "",
) -> str:
    if legacy_tag:
        return legacy_line(legacy_tag)
    if channel in ("", "direct"):
        label = LABEL_DIRECT
    elif channel == "other":
        label = host or "Другой сайт"
    else:
        label = CHANNEL_LABELS.get(channel, channel)
    if paid and channel not in ("", "direct"):
        label += " (реклама)"
    parts = [label]
    if landing_path:
        parts.append(landing_path)
    if cta:
        parts.append(cta)
    line = " → ".join(parts)
    if campaign:
        line += f" · {campaign}"
    return line


def source_line_for_start(param: Optional[str]) -> str:
    """The HTML-safe human line for a /start payload; `Прямой заход` when the
    user came without any attribution payload."""
    decoded = decode_start_param(param)
    if decoded is None:
        return LABEL_DIRECT
    if decoded.version == 0:
        return html.escape(human_line(legacy_tag=decoded.slot))
    return html.escape(
        human_line(
            channel=decoded.channel,
            paid=decoded.paid,
            host=decoded.host or "",
            landing_path=decoded.landing_path or "",
            cta=decoded.slot,
            campaign=decoded.campaign or "",
        )
    )


def source_tag(decoded: Optional[DecodedStart]) -> Optional[str]:
    """Value for the legacy `users.source` column: the CTA slot, which is the
    same string the pre-attribution links carried (`home-hero`)."""
    return decoded.slot if decoded else None
