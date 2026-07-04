from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


GROWTHBOOK_BUCKET_SCALE = {
    1: 1000,
    2: 10000,
}


@dataclass(frozen=True)
class AssignmentResult:
    """Result of deterministic bucket selection."""

    bucket: float
    variation_index: int
    ranges: list[tuple[float, float]]


def fnv1a32(value: str) -> int:
    """Return the 32-bit FNV-1a hash for a UTF-16LE encoded string."""

    hash_value = 0x811C9DC5
    encoded = value.encode("utf-16-le", "surrogatepass")
    for index in range(0, len(encoded), 2):
        code_unit = encoded[index] | (encoded[index + 1] << 8)
        hash_value ^= code_unit
        hash_value = (
            hash_value
            + (hash_value << 1)
            + (hash_value << 4)
            + (hash_value << 7)
            + (hash_value << 8)
            + (hash_value << 24)
        )
        hash_value &= 0xFFFFFFFF
    return hash_value


def hash_value(seed: str, unit: str, *, version: int = 1) -> float:
    """Return a normalized hash bucket value in [0, 1)."""

    if version not in GROWTHBOOK_BUCKET_SCALE:
        raise ValueError("hash version must be 1 or 2")

    if version == 1:
        hashed = fnv1a32(f"{unit}{seed}")
    else:
        hashed = fnv1a32(str(fnv1a32(f"{seed}{unit}")))

    return (hashed % GROWTHBOOK_BUCKET_SCALE[version]) / GROWTHBOOK_BUCKET_SCALE[version]


def get_bucket_ranges(
    *,
    num_variations: int,
    coverage: float = 1,
    weights: Sequence[float] | None = None,
) -> list[tuple[float, float]]:
    """Build GrowthBook-style ranges for one feature rule."""

    if coverage < 0:
        coverage = 0.0
    elif coverage > 1:
        coverage = 1.0

    if num_variations <= 0:
        return []

    default_weight = 1 / num_variations
    normalized_weights = list(weights) if weights else [default_weight] * num_variations

    if len(normalized_weights) != num_variations:
        normalized_weights = [default_weight] * num_variations

    total = sum(normalized_weights)
    if 1.01 < total <= 100.0 and all(weight >= 0 for weight in normalized_weights):
        normalized_weights = [weight / 100.0 for weight in normalized_weights]
        total = sum(normalized_weights)

    if total < 0.99 or total > 1.01:
        normalized_weights = [default_weight] * num_variations

    ranges: list[tuple[float, float]] = []
    cumulative = 0.0
    for weight in normalized_weights:
        start = cumulative
        cumulative += weight
        ranges.append((start, start + coverage * weight))
    return ranges


def choose_variation(bucket: float, ranges: Sequence[tuple[float, float]]) -> int:
    """Return the variation index for a bucket value."""

    for index, (start, end) in enumerate(ranges):
        if bucket >= start and bucket < end:
            return index
    return -1


def assign(
    *,
    seed: str,
    unit: str,
    num_variations: int,
    coverage: float = 1,
    weights: Sequence[float] | None = None,
    hash_version: int = 2,
) -> AssignmentResult:
    """Return deterministic assignment metadata for one opaque unit id."""

    bucket = hash_value(seed=seed, unit=unit, version=hash_version)
    ranges = get_bucket_ranges(
        num_variations=num_variations,
        coverage=coverage,
        weights=weights,
    )
    variation_index = choose_variation(bucket, ranges)
    return AssignmentResult(
        bucket=bucket,
        variation_index=variation_index,
        ranges=ranges,
    )
