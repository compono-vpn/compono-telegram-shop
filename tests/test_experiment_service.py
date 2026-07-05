"""Tests for the A/B experiment framework (BDT-432) and trial experiment (BDT-433)."""

from __future__ import annotations

from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock

import pytest

from estimand_sdk.evaluator import evaluate_feature_from_payload
from estimand_sdk.models import ConfigPayload, FeatureConfig, RuleConfig, VariationConfig
from src.core.experiments import Experiment, assign_variant
from src.services.experiment import (
    TRIAL_EXPERIMENT_KEY,
    TRIAL_VARIANT_OFF,
    TRIAL_VARIANT_ON,
    ExperimentService,
)


def _service(*, trial_enabled: bool = True, trial_on_weight: int = 50) -> ExperimentService:
    config = MagicMock()
    config.experiments.trial_enabled = trial_enabled
    config.experiments.trial_on_weight = trial_on_weight
    config.experiments.estimand = MagicMock()
    config.experiments.estimand.enabled = False
    config.experiments.estimand.on_variant = TRIAL_VARIANT_ON
    config.experiments.estimand.off_variant = TRIAL_VARIANT_OFF
    redis_client = AsyncMock()
    redis_client.set.return_value = True
    return ExperimentService(config, redis_client)


def _build_estimand_payload() -> ConfigPayload:
    return ConfigPayload(
        revision="rev-1",
        features={
            "trial_offer": FeatureConfig(
                type="flag",
                default_value={"trial": "off"},
                seed="trial_offer_v1",
                unit_type="user_id",
                enabled=True,
                published=True,
                variations=[
                    VariationConfig(
                        key="trial_on",
                        name="trial_on",
                        value={"trial": "on"},
                        weight=50,
                        is_control=True,
                        description="",
                    ),
                    VariationConfig(
                        key="trial_off",
                        name="trial_off",
                        value={"trial": "off"},
                        weight=50,
                        is_control=False,
                        description="",
                    ),
                ],
                rules=[
                    RuleConfig(
                        id="default",
                        condition={},
                        variation_keys=["trial_on", "trial_off"],
                        coverage=1.0,
                        priority=0,
                        is_default=True,
                        force=None,
                        seed="trial_offer_v1",
                        hash_version=2,
                        weights=[0.5, 0.5],
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
) -> tuple[ExperimentService, MagicMock, ConfigPayload]:
    config = MagicMock()
    config.experiments.trial_enabled = trial_enabled
    config.experiments.trial_on_weight = 50
    config.experiments.estimand = MagicMock()
    config.experiments.estimand.enabled = True
    config.experiments.estimand.base_url = "https://estimand.local"
    config.experiments.estimand.api_key = "esk_test_key"
    config.experiments.estimand.organization_id = "org-1"
    config.experiments.estimand.project_id = "project-1"
    config.experiments.estimand.environment_id = "env-1"
    config.experiments.estimand.feature_key = "trial_offer"
    config.experiments.estimand.feature_id = "feature-1"
    config.experiments.estimand.on_variant = TRIAL_VARIANT_ON
    config.experiments.estimand.off_variant = TRIAL_VARIANT_OFF
    config.experiments.estimand.conversion_event = "trial_activated"
    redis_client = AsyncMock()
    redis_client.set.return_value = True

    estimand_client = MagicMock()
    payload = _build_estimand_payload()
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

    service = ExperimentService(config, redis_client)
    service.estimand_client = estimand_client
    return service, estimand_client, payload


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
        assert (
            estimand_client.track_conversion.call_args.kwargs["event_name"]
            == "trial_activated"
        )
