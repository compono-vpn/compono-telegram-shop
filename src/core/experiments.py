import hashlib
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Experiment:
    key: str
    variants: tuple[str, ...]
    weights: tuple[int, ...]
    salt: str
    enabled: bool = True
    start_date: date | None = None

    def __post_init__(self) -> None:
        if not self.variants:
            raise ValueError(f"experiment '{self.key}': needs at least one variant")
        if len(self.variants) != len(self.weights):
            raise ValueError(f"experiment '{self.key}': variants/weights length mismatch")
        total = sum(self.weights)
        if total != 100:
            raise ValueError(f"experiment '{self.key}': weights must sum to 100, got {total}")


def _bucket(salt: str, telegram_id: int) -> int:
    digest = hashlib.sha256(f"{salt}:{telegram_id}".encode()).hexdigest()
    return int(digest[:8], 16) % 100


def assign_variant(experiment: Experiment, telegram_id: int) -> str:
    if not experiment.enabled:
        return experiment.variants[0]
    bucket = _bucket(experiment.salt, telegram_id)
    cumulative = 0
    for variant, weight in zip(experiment.variants, experiment.weights):
        cumulative += weight
        if bucket < cumulative:
            return variant
    return experiment.variants[-1]
