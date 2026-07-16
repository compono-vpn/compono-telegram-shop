"""Tests for billing API model deserialization."""

from __future__ import annotations

from src.infrastructure.billing.models import (
    BillingPlan,
    BillingPlanDuration,
    BillingPlanPrice,
    BillingPaymentGateway,
    BillingPromocode,
    BillingSubscription,
    BillingTGProxy,
)


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


class TestBillingPlanPascalCase:
    """BillingPlan uses PascalCase fields (Go JSON default). Code must use .ID not .id."""

    SAMPLE_PLAN = {
        "ID": 42,
        "OrderIndex": 1,
        "IsActive": True,
        "Type": "BOTH",
        "Availability": "ALL",
        "Name": "Test Plan",
        "TrafficLimit": 300,
        "DeviceLimit": 6,
        "TrafficLimitStrategy": "MONTH",
        "Durations": [
            {"ID": 1, "PlanID": 42, "Days": 30, "Prices": [{"ID": 1, "DurationID": 1, "Currency": "RUB", "Price": "119"}]}
        ],
    }

    def test_plan_id_is_pascalcase(self):
        """BillingPlan.ID must be accessible — .id must raise AttributeError."""
        plan = BillingPlan.model_validate(self.SAMPLE_PLAN)
        assert plan.ID == 42

    def test_plan_lowercase_id_raises(self):
        """Regression: on_get_trial used billing_plan.id which doesn't exist."""
        plan = BillingPlan.model_validate(self.SAMPLE_PLAN)
        assert not hasattr(plan, "id"), "BillingPlan should NOT have a lowercase .id attribute"

    def test_plan_name_is_pascalcase(self):
        plan = BillingPlan.model_validate(self.SAMPLE_PLAN)
        assert plan.Name == "Test Plan"
        assert not hasattr(plan, "name"), "BillingPlan should NOT have lowercase .name"

    def test_plan_durations_parsed(self):
        plan = BillingPlan.model_validate(self.SAMPLE_PLAN)
        assert len(plan.Durations) == 1
        assert plan.Durations[0].Days == 30
        assert plan.Durations[0].Prices[0].Price == "119"


class TestBillingGatewayPascalCase:
    """BillingPaymentGateway uses PascalCase fields."""

    def test_gateway_type_is_pascalcase(self):
        gw = BillingPaymentGateway(ID=1, Type="PLATEGA", Currency="RUB", IsActive=True)
        assert gw.Type == "PLATEGA"
        assert gw.IsActive is True
        assert not hasattr(gw, "type"), "should NOT have lowercase .type"


class TestBillingSubscriptionPascalCase:
    """BillingSubscription uses PascalCase fields."""

    def test_subscription_url_is_pascalcase(self):
        sub = BillingSubscription(ID=1, URL="https://example.com/sub/abc", Status="ACTIVE")
        assert sub.URL == "https://example.com/sub/abc"
        assert not hasattr(sub, "url"), "should NOT have lowercase .url"
