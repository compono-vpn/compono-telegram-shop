"""Tests for the Plaidly crypto asset registry and subscription dialog wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram_dialog.widgets.kbd import Group, Select, Url, WebApp

from src.bot.routers.subscription.dialog import confirm, crypto_asset, router
from src.bot.routers.subscription.handlers import (
    on_crypto_asset_select,
    on_payment_method_select,
)
from src.bot.states import Subscription
from src.core.constants import USER_KEY
from src.core.crypto_assets import (
    CRYPTO_ASSETS,
    CRYPTO_ASSETS_BY_ID,
    get_crypto_asset,
)
from src.core.enums import Currency, PaymentGatewayType
from src.models.dto import PlanDto
from src.models.dto.plan import PlanDurationDto
from tests.conftest import make_dialog_manager, make_experiment_service, make_user, unwrap_inject

EXPECTED = {
    "usdt-tron": ("tron", "USDT"),
    "usdt-ton": ("ton", "USDT"),
    "ton": ("ton", "TON"),
    "usdt-eth": ("ethereum", "USDT"),
    "usdc-eth": ("ethereum", "USDC"),
    "eth": ("ethereum", "ETH"),
    "sol": ("solana", "SOL"),
    "usdc-sol": ("solana", "USDC"),
    "usdt-bsc": ("bsc", "USDT"),
    "bnb": ("bsc", "BNB"),
    "pol": ("polygon", "POL"),
    "usdc-base": ("base", "USDC"),
    "usdc-arb": ("arbitrum", "USDC"),
    "usdc-op": ("optimism", "USDC"),
    "avax": ("avalanche", "AVAX"),
}


class TestCryptoAssetRegistry:
    def test_all_expected_options_present(self):
        assert {a.id for a in CRYPTO_ASSETS} == set(EXPECTED)

    def test_chain_token_mapping(self):
        for asset_id, (chain, token) in EXPECTED.items():
            asset = get_crypto_asset(asset_id)
            assert asset.chain == chain
            assert asset.token == token

    def test_ids_are_unique(self):
        ids = [a.id for a in CRYPTO_ASSETS]
        assert len(ids) == len(set(ids))

    def test_lookup_index_matches_tuple(self):
        assert set(CRYPTO_ASSETS_BY_ID) == {a.id for a in CRYPTO_ASSETS}
        for asset in CRYPTO_ASSETS:
            assert CRYPTO_ASSETS_BY_ID[asset.id] is asset

    def test_labels_non_empty_and_chains_supported(self):
        supported_chains = {
            "ethereum",
            "polygon",
            "bsc",
            "base",
            "arbitrum",
            "optimism",
            "avalanche",
            "solana",
            "tron",
            "ton",
        }
        for asset in CRYPTO_ASSETS:
            assert asset.label.strip()
            assert asset.chain in supported_chains

    def test_unknown_asset_raises(self):
        with pytest.raises(KeyError):
            get_crypto_asset("does-not-exist")


class TestPlaidlyEnum:
    def test_plaidly_gateway_exists(self):
        assert PaymentGatewayType.PLAIDLY.value == "PLAIDLY"

    def test_plaidly_maps_to_usd(self):
        assert Currency.from_gateway_type(PaymentGatewayType.PLAIDLY) is Currency.USD


def _collect(widgets, types):
    found = []

    def _walk(items):
        for w in items:
            if isinstance(w, types):
                found.append(w)
            inner = getattr(w, "buttons", None)
            if inner:
                _walk(inner)

    _walk(widgets)
    return found


class TestDialogWiring:
    def test_crypto_asset_window_registered(self):
        assert hasattr(Subscription, "CRYPTO_ASSET")
        assert crypto_asset.state == Subscription.CRYPTO_ASSET
        assert Subscription.CRYPTO_ASSET in router.states_group()

    def test_crypto_window_uses_select_over_assets(self):
        selects = _collect(crypto_asset.keyboard.buttons, Select)
        assert selects, "crypto asset window must contain a Select widget"
        sample = {"crypto_assets": [{"id": "eth", "label": "Ξ ETH"}]}
        assert any(s.items_getter(sample) == sample["crypto_assets"] for s in selects)

    def test_crypto_window_two_column_layout(self):
        groups = [w for w in crypto_asset.keyboard.buttons if isinstance(w, Group)]
        assert groups, "expected a Group wrapping the crypto Select"
        assert any(getattr(g, "width", None) == 2 for g in groups), "picker should be 2-column"

    def test_confirm_window_has_webapp_and_url_pay_buttons(self):
        kinds = {type(w).__name__ for w in _collect(confirm.keyboard.buttons, (Url, WebApp))}
        assert "WebApp" in kinds
        assert "Url" in kinds


def _plan_with_duration(days: int = 30) -> PlanDto:
    return PlanDto(id=42, name="Pro", durations=[PlanDurationDto(id=1, days=days, prices=[])])


def _make_billing(url: str = "https://checkout.plaidly.io/s/1") -> AsyncMock:
    billing = AsyncMock()
    billing.get_gateway_by_type.return_value = MagicMock(Currency="USD")
    billing.create_payment.return_value = MagicMock(ID="pay-1", URL=url)
    billing.calculate_price.return_value = MagicMock(
        original_amount="10",
        discount_percent=0,
        final_amount="10",
        base_discount_percent=0,
        channel_discount_percent=0,
        channel_discount_source="",
    )
    return billing


class _NoChannelIncentive:
    async def discount_context(self, user, **kwargs):
        return None


def _dm_for_crypto(plan: PlanDto) -> MagicMock:
    dm = make_dialog_manager()
    dm.middleware_data[USER_KEY] = make_user(telegram_id=777)
    dm.dialog_data["selected_duration"] = 30
    dm.dialog_data["purchase_type"] = "NEW"
    dm.dialog_data["plandto"] = plan.model_dump()
    dm.switch_to = AsyncMock()
    return dm


class TestOnPaymentMethodSelectPlaidly:
    async def test_plaidly_routes_to_crypto_asset_without_creating_payment(self):
        plan = _plan_with_duration()
        dm = _dm_for_crypto(plan)
        billing = _make_billing()
        ntf = AsyncMock()
        experiment_service = make_experiment_service()
        raw = unwrap_inject(on_payment_method_select)
        redis_client = AsyncMock()

        await raw(
            MagicMock(),
            MagicMock(),
            dm,
            PaymentGatewayType.PLAIDLY,
            billing,
            experiment_service,
            _NoChannelIncentive(),
            ntf,
            redis_client,
        )

        billing.create_payment.assert_not_called()
        dm.switch_to.assert_awaited_once_with(state=Subscription.CRYPTO_ASSET)
        assert dm.dialog_data["selected_payment_method"] == PaymentGatewayType.PLAIDLY


class TestOnCryptoAssetSelect:
    async def test_stores_chain_token_and_sends_gateway_metadata(self):
        plan = _plan_with_duration()
        dm = _dm_for_crypto(plan)
        billing = _make_billing()
        ntf = AsyncMock()
        experiment_service = make_experiment_service()
        raw = unwrap_inject(on_crypto_asset_select)
        redis_client = AsyncMock()

        await raw(
            MagicMock(),
            MagicMock(),
            dm,
            "usdt-tron",
            billing,
            experiment_service,
            _NoChannelIncentive(),
            ntf,
            redis_client,
        )

        billing.create_payment.assert_awaited_once()
        kwargs = billing.create_payment.await_args.kwargs
        assert kwargs["gateway_type"] == "PLAIDLY"
        assert kwargs["gateway_metadata"] == {"chain": "tron", "token": "USDT"}
        assert dm.dialog_data["selected_crypto_asset"] == "usdt-tron"
        dm.switch_to.assert_awaited_once_with(state=Subscription.CONFIRM)

    async def test_each_asset_maps_to_its_chain_and_token(self):
        for asset in CRYPTO_ASSETS:
            plan = _plan_with_duration()
            dm = _dm_for_crypto(plan)
            billing = _make_billing()
            experiment_service = make_experiment_service()
            raw = unwrap_inject(on_crypto_asset_select)
            redis_client = AsyncMock()

            await raw(
                MagicMock(),
                MagicMock(),
                dm,
                asset.id,
                billing,
                experiment_service,
                _NoChannelIncentive(),
                AsyncMock(),
                redis_client,
            )

            kwargs = billing.create_payment.await_args.kwargs
            assert kwargs["gateway_metadata"] == {"chain": asset.chain, "token": asset.token}
