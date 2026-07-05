from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .assignment import choose_variation, get_bucket_ranges, hash_value
from .models import ConfigPayload, FeatureConfig, RuleConfig


REASON_FEATURE_DISABLED = "feature_disabled"
REASON_FEATURE_NOT_FOUND = "feature_not_found"
REASON_NO_MATCHING_RULE = "no_matching_rule"
REASON_NO_VARIANTS = "no_variants"
REASON_OUTSIDE_COVERAGE = "outside_coverage"
REASON_VARIANT_FORCED = "forced_variation"
REASON_RULE_MATCHED = "rule_matched"
REASON_RULE_DEFAULT_MATCHED = "default_rule_matched"


@dataclass(frozen=True)
class EvaluationResult:
    feature_key: str
    variation_key: str | None
    value: Any | None
    bucket: float | None
    variation_index: int | None
    reason: str
    matched_rule_id: str | None
    is_default_rule: bool


def evaluate_features(
    *,
    config: ConfigPayload,
    unit_id: str,
    context: Mapping[str, Any] | None = None,
) -> dict[str, EvaluationResult]:
    """Evaluate all feature keys in a config payload."""

    return {
        feature_key: evaluate_feature(
            feature=feature,
            feature_key=feature_key,
            unit_id=unit_id,
            context=context,
        )
        for feature_key, feature in config.features.items()
    }


def evaluate_feature(
    *,
    feature: FeatureConfig,
    feature_key: str,
    unit_id: str,
    context: Mapping[str, Any] | None = None,
) -> EvaluationResult:
    """Evaluate one feature against unit and context using local rule/assignment logic."""

    if not feature.enabled:
        return EvaluationResult(
            feature_key=feature_key,
            variation_key=None,
            value=None,
            bucket=None,
            variation_index=None,
            reason=REASON_FEATURE_DISABLED,
            matched_rule_id=None,
            is_default_rule=False,
        )

    variation_lookup = {
        variation.key: variation.value
        for variation in feature.variations
    }
    ordered_variants = [variation.key for variation in feature.variations]

    forced_variation = feature.forced_variations.get(str(unit_id))
    if forced_variation in variation_lookup:
        return EvaluationResult(
            feature_key=feature_key,
            variation_key=forced_variation,
            value=variation_lookup.get(forced_variation),
            bucket=None,
            variation_index=None,
            reason=REASON_VARIANT_FORCED,
            matched_rule_id=None,
            is_default_rule=False,
        )

    selected = _select_rule(feature.rules, context or {})
    if selected is None:
        return EvaluationResult(
            feature_key=feature_key,
            variation_key=None,
            value=None,
            bucket=None,
            variation_index=None,
            reason=REASON_NO_MATCHING_RULE,
            matched_rule_id=None,
            is_default_rule=False,
        )

    rule, is_default = selected
    return _evaluate_rule(
        feature_seed=feature.seed,
        feature_key=feature_key,
        unit_id=unit_id,
        variation_lookup=variation_lookup,
        ordered_variants=ordered_variants,
        rule=rule,
        is_default=is_default,
    )


def evaluate_feature_from_payload(
    *,
    config: ConfigPayload,
    feature_key: str,
    unit_id: str,
    context: Mapping[str, Any] | None = None,
) -> EvaluationResult:
    """Evaluate one feature by key from a parsed config payload."""

    feature = config.features.get(feature_key)
    if feature is None:
        return EvaluationResult(
            feature_key=feature_key,
            variation_key=None,
            value=None,
            bucket=None,
            variation_index=None,
            reason=REASON_FEATURE_NOT_FOUND,
            matched_rule_id=None,
            is_default_rule=False,
        )
    return evaluate_feature(feature=feature, feature_key=feature_key, unit_id=unit_id, context=context)


