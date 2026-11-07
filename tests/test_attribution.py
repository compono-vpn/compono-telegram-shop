from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.bot.middlewares.user import UserMiddleware
from src.core.utils.attribution import (
    attribution_from_touch,
    decode_start_param,
    human_line,
    source_line_for_start,
    source_tag,
    touch_from_decoded,
)

FIXTURES = Path(__file__).parent / "fixtures"
VECTORS = json.loads((FIXTURES / "attribution-vectors.json").read_text(encoding="utf-8"))
LINES = json.loads((FIXTURES / "human-line-vectors.json").read_text(encoding="utf-8"))

FIELD_MAP = {
    "slot": "slot",
    "version": "version",
    "channel": "channel",
    "paid": "paid",
    "landingPath": "landing_path",
    "campaign": "campaign",
    "utmSource": "utm_source",
    "host": "host",
}


@pytest.mark.parametrize("vector", VECTORS["decode"], ids=lambda v: v["param"] or "empty")
def test_decode_matches_shared_vectors(vector: dict) -> None:
    got = decode_start_param(vector["param"])
    if "decoded" in vector:
        assert got is None
        return
    assert got is not None
    for key, value in vector.items():
        if key == "param":
            continue
        assert getattr(got, FIELD_MAP[key]) == value, key


@pytest.mark.parametrize("vector", VECTORS["startParam"], ids=lambda v: v["param"])
def test_every_landing_encoded_param_decodes_to_its_inputs(vector: dict) -> None:
    got = decode_start_param(vector["param"])
    assert got is not None and got.version == 1
    source = vector["input"]
    assert got.slot == source["slot"].lower()
    if source.get("channel") and source["channel"] != "direct":
        assert got.channel == source["channel"]


@pytest.mark.parametrize("vector", LINES, ids=lambda v: v["name"])
def test_human_line_matches_shared_vectors(vector: dict) -> None:
    got = human_line(
        channel=vector.get("channel", ""),
        paid=vector.get("paid", False),
        host=vector.get("host", ""),
        landing_path=vector.get("landing_path", ""),
        cta=vector.get("cta", ""),
        campaign=vector.get("campaign", ""),
        legacy_tag=vector.get("legacy_tag", ""),
    )
    assert got == vector["line"]


def test_event_line_examples_from_start_payloads() -> None:
    assert source_line_for_start("source-a1_home-hero_lios_rg") == "Google → /ios → home-hero"
    assert source_line_for_start("source-home-hero") == "Сайт → home-hero"
    assert (
        source_line_for_start("source-channel_proxy") == "Telegram → пост в канале (channel_proxy)"
    )
    assert source_line_for_start(None) == "Прямой заход"
    assert source_line_for_start("ref_abc") == "Прямой заход"


def test_touch_and_legacy_source_tag() -> None:
    decoded = decode_start_param("source-a1_home-steps_lvpn-dlya-rossii_ry_mp_cwinter-sale_syandex")
    assert decoded is not None
    touch = touch_from_decoded(decoded)
    assert touch == {
        "ref": "home-steps",
        "channel": "yandex",
        "landing_path": "/vpn-dlya-rossii",
        "utm_campaign": "winter-sale",
        "utm_source": "yandex",
        "utm_medium": "paid",
    }
    assert attribution_from_touch(touch)["first_touch"] is touch
    assert source_tag(decoded) == "home-steps"
    assert source_tag(decode_start_param("source-home-hero")) == "home-hero"
    assert touch_from_decoded(decode_start_param("source-home-hero")) == {"ref": "home-hero"}
    assert source_tag(None) is None


def test_source_line_is_html_safe() -> None:
    decoded = decode_start_param("source-a1_x_rot_h1-2")
    assert decoded is not None
    assert "<" not in source_line_for_start("source-a1_x_rot_h1-2")


class TestUserMiddlewareAttribution:
    def test_source_column_keeps_the_legacy_slot_tag(self) -> None:
        event = SimpleNamespace(text="/start source-a1_home-hero_lios_rg")
        assert UserMiddleware._parse_source(event) == "home-hero"
        assert UserMiddleware._start_param(event) == "source-a1_home-hero_lios_rg"
        assert UserMiddleware._parse_source(
            SimpleNamespace(text="/start source-channel_proxy")
        ) == ("channel_proxy")
        assert UserMiddleware._parse_source(SimpleNamespace(text="/start")) is None
        assert UserMiddleware._parse_source(SimpleNamespace(text="/start ref_abc")) is None

    @pytest.mark.asyncio
    async def test_returning_user_records_a_last_touch(self) -> None:
        billing = SimpleNamespace(update_user=AsyncMock())
        event = SimpleNamespace(text="/start source-a1_home-hero_lios_rg")
        await UserMiddleware._record_returning_touch(billing, 42, event)
        billing.update_user.assert_awaited_once_with(
            42,
            {
                "attribution_touch": {
                    "ref": "home-hero",
                    "channel": "google",
                    "landing_path": "/ios",
                }
            },
        )

    @pytest.mark.asyncio
    async def test_returning_user_without_payload_or_command_records_nothing(self) -> None:
        billing = SimpleNamespace(update_user=AsyncMock())
        for text in ("/start", "hello source-a1_x", "/start ref_abc", None):
            await UserMiddleware._record_returning_touch(billing, 1, SimpleNamespace(text=text))
        billing.update_user.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_billing_failure_never_breaks_the_update(self) -> None:
        billing = SimpleNamespace(update_user=AsyncMock(side_effect=RuntimeError("down")))
        await UserMiddleware._record_returning_touch(
            billing, 1, SimpleNamespace(text="/start source-home-hero")
        )
