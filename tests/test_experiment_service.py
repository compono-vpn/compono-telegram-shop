"""Tests for the A/B experiment framework (BDT-432), trial experiment (BDT-433),
and the new-user-only enrollment gate (BDT-442).
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.experiments import Experiment, assign_variant
from src.services.experiment import (
    TRIAL_EXPERIMENT_KEY,
    TRIAL_VARIANT_OFF,
    TRIAL_VARIANT_ON,
    ExperimentService,
)

_PAST_START = date(2020, 1, 1)
_OLD_USER_CREATED_AT = datetime(2019, 12, 31)
_NEW_USER_CREATED_AT = datetime(2024, 1, 1)


def _service(
    *,
    trial_enabled: bool = True,
    trial_on_weight: int = 50,
    trial_start_date: date | None = _PAST_START,
) -> ExperimentService:
    config = MagicMock()
    config.experiments.trial_enabled = trial_enabled
    config.experiments.trial_on_weight = trial_on_weight
    config.experiments.trial_start_date = trial_start_date
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

    def test_start_date_defaults_to_none(self):
        exp = Experiment(key="x", variants=("a", "b"), weights=(100, 0), salt="s")
        assert exp.start_date is None

    def test_start_date_can_be_set(self):
        exp = Experiment(
            key="x", variants=("a", "b"), weights=(100, 0), salt="s", start_date=_PAST_START
        )
        assert exp.start_date == _PAST_START


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
    """Weight-based assignment tests. All use a new-enough created_at so the
    BDT-442 gate doesn't interfere with what's under test here."""

    async def test_weight_100_enables_trial(self):
        svc = _service(trial_on_weight=100)
        assert await svc.is_trial_offer_enabled(999, created_at=_NEW_USER_CREATED_AT) is True

    async def test_weight_0_disables_trial(self):
        svc = _service(trial_on_weight=0)
        assert await svc.is_trial_offer_enabled(999, created_at=_NEW_USER_CREATED_AT) is False

    async def test_disabled_experiment_defaults_to_control_on(self):
        svc = _service(trial_enabled=False, trial_on_weight=0)
        assert await svc.is_trial_offer_enabled(999, created_at=_NEW_USER_CREATED_AT) is True

    async def test_variant_names(self):
        svc = _service(trial_on_weight=100)
        assert (
            svc.variant(TRIAL_EXPERIMENT_KEY, 1, created_at=_NEW_USER_CREATED_AT)
            == TRIAL_VARIANT_ON
        )
        svc_off = _service(trial_on_weight=0)
        assert (
            svc_off.variant(TRIAL_EXPERIMENT_KEY, 1, created_at=_NEW_USER_CREATED_AT)
            == TRIAL_VARIANT_OFF
        )

    async def test_exposure_deduped_by_redis_nx(self):
        svc = _service(trial_on_weight=100)
        svc.redis_client.set.return_value = None
        variant = await svc.expose(TRIAL_EXPERIMENT_KEY, 42, created_at=_NEW_USER_CREATED_AT)
        assert variant == TRIAL_VARIANT_ON
        svc.redis_client.set.assert_awaited_once()

    async def test_exposure_survives_redis_error(self):
        svc = _service(trial_on_weight=100)
        svc.redis_client.set.side_effect = Exception("redis down")
        variant = await svc.expose(TRIAL_EXPERIMENT_KEY, 7, created_at=_NEW_USER_CREATED_AT)
        assert variant == TRIAL_VARIANT_ON


class TestNewUserGate:
    """BDT-442: an experiment only enrolls users created on/after its
    start_date. Existing users always resolve to variants[0] (the
    pre-experiment/current behaviour) and never get an exposure recorded.
    """

    async def test_old_user_gets_control_without_exposure(self):
        svc = _service(trial_on_weight=0, trial_start_date=_PAST_START)
        variant = await svc.expose(TRIAL_EXPERIMENT_KEY, 111, created_at=_OLD_USER_CREATED_AT)
        assert variant == TRIAL_VARIANT_ON
        svc.redis_client.set.assert_not_awaited()

    async def test_new_user_gets_normal_assignment(self):
        svc = _service(trial_on_weight=0, trial_start_date=_PAST_START)
        variant = await svc.expose(TRIAL_EXPERIMENT_KEY, 111, created_at=_NEW_USER_CREATED_AT)
        assert variant == TRIAL_VARIANT_OFF
        svc.redis_client.set.assert_awaited_once()

    async def test_unknown_created_at_gets_control_without_exposure(self):
        svc = _service(trial_on_weight=0, trial_start_date=_PAST_START)
        variant = await svc.expose(TRIAL_EXPERIMENT_KEY, 111, created_at=None)
        assert variant == TRIAL_VARIANT_ON
        svc.redis_client.set.assert_not_awaited()

    async def test_created_at_omitted_defaults_to_unknown(self):
        svc = _service(trial_on_weight=0, trial_start_date=_PAST_START)
        variant = await svc.expose(TRIAL_EXPERIMENT_KEY, 111)
        assert variant == TRIAL_VARIANT_ON
        svc.redis_client.set.assert_not_awaited()

    async def test_boundary_created_at_equals_start_date_is_enrolled(self):
        svc = _service(trial_on_weight=0, trial_start_date=_PAST_START)
        created_at = datetime(_PAST_START.year, _PAST_START.month, _PAST_START.day)
        variant = await svc.expose(TRIAL_EXPERIMENT_KEY, 111, created_at=created_at)
        assert variant == TRIAL_VARIANT_OFF
        svc.redis_client.set.assert_awaited_once()

    async def test_no_start_date_configured_forces_control(self):
        svc = _service(trial_on_weight=0, trial_start_date=None)
        variant = await svc.expose(TRIAL_EXPERIMENT_KEY, 111, created_at=_NEW_USER_CREATED_AT)
        assert variant == TRIAL_VARIANT_ON
        svc.redis_client.set.assert_not_awaited()

    def test_variant_gates_old_user_to_control(self):
        svc = _service(trial_on_weight=0, trial_start_date=_PAST_START)
        assert (
            svc.variant(TRIAL_EXPERIMENT_KEY, 111, created_at=_OLD_USER_CREATED_AT)
            == TRIAL_VARIANT_ON
        )

    def test_variant_allows_new_user_normal_assignment(self):
        svc = _service(trial_on_weight=0, trial_start_date=_PAST_START)
        assert (
            svc.variant(TRIAL_EXPERIMENT_KEY, 111, created_at=_NEW_USER_CREATED_AT)
            == TRIAL_VARIANT_OFF
        )

    def test_record_conversion_gates_old_user_to_control_variant(self):
        svc = _service(trial_on_weight=0, trial_start_date=_PAST_START)
        svc.record_conversion(
            TRIAL_EXPERIMENT_KEY, 111, "trial_activated", created_at=_OLD_USER_CREATED_AT
        )
        # No exception, and the variant used for the metric matches the gate.
        assert (
            svc.variant(TRIAL_EXPERIMENT_KEY, 111, created_at=_OLD_USER_CREATED_AT)
            == TRIAL_VARIANT_ON
        )
