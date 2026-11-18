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


class TestAndroidTvDeepLinkAttribution:
    """Owner default 2026-11-18 (COM-202): a /start tv-<CODE> link from the TV's QR code
    is attributed to the source ``androidtv``. The pairing code itself is a short-lived
    secret and must never end up in the source column or the attribution touch."""

    CODE = "K7M4QX9P"

    def test_tv_payload_decodes_to_androidtv(self) -> None:
        for param in (f"tv-{self.CODE}", f"TV-{self.CODE.lower()}", f" tv-{self.CODE} "):
            decoded = decode_start_param(param)
            assert decoded is not None, param
            assert source_tag(decoded) == "androidtv"
            touch = touch_from_decoded(decoded)
            assert touch == {"ref": "androidtv"}
            assert self.CODE not in json.dumps(touch).upper()

    def test_new_user_source_and_admin_line(self) -> None:
        event = SimpleNamespace(text=f"/start tv-{self.CODE}")
        assert UserMiddleware._parse_source(event) == "androidtv"
        line = source_line_for_start(f"tv-{self.CODE}")
        assert "androidtv" in line
        assert self.CODE not in line.upper()

    @pytest.mark.asyncio
    async def test_returning_user_gets_an_androidtv_last_touch(self) -> None:
        billing = SimpleNamespace(update_user=AsyncMock())
        await UserMiddleware._record_returning_touch(
            billing, 42, SimpleNamespace(text=f"/start tv-{self.CODE}")
        )
        billing.update_user.assert_awaited_once_with(
            42, {"attribution_touch": {"ref": "androidtv"}}
        )

    def test_other_payloads_are_unchanged(self) -> None:
        # Only a payload the TV handler accepts as a code is a TV link; malformed ones open
        # the normal main menu and stay unattributed, as before.
        for bad in ("tv-", "tv-ABC", "tv-ILOU1234", "tv-ABCDEFGH9", "tv-ABCD-EFGH", "xtv-ABCDEFGH"):
            assert decode_start_param(bad) is None, bad
        assert decode_start_param("tvx") is None
        assert decode_start_param("ref_abc") is None
        assert source_tag(decode_start_param("source-home-hero")) == "home-hero"
