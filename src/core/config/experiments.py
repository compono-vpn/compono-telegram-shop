from datetime import date
from typing import Optional, Self

from pydantic import model_validator

from .base import BaseConfig


class ExperimentsConfig(BaseConfig, env_prefix="APP_EXPERIMENT_"):
    trial_enabled: bool = False
    trial_on_weight: int = 50
    trial_start_date: Optional[date] = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if not 0 <= self.trial_on_weight <= 100:
            raise ValueError("APP_EXPERIMENT_TRIAL_ON_WEIGHT must be between 0 and 100")
        return self
