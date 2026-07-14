from __future__ import annotations

import ast
import glob
import re
from pathlib import Path

from fluent_compiler.bundle import FluentBundle

from src.infrastructure.billing.converters import billing_user_to_dto
from src.infrastructure.billing.models import BillingUser

GETTERS_PATH = Path("src/bot/routers/menu/getters.py")


def _bundle() -> FluentBundle:
    text = "\n".join(
        Path(f).read_text(encoding="utf-8") for f in glob.glob("assets/translations/ru/*.ftl")
    )
    return FluentBundle.from_string("ru", text, use_isolating=False)


def _menu_getter_base_data_keys() -> set[str]:
    tree = ast.parse(GETTERS_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "base_data" for t in node.targets
        ):
            if isinstance(node.value, ast.Dict):
                return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    raise AssertionError("base_data dict not found in menu getter")


def _frg_user_externals() -> set[str]:
    text = Path("assets/translations/ru/utils.ftl").read_text(encoding="utf-8")
    match = re.search(r"^frg-user\s*=(.*?)(?=^[A-Za-z0-9#])", text, flags=re.MULTILINE | re.DOTALL)
    assert match, "frg-user missing from utils.ftl"
    return set(re.findall(r"\{\s*\$([A-Za-z_][A-Za-z0-9_]*)\s*\}", match.group(1)))


def test_billing_user_loyalty_discount_maps_to_dto() -> None:
    dto = billing_user_to_dto(BillingUser(TelegramID=1, LoyaltyDiscount=30))
    assert dto.loyalty_discount == 30


def test_frg_user_externals_supplied_by_menu_getter() -> None:
    missing = _frg_user_externals() - _menu_getter_base_data_keys()
    assert not missing, f"frg-user references externals not in menu getter base_data: {missing}"


def test_frg_user_shows_loyalty_discount_when_set() -> None:
    value, errors = _bundle().format(
        "frg-user",
        {"user_id": "1", "user_name": "Anton", "personal_discount": 0, "loyalty_discount": 30},
    )
    assert not errors
    assert "постоянного клиента" in value and "30" in value


def test_frg_user_hides_loyalty_discount_when_zero() -> None:
    value, errors = _bundle().format(
        "frg-user",
        {"user_id": "1", "user_name": "Anton", "personal_discount": 0, "loyalty_discount": 0},
    )
    assert not errors
    assert "постоянного клиента" not in value
