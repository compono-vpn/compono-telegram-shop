from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class VariationConfig:
    """Single variation definition from compiled config."""

    key: str
    name: str
    value: Any
    weight: int | float
    is_control: bool
    description: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "VariationConfig":
        return cls(
            key=str(payload["key"]),
            name=str(payload.get("name", "")),
            value=payload.get("value"),
            weight=float(payload.get("weight", 0)),
            is_control=bool(payload.get("isControl", False)),
            description=str(payload.get("description", "")),
        )


@dataclass(frozen=True)
class RuleConfig:
    """Targeting rule from compiled config."""

    id: str
    condition: dict[str, Any]
    variation_keys: list[str]
    coverage: float
    priority: int
    is_default: bool
    force: str | None
    seed: str
    hash_version: int
    weights: list[float] | None
    ranges: list[tuple[float, float]] | None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "RuleConfig":
        raw_weights = payload.get("weights")
        raw_ranges = payload.get("ranges")
        return cls(
            id=str(payload["id"]),
            condition=dict(payload.get("condition", {})),
            variation_keys=[str(item) for item in payload.get("variationKeys", [])],
            coverage=float(payload.get("coverage", 1.0)),
            priority=int(payload.get("priority", 0)),
            is_default=bool(payload.get("isDefault", False)),
            force=payload.get("force") if isinstance(payload.get("force"), str) else None,
            seed=str(payload.get("seed", "")),
            hash_version=int(payload.get("hashVersion", 2)),
            weights=[float(value) for value in raw_weights] if isinstance(raw_weights, list) else None,
            ranges=[
                (float(start), float(end))
                for start, end in raw_ranges
                if isinstance(raw_ranges, list)
            ]
            if isinstance(raw_ranges, list)
            else None,
        )


@dataclass(frozen=True)
class FeatureConfig:
    """Compiled config payload for one feature key."""

    type: str
    default_value: Any
    seed: str
    unit_type: str
    enabled: bool
    published: bool
    variations: list[VariationConfig]
    rules: list[RuleConfig]
    forced_variations: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "FeatureConfig":
        raw_forced_variations = payload.get("forcedVariations", {})
        forced_variations = raw_forced_variations if isinstance(raw_forced_variations, Mapping) else {}
        return cls(
            type=str(payload["type"]),
            default_value=payload.get("defaultValue"),
            seed=str(payload["seed"]),
            unit_type=str(payload["unitType"]),
            enabled=bool(payload.get("enabled", False)),
            published=bool(payload.get("published", False)),
            variations=[VariationConfig.from_mapping(raw) for raw in payload.get("variations", [])],
            rules=[RuleConfig.from_mapping(raw) for raw in payload.get("rules", [])],
            forced_variations={
                str(unit_id): str(variation_key)
                for unit_id, variation_key in forced_variations.items()
                if isinstance(variation_key, str)
            },
        )


@dataclass(frozen=True)
class ConfigPayload:
    """Strongly-typed representation of `/api/v1/config`."""

    revision: str
    features: dict[str, FeatureConfig]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ConfigPayload":
        features_payload = payload.get("features", {})
        return cls(
            revision=str(payload["revision"]),
            features={
                str(feature_key): FeatureConfig.from_mapping(feature_payload)
                for feature_key, feature_payload in dict(features_payload).items()
            },
        )


@dataclass(frozen=True)
class EventPayload:
    """JSON-ready event envelope used by `/api/v1/events`."""

    event_id: str
    project_id: str
    environment_id: str
    feature_id: str
    unit_id: str
    event_type: str
    event_name: str | None = None
    variant_key: str | None = None
    variation_id: str | None = None
    value: float = 1.0
    timestamp: str | None = None
    properties: dict[str, Any] | None = None

    def to_mapping(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event_id": self.event_id,
            "project_id": self.project_id,
            "environment_id": self.environment_id,
            "feature_id": self.feature_id,
            "unit_id": self.unit_id,
            "event_type": self.event_type,
            "value": float(self.value),
        }
        if self.event_name is not None:
            payload["event_name"] = self.event_name
        if self.variant_key is not None:
            payload["variant_key"] = self.variant_key
        if self.variation_id is not None:
            payload["variation_id"] = self.variation_id
        if self.timestamp is not None:
            payload["timestamp"] = self.timestamp
        if self.properties is not None:
            payload["properties"] = self.properties
        return payload


@dataclass(frozen=True)
class EventBatchResponse:
    """Response payload from event ingestion endpoint."""

    status: str
    code: str
    ingested: int
    deduplicated: int
    detail: str | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "EventBatchResponse":
        return cls(
            status=str(payload.get("status", "")),
            code=str(payload.get("code", "")),
            ingested=int(payload.get("ingested", 0)),
            deduplicated=int(payload.get("deduplicated", 0)),
            detail=payload.get("detail"),
        )
