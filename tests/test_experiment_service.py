"""Tests for the A/B experiment framework (BDT-432) and trial experiment (BDT-433)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock

import pytest

import src.services.experiment as experiment_module
from estimand_sdk.evaluator import evaluate_feature_from_payload
from estimand_sdk.models import ConfigPayload, FeatureConfig, RuleConfig, VariationConfig
from src.core.experiments import Experiment, assign_variant
from src.models.dto.user import UserDto
from src.services.experiment import (
    TRIAL_EXPERIMENT_KEY,
    TRIAL_VARIANT_OFF,
    TRIAL_VARIANT_ON,
    ExperimentFeature,
    ExperimentService,
)


def _service(
    *,
    trial_enabled: bool = True,
    trial_on_weight: int = 50,
    trial_offer_start_date: datetime | None = None,
    trial_length_start_date: datetime | None = None,
    start_tier_price_start_date: datetime | None = None,
    intro_price_start_date: datetime | None = None,
    checkout_flow_start_date: datetime | None = None,
    payment_rescue_start_date: datetime | None = None,
) -> ExperimentService:
    config = MagicMock()
    config.experiments.trial_enabled = trial_enabled
    config.experiments.trial_on_weight = trial_on_weight
    config.experiments.trial_offer_start_date = trial_offer_start_date
    config.experiments.trial_length_start_date = trial_length_start_date
    config.experiments.start_tier_price_start_date = start_tier_price_start_date
    config.experiments.intro_price_start_date = intro_price_start_date
    config.experiments.checkout_flow_start_date = checkout_flow_start_date
    config.experiments.payment_rescue_start_date = payment_rescue_start_date
    config.experiments.estimand = MagicMock()
    config.experiments.estimand.enabled = False
    config.experiments.estimand.on_variant = TRIAL_VARIANT_ON
    config.experiments.estimand.off_variant = TRIAL_VARIANT_OFF
    redis_client = AsyncMock()
    redis_client.set.return_value = True
    return ExperimentService(config, redis_client)


def _build_estimand_payload(
    *,
    revision: str = "rev-1",
    on_variant: str = TRIAL_VARIANT_ON,
    off_variant: str = TRIAL_VARIANT_OFF,
    feature_key: str = TRIAL_EXPERIMENT_KEY,
    feature_variations: list[tuple[str, dict[str, Any]]] | None = None,
    variation_weights: list[float] | None = None,
) -> ConfigPayload:
    variations = feature_variations
    if variations is None:
        variations = [
            (on_variant, {"trial": "on"}),
            (off_variant, {"trial": "off"}),
        ]

    count = len(variations)
    if count == 0:
        raise ValueError("at least one variation required")

    if variation_weights is None:
        equal_weight = 1.0 / count
        variation_weights = [equal_weight for _ in range(count)]

    if len(variation_weights) != count:
        raise ValueError("variation weights must match variation count")

    return ConfigPayload(
        revision=revision,
        features={
            feature_key: FeatureConfig(
                type="flag",
                default_value={"trial": "off"},
                seed=f"{feature_key}_v1",
                unit_type="user_id",
                enabled=True,
                published=True,
                variations=[
                    VariationConfig(
                        key=key,
                        name=key,
                        value=value,
                        weight=100,
                        is_control=index == 0,
                        description="",
                    )
                    for index, (key, value) in enumerate(variations)
                ],
                rules=[
                    RuleConfig(
                        id="default",
                        condition={},
                        variation_keys=[key for key, _ in variations],
                        coverage=1.0,
                        priority=0,
                        is_default=True,
                        force=None,
                        seed=f"{feature_key}_v1",
                        hash_version=2,
                        weights=variation_weights,
                        ranges=None,
                    ),
                ],
            )
        },
    )


def _service_estimand(
    *,
    trial_enabled: bool = True,
    on_click: Callable[[Any], Any] | None = None,
    on_variant: str = TRIAL_VARIANT_ON,
    off_variant: str = TRIAL_VARIANT_OFF,
    feature_key: str = TRIAL_EXPERIMENT_KEY,
    feature_id: str = "feature-1",
    trial_length_feature_id: str = "",
    start_tier_price_feature_id: str = "",
    intro_price_feature_id: str = "",
    checkout_flow_feature_id: str = "",
    payment_rescue_feature_id: str = "",
    checkout_flow_feature_key: str = "checkout_flow",
    trial_length_feature_key: str = "trial_length",
    start_tier_price_feature_key: str = "start_tier_price",
    intro_price_feature_key: str = "intro_price",
    payment_rescue_feature_key: str = "payment_rescue",
    trial_offer_start_date: datetime | None = None,
    payload: ConfigPayload | None = None,
) -> tuple[ExperimentService, MagicMock, ConfigPayload]:
    config = MagicMock()
    config.experiments.trial_enabled = trial_enabled
    config.experiments.trial_on_weight = 50
    config.experiments.trial_offer_start_date = trial_offer_start_date
    config.experiments.trial_length_start_date = None
    config.experiments.start_tier_price_start_date = None
    config.experiments.intro_price_start_date = None
    config.experiments.checkout_flow_start_date = None
    config.experiments.payment_rescue_start_date = None
    config.experiments.estimand = MagicMock()
    config.experiments.estimand.enabled = True
    config.experiments.estimand.base_url = "https://estimand.local"
    config.experiments.estimand.api_key = "esk_test_key"
    config.experiments.estimand.organization_id = "org-1"
    config.experiments.estimand.project_id = "project-1"
    config.experiments.estimand.environment_id = "env-1"
    config.experiments.estimand.feature_key = feature_key
    config.experiments.estimand.feature_id = feature_id
    config.experiments.estimand.trial_length_feature_key = trial_length_feature_key
    config.experiments.estimand.trial_length_feature_id = trial_length_feature_id
    config.experiments.estimand.start_tier_price_feature_key = start_tier_price_feature_key
    config.experiments.estimand.start_tier_price_feature_id = start_tier_price_feature_id
    config.experiments.estimand.intro_price_feature_key = intro_price_feature_key
    config.experiments.estimand.intro_price_feature_id = intro_price_feature_id
    config.experiments.estimand.checkout_flow_feature_key = checkout_flow_feature_key
    config.experiments.estimand.checkout_flow_feature_id = checkout_flow_feature_id
    config.experiments.estimand.payment_rescue_feature_key = payment_rescue_feature_key
    config.experiments.estimand.payment_rescue_feature_id = payment_rescue_feature_id
    config.experiments.estimand.on_variant = on_variant
    config.experiments.estimand.off_variant = off_variant
    config.experiments.estimand.conversion_event = "trial_activated"
    redis_client = AsyncMock()
    redis_client.set.return_value = True

    estimand_client = MagicMock()
    payload = payload or _build_estimand_payload(
        on_variant=on_variant,
        off_variant=off_variant,
        feature_key=feature_key,
    )
    estimand_client.fetch_config.return_value = payload
    estimand_client.evaluate_feature.side_effect = lambda **kwargs: evaluate_feature_from_payload(
        config=payload,
        feature_key=kwargs["feature_key"],
        unit_id=kwargs["unit_id"],
    )

    if on_click:
        estimand_client.track_exposure = MagicMock(side_effect=on_click)
        estimand_client.track_conversion = MagicMock(side_effect=on_click)
    else:
        estimand_client.track_exposure = MagicMock()
        estimand_client.track_conversion = MagicMock()

    service = ExperimentService(
        config,
        redis_client,
        estimand_client=estimand_client,
    )
    return service, estimand_client, payload


def _payload_evaluator(payload: ConfigPayload):
    return lambda **kwargs: evaluate_feature_from_payload(
        config=payload,
        feature_key=kwargs["feature_key"],
        unit_id=kwargs["unit_id"],
    )


class TestExperimentModel:
    def test_weights_must_sum_to_100(self):
        with pytest.raises(ValueError, match="sum to 100"):
            Experiment(key="x", variants=("a", "b"), weights=(30, 30), salt="s")

    def test_variants_weights_length_mismatch(self):
        with pytest.raises(ValueError, match="length mismatch"):
            Experiment(key="x", variants=("a", "b"), weights=(100,), salt="s")


class TestAssignVariant:
    def test_deterministic(self):
        exp = Experiment(key="x", variants=("a", "b"), weights=(50, 50), salt="s")
        assert assign_variant(exp, 12345) == assign_variant(exp, 12345)

    def test_disabled_returns_control(self):
        exp = Experiment(key="x", variants=("a", "b"), weights=(50, 50), salt="s", enabled=False)
        assert all(assign_variant(exp, tid) == "a" for tid in range(200))

    def test_full_weight_all_one_variant(self):
        exp = Experiment(key="x", variants=("a", "b"), weights=(100, 0), salt="s")
        assert all(assign_variant(exp, tid) == "a" for tid in range(200))

    def test_distribution_roughly_matches_weights(self):
        exp = Experiment(key="x", variants=("a", "b"), weights=(70, 30), salt="dist")
        a = sum(assign_variant(exp, tid) == "a" for tid in range(2000))
        assert 0.6 < a / 2000 < 0.8


class TestTrialExperiment:
    async def test_weight_100_enables_trial(self):
        svc = _service(trial_on_weight=100)
        assert await svc.is_trial_offer_enabled(999) is True

    async def test_weight_0_disables_trial(self):
        svc = _service(trial_on_weight=0)
        assert await svc.is_trial_offer_enabled(999) is False

    async def test_disabled_experiment_defaults_to_control_on(self):
        svc = _service(trial_enabled=False, trial_on_weight=0)
        assert await svc.is_trial_offer_enabled(999) is True

    async def test_deterministic_assignment_fallback_for_estimand_failure(self):
        svc, estimand_client, _ = _service_estimand()
        estimand_client.fetch_config.side_effect = Exception("estimand down")

        first = await svc.expose(TRIAL_EXPERIMENT_KEY, 123)
        second = await svc.expose(TRIAL_EXPERIMENT_KEY, 123)

        assert first == second
        assert first in {TRIAL_VARIANT_ON, TRIAL_VARIANT_OFF}
        assert estimand_client.fetch_config.call_count == 1
        assert estimand_client.track_exposure.call_count == 0

    async def test_estimand_client_can_be_injected_into_service(self):
        svc, estimand_client, _ = _service_estimand()

        assert svc.estimand_client is estimand_client
        assert await svc.expose(TRIAL_EXPERIMENT_KEY, 123) in {
            TRIAL_VARIANT_ON,
            TRIAL_VARIANT_OFF,
        }
        assert estimand_client.evaluate_feature.call_count == 1

    def test_estimand_config_cache_reuses_payload_within_ttl(self, monkeypatch):
        times = iter([100.0, 120.0])
        monkeypatch.setattr(experiment_module, "monotonic", lambda: next(times))
        svc, estimand_client, _ = _service_estimand()
        user = UserDto(telegram_id=555, name="Cache")

        svc.evaluate_feature_for_user(user, TRIAL_EXPERIMENT_KEY)
        svc.evaluate_feature_for_user(user, TRIAL_EXPERIMENT_KEY)

        assert estimand_client.fetch_config.call_count == 1

    def test_estimand_config_cache_refreshes_after_ttl(self, monkeypatch):
        times = iter([100.0, 131.0])
        monkeypatch.setattr(experiment_module, "monotonic", lambda: next(times))
        svc, estimand_client, _ = _service_estimand()
        user = UserDto(telegram_id=555, name="Cache")

        svc.evaluate_feature_for_user(user, TRIAL_EXPERIMENT_KEY)
        svc.evaluate_feature_for_user(user, TRIAL_EXPERIMENT_KEY)

        assert estimand_client.fetch_config.call_count == 2

    async def test_non_serving_feature_uses_local_fallback_without_remote_events(self):
        feature_key = ExperimentFeature.CHECKOUT_FLOW.value
        feature_id = "cf-01"
        payload = _build_estimand_payload(feature_key=feature_key)
        feature = payload.features[feature_key]
        payload.features[feature_key] = FeatureConfig(
            type=feature.type,
            default_value=feature.default_value,
            seed=feature.seed,
            unit_type=feature.unit_type,
            enabled=False,
            published=feature.published,
            variations=feature.variations,
            rules=feature.rules,
            forced_variations=feature.forced_variations,
        )
        svc, estimand_client, _ = _service_estimand(
            feature_key=feature_key,
            feature_id=feature_id,
            checkout_flow_feature_id=feature_id,
            payload=payload,
        )
        user = UserDto(telegram_id=555, name="NonServing")

        evaluation = svc.evaluate_feature_for_user(user, ExperimentFeature.CHECKOUT_FLOW)

        assert evaluation.feature_key == feature_key
        assert evaluation.variant == "checkout_flow_v1_off"
        assert evaluation.payload is None

        variant = await svc.expose(feature_key, user.telegram_id, user.created_at)

        assert variant == "checkout_flow_v1_off"
        svc.redis_client.set.assert_not_awaited()

        svc.record_conversion(
            feature_key,
            user.telegram_id,
            "payment_link_created",
            user.created_at,
        )

        estimand_client.track_exposure.assert_not_called()
        estimand_client.track_conversion.assert_not_called()

    async def test_unpublished_feature_uses_local_fallback_without_remote_events(self):
        feature_key = ExperimentFeature.START_TIER_PRICE.value
        feature_id = "price-01"
        payload = _build_estimand_payload(feature_key=feature_key)
        feature = payload.features[feature_key]
        payload.features[feature_key] = FeatureConfig(
            type=feature.type,
            default_value=feature.default_value,
            seed=feature.seed,
            unit_type=feature.unit_type,
            enabled=True,
            published=False,
            variations=feature.variations,
            rules=feature.rules,
            forced_variations=feature.forced_variations,
        )
        svc, estimand_client, _ = _service_estimand(
            feature_key=feature_key,
            feature_id=feature_id,
            start_tier_price_feature_id=feature_id,
            payload=payload,
        )
        user = UserDto(telegram_id=556, name="Unpublished")

        evaluation = svc.evaluate_feature_for_user(user, ExperimentFeature.START_TIER_PRICE)

        assert evaluation.feature_key == feature_key
        assert evaluation.variant == "start_tier_price_v1_off"
        assert evaluation.payload is None

        await svc.expose(feature_key, user.telegram_id, user.created_at)
        svc.record_conversion(feature_key, user.telegram_id, "payment_completed", user.created_at)

        svc.redis_client.set.assert_not_awaited()
        estimand_client.track_exposure.assert_not_called()
        estimand_client.track_conversion.assert_not_called()

    async def test_non_trial_feature_evaluates_via_estimand_when_configured(self):
        feature_key = ExperimentFeature.CHECKOUT_FLOW.value
        feature_id = "cf-01"
        on_variant = "checkout_flow_v1_on"
        off_variant = "checkout_flow_v1_off"
        svc, estimand_client, payload = _service_estimand(
            feature_key=feature_key,
            feature_id=feature_id,
            checkout_flow_feature_id=feature_id,
            on_variant=on_variant,
            off_variant=off_variant,
        )
        user = UserDto(telegram_id=555, name="NonTrial")

        evaluation = svc.evaluate_feature_for_user(user, ExperimentFeature.CHECKOUT_FLOW)

        assert evaluation.feature_key == feature_key
        assert evaluation.variant in {on_variant, off_variant}
        assert evaluation.payload in (
            payload.features[feature_key].variations[0].value,
            payload.features[feature_key].variations[1].value,
        )
        assert estimand_client.evaluate_feature.call_count >= 1

    async def test_non_trial_feature_returns_multi_arm_estimand_variant(self):
        payload = _build_estimand_payload(
            feature_key=ExperimentFeature.TRIAL_LENGTH.value,
            feature_variations=[
                ("trial_14", {"days": 14}),
                ("trial_7", {"days": 7}),
                ("trial_3", {"days": 3}),
            ],
            variation_weights=[1.0, 0.0, 0.0],
        )
        svc, estimand_client, payload_from_config = _service_estimand(
            feature_key=ExperimentFeature.TRIAL_LENGTH.value,
            feature_id="tl-14",
            trial_length_feature_id="tl-14",
            on_variant="trial_14",
            off_variant="trial_3",
            payload=payload,
        )
        user = UserDto(telegram_id=321, name="MultiArm")

        evaluation = svc.evaluate_feature_for_user(user, ExperimentFeature.TRIAL_LENGTH)

        assert evaluation.variant == "trial_14"
        trial_length_variation = (
            payload_from_config.features[ExperimentFeature.TRIAL_LENGTH.value].variations[0].value
        )
        assert evaluation.payload == trial_length_variation
        assert evaluation.payload == {"days": 14}
        assert estimand_client.evaluate_feature.call_count >= 1

    async def test_non_trial_start_date_blocks_old_users_from_estimand_feature(self):
        now = datetime.now(timezone.utc)
        start_date = now + timedelta(days=1)
        user = UserDto(
            telegram_id=901,
            name="Old non-trial",
            created_at=now - timedelta(days=2),
        )
        svc = _service(
            trial_on_weight=50,
            trial_offer_start_date=now,
            trial_length_start_date=None,
            start_tier_price_start_date=None,
            intro_price_start_date=None,
            checkout_flow_start_date=start_date,
            payment_rescue_start_date=None,
        )

        assert (
            await svc.expose(
                ExperimentFeature.CHECKOUT_FLOW.value,
                user.telegram_id,
                user.created_at,
            )
            == "checkout_flow_v1_off"
        )
        svc.redis_client.set.assert_not_awaited()

    async def test_non_trial_unknown_created_at_falls_back_to_control(self):
        user = UserDto(
            telegram_id=902,
            name="Unknown non-trial",
            created_at=None,
        )
        svc = _service(
            trial_on_weight=50,
            checkout_flow_start_date=datetime.now(timezone.utc),
        )

        assert (
            await svc.expose(
                ExperimentFeature.CHECKOUT_FLOW.value,
                user.telegram_id,
                user.created_at,
            )
            == "checkout_flow_v1_off"
        )
        svc.redis_client.set.assert_not_awaited()

    async def test_disabled_experiment_uses_local_control_without_estimate(self):
        svc = _service(trial_enabled=False, trial_on_weight=0)
        assert await svc.expose(TRIAL_EXPERIMENT_KEY, 7) == TRIAL_VARIANT_ON
        assert svc.variant(TRIAL_EXPERIMENT_KEY, 7) == TRIAL_VARIANT_ON

    async def test_disabled_experiment_service_does_not_send_remote_conversion(self):
        svc = _service(trial_enabled=False, trial_on_weight=100)
        svc.estimand_client = MagicMock()

        svc.record_conversion(TRIAL_EXPERIMENT_KEY, 42, "rescue_clicked")

        svc.estimand_client.track_conversion.assert_not_called()

    async def test_variant_names(self):
        svc = _service(trial_on_weight=100)
        assert svc.variant(TRIAL_EXPERIMENT_KEY, 1) == TRIAL_VARIANT_ON
        svc_off = _service(trial_on_weight=0)
        assert svc_off.variant(TRIAL_EXPERIMENT_KEY, 1) == TRIAL_VARIANT_OFF

    async def test_exposure_deduped_by_redis_nx(self):
        svc = _service(trial_on_weight=100)
        svc.redis_client.set.return_value = None
        variant = await svc.expose(TRIAL_EXPERIMENT_KEY, 42)
        assert variant == TRIAL_VARIANT_ON
        svc.redis_client.set.assert_awaited_once()

    async def test_exposure_cache_key_includes_estimand_revision(self):
        payload = _build_estimand_payload(revision="rev-1")
        svc, estimand_client, _ = _service_estimand(payload=payload)

        await svc.expose(TRIAL_EXPERIMENT_KEY, 42)

        updated_payload = _build_estimand_payload(revision="rev-2")
        estimand_client.fetch_config.return_value = updated_payload
        estimand_client.evaluate_feature.side_effect = _payload_evaluator(updated_payload)
        svc._fetched_config = None
        svc._fetched_config_at = 0.0

        await svc.expose(TRIAL_EXPERIMENT_KEY, 42)

        names = [call.kwargs["name"] for call in svc.redis_client.set.await_args_list]
        assert names == [
            "exp_exposed:trial_offer:42:rev-1:trial_on",
            "exp_exposed:trial_offer:42:rev-2:trial_on",
        ]

    async def test_exposure_cache_key_includes_variant(self):
        first_payload = _build_estimand_payload(
            revision="rev-1",
            feature_variations=[
                ("checkout_flow_v1_on", {"enabled": True}),
                ("checkout_flow_v1_off", {"enabled": False}),
            ],
            variation_weights=[1.0, 0.0],
            feature_key=ExperimentFeature.CHECKOUT_FLOW.value,
        )
        svc, estimand_client, _ = _service_estimand(
            feature_key=ExperimentFeature.CHECKOUT_FLOW.value,
            feature_id="checkout-flow-1",
            checkout_flow_feature_id="checkout-flow-1",
            payload=first_payload,
        )

        await svc.expose(ExperimentFeature.CHECKOUT_FLOW.value, 42)

        second_payload = _build_estimand_payload(
            revision="rev-1",
            feature_variations=[
                ("checkout_flow_v1_on", {"enabled": True}),
                ("checkout_flow_v1_off", {"enabled": False}),
            ],
            variation_weights=[0.0, 1.0],
            feature_key=ExperimentFeature.CHECKOUT_FLOW.value,
        )
        estimand_client.fetch_config.return_value = second_payload
        estimand_client.evaluate_feature.side_effect = _payload_evaluator(second_payload)
        svc._fetched_config = None
        svc._fetched_config_at = 0.0

        await svc.expose(ExperimentFeature.CHECKOUT_FLOW.value, 42)

        names = [call.kwargs["name"] for call in svc.redis_client.set.await_args_list]
        assert names == [
            "exp_exposed:checkout_flow:42:rev-1:checkout_flow_v1_on",
            "exp_exposed:checkout_flow:42:rev-1:checkout_flow_v1_off",
        ]

    async def test_exposure_survives_redis_error(self):
        svc = _service(trial_on_weight=100)
        svc.redis_client.set.side_effect = Exception("redis down")
        assert await svc.expose(TRIAL_EXPERIMENT_KEY, 7) == TRIAL_VARIANT_ON

    async def test_estimand_variant_is_sticky_for_same_telegram_id(self):
        svc, _, _ = _service_estimand()
        first = svc.variant(TRIAL_EXPERIMENT_KEY, 12345)
        second = svc.variant(TRIAL_EXPERIMENT_KEY, 12345)
        assert first == second
        assert first in {TRIAL_VARIANT_ON, TRIAL_VARIANT_OFF}
        assert svc.estimand_client.evaluate_feature.call_count >= 2

    async def test_estimand_records_exposure_and_conversion_events(self):
        svc, estimand_client, _ = _service_estimand()
        variant = await svc.expose(TRIAL_EXPERIMENT_KEY, 42)
        assert variant in {TRIAL_VARIANT_ON, TRIAL_VARIANT_OFF}
        assert estimand_client.track_exposure.call_count == 1
        svc.record_conversion(TRIAL_EXPERIMENT_KEY, 42, "trial_activated")
        assert estimand_client.track_conversion.call_count == 1
        assert not isinstance(variant, type(None))

    async def test_estimand_uses_default_conversion_event_when_empty(self):
        svc, estimand_client, _ = _service_estimand()
        svc.record_conversion(TRIAL_EXPERIMENT_KEY, 7, "")
        assert estimand_client.track_conversion.call_count == 1
        assert estimand_client.track_conversion.call_args.kwargs["event_name"] == "trial_activated"

    async def test_attributed_conversion_reuses_original_variant_after_config_change(self):
        initial_payload = _build_estimand_payload(
            revision="rev-1",
            feature_key=ExperimentFeature.INTRO_PRICE.value,
            feature_variations=[
                ("intro_99", {"final_amount": "99"}),
                ("intro_119", {"final_amount": "119"}),
            ],
            variation_weights=[1.0, 0.0],
        )
        svc, estimand_client, _ = _service_estimand(
            feature_key=ExperimentFeature.INTRO_PRICE.value,
            feature_id="intro-price-1",
            intro_price_feature_id="intro-price-1",
            payload=initial_payload,
        )
        user = UserDto(telegram_id=777, name="Checkout", created_at=datetime.now(timezone.utc))
        original = svc.evaluate_feature_for_user(user, ExperimentFeature.INTRO_PRICE)
        original_eval_count = estimand_client.evaluate_feature.call_count

        updated_payload = _build_estimand_payload(
            revision="rev-2",
            feature_key=ExperimentFeature.INTRO_PRICE.value,
            feature_variations=[
                ("intro_129", {"final_amount": "129"}),
                ("intro_119", {"final_amount": "119"}),
            ],
            variation_weights=[1.0, 0.0],
        )
        estimand_client.fetch_config.return_value = updated_payload
        estimand_client.evaluate_feature.side_effect = _payload_evaluator(updated_payload)
        svc._fetched_config = None
        svc._fetched_config_at = 0.0

        svc.record_attributed_conversion(
            original.feature_key,
            original.variant,
            user.telegram_id,
            "payment_completed",
        )

        assert estimand_client.evaluate_feature.call_count == original_eval_count
        assert estimand_client.track_conversion.call_args.kwargs["variant_key"] == "intro_99"
        assert (
            estimand_client.track_conversion.call_args.kwargs["event_name"]
            == "payment_completed"
        )

    async def test_start_date_blocks_old_users_from_trial_offer(self):
        now = datetime.now(timezone.utc)
        start_date = now + timedelta(days=1)
        user = UserDto(telegram_id=900, name="Old User", created_at=now - timedelta(days=2))
        svc = _service(trial_on_weight=100, trial_offer_start_date=start_date)

        assert (
            await svc.expose(TRIAL_EXPERIMENT_KEY, user.telegram_id, user.created_at)
            == TRIAL_VARIANT_ON
        )
        assert await svc.is_trial_offer_enabled(user) is True
        svc.redis_client.set.assert_not_awaited()

    async def test_unknown_created_at_falls_back_to_control_for_started_experiment(self):
        now = datetime.now(timezone.utc)
        user = UserDto(telegram_id=901, name="Unknown", created_at=None)
        svc = _service(trial_on_weight=100, trial_offer_start_date=now)

        assert (
            await svc.expose(TRIAL_EXPERIMENT_KEY, user.telegram_id, user.created_at)
            == TRIAL_VARIANT_ON
        )
        assert await svc.is_trial_offer_enabled(user) is True
        svc.redis_client.set.assert_not_awaited()

    async def test_trial_offer_uses_custom_estimand_variant_keys_for_payload(self):
        on_variant = "trial_enabled"
        off_variant = "trial_disabled"
        svc, _, payload = _service_estimand(
            on_variant=on_variant,
            off_variant=off_variant,
            feature_key=TRIAL_EXPERIMENT_KEY,
        )
        user = UserDto(telegram_id=777, name="Compat")

        evaluation = svc.evaluate_feature_for_user(user, ExperimentFeature.TRIAL_OFFER)

        assert evaluation.feature_key == TRIAL_EXPERIMENT_KEY
        assert evaluation.variant in {on_variant, off_variant}
        assert evaluation.payload in (
            payload.features[TRIAL_EXPERIMENT_KEY].variations[0].value,
            payload.features[TRIAL_EXPERIMENT_KEY].variations[1].value,
        )

    async def test_evaluate_feature_for_user_accepts_checkout_flow_key(self):
        user = UserDto(telegram_id=902, name="Multi", created_at=datetime.now(timezone.utc))
        svc = _service(checkout_flow_start_date=datetime.now(timezone.utc))

        evaluation = svc.evaluate_feature_for_user(user, ExperimentFeature.CHECKOUT_FLOW)

        assert evaluation.feature_key == "checkout_flow"
        assert evaluation.variant == "checkout_flow_v1_off"
        assert evaluation.payload is None
