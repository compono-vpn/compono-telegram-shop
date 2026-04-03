"""Tests for PricingService -- verifies price calculation, currency rules, and parsing."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import make_user

from src.core.enums import Currency
from src.models.dto.transaction import PriceDetailsDto
from src.models.dto.user import UserDto
from src.services.pricing import PricingService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service() -> PricingService:
    config = MagicMock()
    redis_client = AsyncMock()
    redis_repository = MagicMock()
    return PricingService(
        config=config,
        redis_client=redis_client,
        redis_repository=redis_repository,
    )


def _make_user_with_discount(
    personal_discount: int = 0,
    purchase_discount: int = 0,
    purchase_discount_max_days: int = 0,
) -> UserDto:
    user = make_user()
    user.personal_discount = personal_discount
    user.purchase_discount = purchase_discount
    user.purchase_discount_max_days = purchase_discount_max_days
    return user


# ---------------------------------------------------------------------------
# Tests: calculate -- happy path
# ---------------------------------------------------------------------------


class TestCalculateHappyPath:

    def test_no_discount_returns_original_price(self):
        svc = _make_service()
        user = _make_user_with_discount()
        result = svc.calculate(user, Decimal("100"), Currency.XTR)

        assert isinstance(result, PriceDetailsDto)
        assert result.original_amount == Decimal("100")
        assert result.final_amount == Decimal("100")
        assert result.discount_percent == 0

    def test_personal_discount_applied(self):
        svc = _make_service()
        user = _make_user_with_discount(personal_discount=20)
        result = svc.calculate(user, Decimal("100"), Currency.XTR)

        assert result.original_amount == Decimal("100")
        assert result.discount_percent == 20
        assert result.final_amount == Decimal("80")

    def test_purchase_discount_takes_precedence_over_personal(self):
        svc = _make_service()
        user = _make_user_with_discount(personal_discount=10, purchase_discount=30)
        result = svc.calculate(user, Decimal("100"), Currency.XTR)

        assert result.discount_percent == 30
        assert result.final_amount == Decimal("70")

    def test_purchase_discount_skipped_if_duration_exceeds_max(self):
        svc = _make_service()
        user = _make_user_with_discount(
            personal_discount=10,
            purchase_discount=30,
            purchase_discount_max_days=30,
        )
        result = svc.calculate(user, Decimal("100"), Currency.XTR, duration_days=60)

        # purchase_discount should be zeroed; personal_discount (10) used instead
        assert result.discount_percent == 10
        assert result.final_amount == Decimal("90")

    def test_purchase_discount_applied_if_duration_within_max(self):
        svc = _make_service()
        user = _make_user_with_discount(
            purchase_discount=20,
            purchase_discount_max_days=60,
        )
        result = svc.calculate(user, Decimal("100"), Currency.XTR, duration_days=30)

        assert result.discount_percent == 20
        assert result.final_amount == Decimal("80")

    def test_purchase_discount_applied_when_no_max_days_set(self):
        """purchase_discount_max_days=0 means no limit."""
        svc = _make_service()
        user = _make_user_with_discount(purchase_discount=15, purchase_discount_max_days=0)
        result = svc.calculate(user, Decimal("200"), Currency.XTR, duration_days=365)

        assert result.discount_percent == 15
        assert result.final_amount == Decimal("170")


# ---------------------------------------------------------------------------
# Tests: calculate -- edge cases
# ---------------------------------------------------------------------------


class TestCalculateEdgeCases:

    def test_zero_price_returns_zeros(self):
        svc = _make_service()
        user = _make_user_with_discount(personal_discount=50)
        result = svc.calculate(user, Decimal("0"), Currency.XTR)

        assert result.original_amount == Decimal("0")
        assert result.final_amount == Decimal("0")
        assert result.discount_percent == 0

    def test_negative_price_returns_zeros(self):
        svc = _make_service()
        user = _make_user_with_discount()
        result = svc.calculate(user, Decimal("-10"), Currency.XTR)

        assert result.original_amount == Decimal("0")
        assert result.final_amount == Decimal("0")

    def test_100_percent_discount_returns_free(self):
        svc = _make_service()
        user = _make_user_with_discount(personal_discount=100)
        result = svc.calculate(user, Decimal("500"), Currency.XTR)

        assert result.original_amount == Decimal("500")
        assert result.discount_percent == 100
        assert result.final_amount == Decimal("0")
        assert result.is_free is True

    def test_discount_over_100_capped(self):
        svc = _make_service()
        user = _make_user_with_discount(personal_discount=150)
        result = svc.calculate(user, Decimal("100"), Currency.XTR)

        assert result.discount_percent == 100
        assert result.final_amount == Decimal("0")

    def test_discount_so_small_rounding_equals_original_resets_discount(self):
        """If after currency rounding the final equals original, discount_percent is set to 0."""
        svc = _make_service()
        # 1% of 1 XTR = 0.01, rounds down to 0 for XTR (integer), so final = max(1, 1) = 1
        user = _make_user_with_discount(personal_discount=1)
        result = svc.calculate(user, Decimal("1"), Currency.XTR)

        # After 1% discount: 0.99, rounds to 0 for XTR int, min enforced to 1
        # final_amount == original -> discount_percent set to 0
        assert result.final_amount == Decimal("1")
        assert result.discount_percent == 0

    def test_none_discounts_treated_as_zero(self):
        """When both discount fields are 0 (or None-like), no discount applied."""
        svc = _make_service()
        user = make_user()
        user.personal_discount = 0
        user.purchase_discount = 0
        result = svc.calculate(user, Decimal("50"), Currency.USD)

        assert result.discount_percent == 0
        assert result.final_amount == Decimal("50.00")


# ---------------------------------------------------------------------------
# Tests: calculate -- currency-specific rounding
# ---------------------------------------------------------------------------


class TestCalculateCurrencyRounding:

    def test_xtr_rounds_down_to_integer(self):
        svc = _make_service()
        user = _make_user_with_discount(personal_discount=15)
        # 85% of 99 = 84.15, should round down to 84
        result = svc.calculate(user, Decimal("99"), Currency.XTR)

        assert result.final_amount == Decimal("84")

    def test_rub_rounds_down_to_integer(self):
        svc = _make_service()
        user = _make_user_with_discount(personal_discount=10)
        # 90% of 999 = 899.1, should round down to 899
        result = svc.calculate(user, Decimal("999"), Currency.RUB)

        assert result.final_amount == Decimal("899")

    def test_usd_rounds_to_two_decimals(self):
        svc = _make_service()
        user = _make_user_with_discount(personal_discount=15)
        # 85% of 9.99 = 8.4915, should round to 8.49
        result = svc.calculate(user, Decimal("9.99"), Currency.USD)

        assert result.final_amount == Decimal("8.49")


# ---------------------------------------------------------------------------
# Tests: apply_currency_rules
# ---------------------------------------------------------------------------


class TestApplyCurrencyRules:

    def test_xtr_truncates_to_integer(self):
        svc = _make_service()
        assert svc.apply_currency_rules(Decimal("5.99"), Currency.XTR) == Decimal("5")

    def test_rub_truncates_to_integer(self):
        svc = _make_service()
        assert svc.apply_currency_rules(Decimal("123.78"), Currency.RUB) == Decimal("123")

    def test_usd_rounds_to_two_decimals(self):
        svc = _make_service()
        assert svc.apply_currency_rules(Decimal("1.999"), Currency.USD) == Decimal("2.00")

    def test_usd_preserves_two_decimals(self):
        svc = _make_service()
        assert svc.apply_currency_rules(Decimal("1.50"), Currency.USD) == Decimal("1.50")

    def test_xtr_enforces_minimum_1(self):
        svc = _make_service()
        assert svc.apply_currency_rules(Decimal("0.5"), Currency.XTR) == Decimal("1")

    def test_rub_enforces_minimum_1(self):
        svc = _make_service()
        assert svc.apply_currency_rules(Decimal("0.1"), Currency.RUB) == Decimal("1")

    def test_usd_enforces_minimum_001(self):
        svc = _make_service()
        assert svc.apply_currency_rules(Decimal("0.001"), Currency.USD) == Decimal("0.01")

    def test_xtr_zero_becomes_minimum(self):
        svc = _make_service()
        assert svc.apply_currency_rules(Decimal("0"), Currency.XTR) == Decimal("1")

    def test_usd_zero_becomes_minimum(self):
        svc = _make_service()
        assert svc.apply_currency_rules(Decimal("0"), Currency.USD) == Decimal("0.01")


# ---------------------------------------------------------------------------
# Tests: parse_price
# ---------------------------------------------------------------------------


class TestParsePrice:

    def test_valid_integer_price(self):
        svc = _make_service()
        result = svc.parse_price("100", Currency.XTR)
        assert result == Decimal("100")

    def test_valid_decimal_price_usd(self):
        svc = _make_service()
        result = svc.parse_price("9.99", Currency.USD)
        assert result == Decimal("9.99")

    def test_strips_whitespace(self):
        svc = _make_service()
        result = svc.parse_price("  50  ", Currency.XTR)
        assert result == Decimal("50")

    def test_zero_returns_zero(self):
        svc = _make_service()
        result = svc.parse_price("0", Currency.XTR)
        assert result == Decimal("0")

    def test_negative_raises_value_error(self):
        svc = _make_service()
        with pytest.raises(ValueError, match="Negative price"):
            svc.parse_price("-5", Currency.XTR)

    def test_invalid_format_raises_value_error(self):
        svc = _make_service()
        with pytest.raises(ValueError, match="Invalid numeric format"):
            svc.parse_price("abc", Currency.XTR)

    def test_empty_string_raises_value_error(self):
        svc = _make_service()
        with pytest.raises(ValueError, match="Invalid numeric format"):
            svc.parse_price("", Currency.XTR)

    def test_applies_currency_rules_after_parsing(self):
        svc = _make_service()
        # 5.99 for XTR should truncate to 5
        result = svc.parse_price("5.99", Currency.XTR)
        assert result == Decimal("5")

    def test_small_valid_price_enforces_minimum(self):
        svc = _make_service()
        # 0.001 for USD -> min 0.01
        result = svc.parse_price("0.001", Currency.USD)
        assert result == Decimal("0.01")
