"""Tests for billing API model deserialization."""

from __future__ import annotations

from src.infrastructure.billing.models import BillingTGProxy


class TestBillingTGProxy:
    """BillingTGProxy must parse the actual JSON format from the Go billing API."""

    def test_parses_lowercase_json_keys(self):
        """The Go billing API returns lowercase JSON keys (id, server, port, etc.)."""
        raw = {
            "id": 1,
            "server": "176.108.250.74",
            "port": 443,
            "secret": "abc123",
            "link": "tg://proxy?server=176.108.250.74&port=443&secret=abc123",
            "eligible_plan_ids": [2, 3],
            "is_active": True,
        }
        proxy = BillingTGProxy.model_validate(raw)

        assert proxy.server == "176.108.250.74"
        assert proxy.port == 443
        assert proxy.secret == "abc123"
        assert proxy.link == "tg://proxy?server=176.108.250.74&port=443&secret=abc123"

    def test_server_not_empty_after_parsing(self):
        """Regression: PascalCase model fields caused empty server/port from lowercase JSON."""
        raw = {"id": 1, "server": "1.2.3.4", "port": 443, "secret": "x", "link": "tg://proxy?server=1.2.3.4&port=443&secret=x"}
        proxy = BillingTGProxy.model_validate(raw)

        assert proxy.server != "", "server should not be empty after parsing lowercase JSON"
        assert proxy.port != 0, "port should not be 0 after parsing lowercase JSON"
