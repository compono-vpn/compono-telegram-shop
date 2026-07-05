from __future__ import annotations

from unittest import TestCase

from estimand_sdk import (
    REASON_FEATURE_DISABLED,
    REASON_FEATURE_UNPUBLISHED,
    REASON_NO_MATCHING_RULE,
    REASON_RULE_MATCHED,
    REASON_VARIANT_FORCED,
    ConfigPayload,
    evaluate_feature_from_payload,
    evaluate_features,
)
from estimand_sdk.models import FeatureConfig, RuleConfig, VariationConfig


class EvaluatorTestCase(TestCase):
    def _feature(self, feature_type: str = "flag") -> FeatureConfig:
        return FeatureConfig(
            type=feature_type,
            default_value={"enabled": True},
            seed="checkout-v2",
            unit_type="user_id",
            enabled=True,
            published=True,
            variations=[
                VariationConfig(
                    key="control",
                    name="control",
                    value={"label": "control"},
                    weight=50,
                    is_control=True,
                    description="",
                ),
                VariationConfig(
                    key="treatment",
                    name="treatment",
                    value={"label": "treatment"},
                    weight=50,
                    is_control=False,
                    description="",
                ),
            ],
            rules=[
                RuleConfig(
                    id="r1",
                    condition={},
                    variation_keys=["control", "treatment"],
                    coverage=1.0,
                    priority=1,
                    is_default=False,
                    force=None,
                    seed="checkout-v2",
                    hash_version=2,
                    weights=[0.25, 0.75],
                    ranges=None,
                )
            ],
        )

    def _config(self) -> ConfigPayload:
        return ConfigPayload(revision="rev-1", features={"checkout": self._feature()})

    def test_feature_disabled_returns_expected_reason(self) -> None:
        disabled = self._feature()
        disabled = FeatureConfig(
            type=disabled.type,
            default_value=disabled.default_value,
            seed=disabled.seed,
            unit_type=disabled.unit_type,
            enabled=False,
            published=disabled.published,
            variations=disabled.variations,
            rules=disabled.rules,
        )
        payload = ConfigPayload(revision="rev-1", features={"checkout": disabled})
        result = evaluate_feature_from_payload(
            config=payload,
            feature_key="checkout",
            unit_id="user-1",
        )
        self.assertEqual(result.reason, REASON_FEATURE_DISABLED)
        self.assertIsNone(result.variation_key)

    def test_feature_unpublished_returns_expected_reason(self) -> None:
        unpublished = self._feature()
        unpublished = FeatureConfig(
            type=unpublished.type,
            default_value=unpublished.default_value,
            seed=unpublished.seed,
            unit_type=unpublished.unit_type,
            enabled=True,
            published=False,
            variations=unpublished.variations,
            rules=unpublished.rules,
        )
        payload = ConfigPayload(revision="rev-1", features={"checkout": unpublished})
        result = evaluate_feature_from_payload(
            config=payload,
            feature_key="checkout",
            unit_id="user-1",
        )
        self.assertEqual(result.reason, REASON_FEATURE_UNPUBLISHED)
        self.assertIsNone(result.variation_key)

    def test_force_variation_is_respected(self) -> None:
        forced = self._feature()
        forced = FeatureConfig(
            type=forced.type,
            default_value=forced.default_value,
            seed=forced.seed,
            unit_type=forced.unit_type,
            enabled=True,
            published=True,
            variations=forced.variations,
            rules=[
                RuleConfig(
                    id="r1",
                    condition={},
                    variation_keys=["control", "treatment"],
                    coverage=1.0,
                    priority=1,
                    is_default=False,
                    force="treatment",
                    seed="checkout-v2",
                    hash_version=2,
                    weights=[0.25, 0.75],
                    ranges=None,
                )
            ],
        )
        payload = ConfigPayload(revision="rev-1", features={"checkout": forced})
        result = evaluate_feature_from_payload(
            config=payload,
            feature_key="checkout",
            unit_id="user-123",
        )
        self.assertEqual(result.reason, REASON_VARIANT_FORCED)
        self.assertEqual(result.variation_key, "treatment")

    def test_forced_variation_override_takes_precedence_over_rules(self) -> None:
        feature = self._feature()
        feature = FeatureConfig(
            type=feature.type,
            default_value=feature.default_value,
            seed=feature.seed,
            unit_type=feature.unit_type,
            enabled=True,
            published=True,
            variations=feature.variations,
            rules=[
                RuleConfig(
                    id="r1",
                    condition={"plan": "enterprise"},
                    variation_keys=["control", "treatment"],
                    coverage=1.0,
                    priority=1,
                    is_default=False,
                    force="control",
                    seed="checkout-v2",
                    hash_version=2,
                    weights=None,
                    ranges=None,
                )
            ],
            forced_variations={"telegram-42": "treatment"},
        )
        payload = ConfigPayload(revision="rev-1", features={"checkout": feature})

        result = evaluate_feature_from_payload(
            config=payload,
            feature_key="checkout",
            unit_id="telegram-42",
            context={"plan": "starter"},
        )

        self.assertEqual(result.reason, REASON_VARIANT_FORCED)
        self.assertEqual(result.variation_key, "treatment")
        self.assertIsNone(result.matched_rule_id)

    def test_no_matching_rule(self) -> None:
        unmatched = self._feature()
        unmatched = FeatureConfig(
            type=unmatched.type,
            default_value=unmatched.default_value,
            seed=unmatched.seed,
            unit_type=unmatched.unit_type,
            enabled=True,
            published=True,
            variations=unmatched.variations,
            rules=[
                RuleConfig(
                    id="r1",
                    condition={"plan": "enterprise"},
                    variation_keys=["control", "treatment"],
                    coverage=1.0,
                    priority=1,
                    is_default=False,
                    force=None,
                    seed="checkout-v2",
                    hash_version=2,
                    weights=None,
                    ranges=None,
                )
            ],
        )
        payload = ConfigPayload(revision="rev-1", features={"checkout": unmatched})
        result = evaluate_feature_from_payload(
            config=payload,
            feature_key="checkout",
            unit_id="user-1",
            context={"plan": "starter"},
        )
        self.assertEqual(result.reason, REASON_NO_MATCHING_RULE)

    def test_evaluate_all_returns_map(self) -> None:
        payload = self._config()
        results = evaluate_features(config=payload, unit_id="user-1", context={})
        self.assertIn("checkout", results)
        self.assertEqual(results["checkout"].reason, REASON_RULE_MATCHED)

    def test_feature_lookup_not_found(self) -> None:
        payload = self._config()
        result = evaluate_feature_from_payload(
            config=payload,
            feature_key="missing",
            unit_id="user-1",
        )
        self.assertEqual(result.feature_key, "missing")
        self.assertEqual(result.reason, "feature_not_found")
