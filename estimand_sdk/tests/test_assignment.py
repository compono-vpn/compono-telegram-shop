from __future__ import annotations

from unittest import TestCase

from estimand_sdk.assignment import (
    AssignmentResult,
    assign,
    choose_variation,
    fnv1a32,
    get_bucket_ranges,
    hash_value,
)


class AssignmentAlgorithmTestCase(TestCase):
    def test_fnv1a32_matches_reference_vectors(self) -> None:
        self.assertEqual(fnv1a32("checkout-redesignuser_123"), 3369010751)
        self.assertEqual(fnv1a32("emoji-seeduser_\U0001f600"), 1882293818)

    def test_hash_value_version_2_matches_reference_vectors(self) -> None:
        self.assertEqual(hash_value("checkout-redesign", "user_123", version=2), 0.7634)
        self.assertEqual(hash_value("checkout-redesign", "user_124", version=2), 0.8955)
        self.assertEqual(hash_value("checkout-redesign", "user_42", version=2), 0.9493)

    def test_hash_value_version_1_reference(self) -> None:
        self.assertEqual(hash_value("promo-banner", "u-42", version=1), 0.085)

    def test_bucket_ranges_weights_and_coverage(self) -> None:
        self.assertEqual(
            get_bucket_ranges(num_variations=2, coverage=0.5),
            [(0.0, 0.25), (0.5, 0.75)],
        )
        self.assertEqual(
            get_bucket_ranges(num_variations=3, coverage=1, weights=[0.2, 0.3, 0.5]),
            [(0.0, 0.2), (0.2, 0.5), (0.5, 1.0)],
        )
        self.assertEqual(
            get_bucket_ranges(num_variations=2, coverage=1, weights=[0, 100]),
            [(0.0, 0.0), (0.0, 1.0)],
        )

    def test_assign_variation_is_deterministic(self) -> None:
        result = assign(
            seed="checkout-redesign",
            unit="user_42",
            num_variations=2,
            coverage=1,
            weights=[0.25, 0.75],
        )
        self.assertEqual(
            result,
            AssignmentResult(
                bucket=0.9493,
                variation_index=1,
                ranges=[(0.0, 0.25), (0.25, 1.0)],
            ),
        )

    def test_choose_variation_half_open_interval(self) -> None:
        ranges = [(0.0, 0.25), (0.25, 0.5)]
        self.assertEqual(choose_variation(0.25, ranges), 1)
        self.assertEqual(choose_variation(0.0, ranges), 0)
        self.assertEqual(choose_variation(0.5, ranges), -1)
