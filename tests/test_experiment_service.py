"""Tests for the A/B experiment framework (BDT-432) and trial experiment (BDT-433)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

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
    redis_client = AsyncMock()
    redis_client.set.return_value = True
    return ExperimentService(config, redis_client)


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
