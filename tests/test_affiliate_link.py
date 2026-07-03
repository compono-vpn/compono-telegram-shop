"""Tests for affiliate link minting (BDT-437)."""

from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from src.bot.middlewares.user import UserMiddleware
from src.core.utils.formatters import affiliate_link, affiliate_slug


class TestAffiliateHelpers:
    def test_slug(self):
        assert affiliate_slug("xyz") == "aff-xyz"

    def test_link(self):
        assert affiliate_link("compono_bot", "xyz") == (
            "https://t.me/compono_bot?start=source-aff-xyz"
        )

    def test_link_strips_at(self):
        assert affiliate_link("@compono_bot", "xyz") == affiliate_link("compono_bot", "xyz")


class TestAffiliateRoundTrip:
    """The link a partner shares must yield source 'aff-<id>' when the invitee /starts."""

    def test_start_param_parses_back_to_affiliate_source(self):
        link = affiliate_link("compono_bot", "creator42")
        start_param = parse_qs(urlparse(link).query)["start"][0]
        assert start_param == "source-aff-creator42"

        fake_event = SimpleNamespace(text=f"/start {start_param}")
        assert UserMiddleware._parse_source(fake_event) == "aff-creator42"