def _evaluate_rule(
    *,
    feature_seed: str,
    feature_key: str,
    unit_id: str,
    variation_lookup: dict[str, Any],
    ordered_variants: Sequence[str],
    rule: RuleConfig,
    is_default: bool,
) -> EvaluationResult:
    if rule.force and rule.force in variation_lookup:
        return EvaluationResult(
            feature_key=feature_key,
            variation_key=rule.force,
            value=variation_lookup.get(rule.force),
            bucket=None,
            variation_index=None,
            reason=REASON_VARIANT_FORCED,
            matched_rule_id=rule.id,
            is_default_rule=is_default,
        )

    variation_keys = [variation for variation in rule.variation_keys if variation in ordered_variants]
    if not variation_keys:
        return EvaluationResult(
            feature_key=feature_key,
            variation_key=None,
            value=None,
            bucket=None,
            variation_index=None,
            reason=REASON_NO_VARIANTS,
            matched_rule_id=rule.id,
            is_default_rule=is_default,
        )

    ranges = rule.ranges or get_bucket_ranges(
        num_variations=len(variation_keys),
        coverage=rule.coverage,
        weights=rule.weights,
    )
    if not ranges:
        return EvaluationResult(
            feature_key=feature_key,
            variation_key=None,
            value=None,
            bucket=None,
            variation_index=None,
            reason=REASON_NO_VARIANTS,
            matched_rule_id=rule.id,
            is_default_rule=is_default,
        )

    bucket = hash_value(seed=rule.seed or feature_seed, unit=unit_id, version=rule.hash_version or 2)
    variation_index = choose_variation(bucket, ranges)
    if variation_index < 0 or variation_index >= len(variation_keys):
        return EvaluationResult(
            feature_key=feature_key,
            variation_key=None,
            value=None,
            bucket=bucket,
            variation_index=variation_index,
            reason=REASON_OUTSIDE_COVERAGE,
            matched_rule_id=rule.id,
            is_default_rule=is_default,
        )

    variation_key = variation_keys[variation_index]
    return EvaluationResult(
        feature_key=feature_key,
        variation_key=variation_key,
        value=variation_lookup.get(variation_key, config_default_value(variation_lookup)),
        bucket=bucket,
        variation_index=variation_index,
        reason=REASON_RULE_DEFAULT_MATCHED if is_default else REASON_RULE_MATCHED,
        matched_rule_id=rule.id,
        is_default_rule=is_default,
    )


def _select_rule(
    rules: Sequence[RuleConfig],
    context: Mapping[str, Any],
) -> tuple[RuleConfig, bool] | None:
    non_default_rules = [rule for rule in rules if not rule.is_default]
    for rule in non_default_rules:
        if _rule_matches(rule.condition, context):
            return rule, False

    for rule in rules:
        if not rule.is_default:
            continue
        if _rule_matches(rule.condition, context):
            return rule, True

    return None


def _rule_matches(condition: Mapping[str, Any], context: Mapping[str, Any]) -> bool:
    if not condition:
        return True
    for key, expected in condition.items():
        if not _condition_matches(context.get(key), expected):
            return False
    return True


def _condition_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, list):
        return actual in expected
    if isinstance(expected, dict):
        return _condition_operator_matches(actual, expected)
    return actual == expected


def _condition_operator_matches(actual: Any, operators: Mapping[str, Any]) -> bool:
    for operator, expected in operators.items():
        if operator == "in":
            if not isinstance(expected, list):
                return False
            if actual not in expected:
                return False
            continue
        if operator == "nin":
            if not isinstance(expected, list):
                return False
            if actual in expected:
                return False
            continue
        if operator == "ne":
            if actual == expected:
                return False
            continue
        if not _condition_numeric_matches(actual, operator, expected):
            return False
    return True


def _condition_numeric_matches(actual: Any, operator: str, expected: Any) -> bool:
    if operator == "eq":
        return actual == expected

    actual_as_float = _as_float(actual)
    expected_as_float = _as_float(expected)
    if actual_as_float is None or expected_as_float is None:
        return False

    if operator == "gt":
        return actual_as_float > expected_as_float
    if operator == "gte":
        return actual_as_float >= expected_as_float
    if operator == "lt":
        return actual_as_float < expected_as_float
    if operator == "lte":
        return actual_as_float <= expected_as_float
    return False


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def config_default_value(variation_lookup: Mapping[str, Any]) -> Any:
    return variation_lookup.get("control")
