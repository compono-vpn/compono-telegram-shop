from datetime import datetime
from typing import Self

from pydantic import Field, SecretStr, model_validator

from .base import BaseConfig


class EstimandConfig(BaseConfig, env_prefix="APP_EXPERIMENT_ESTIMAND_"):
    enabled: bool = False
    base_url: str = "https://estimand.app"
    api_key: SecretStr = SecretStr("")
    organization_id: str = ""
    project_id: str = ""
    environment_id: str = ""
    feature_key: str = "trial_offer"
    feature_id: str = ""
    trial_length_feature_key: str = "trial_length"
    trial_length_feature_id: str = ""
    start_tier_price_feature_key: str = "start_tier_price"
    start_tier_price_feature_id: str = ""
    intro_price_feature_key: str = "intro_price"
    intro_price_feature_id: str = ""
    checkout_flow_feature_key: str = "checkout_flow"
    checkout_flow_feature_id: str = ""
    payment_rescue_feature_key: str = "payment_rescue"
    payment_rescue_feature_id: str = ""
    on_variant: str = "trial_on"
    off_variant: str = "trial_off"
    conversion_event: str = "trial_activated"
    request_timeout: float = 3.0

    def is_fully_configured(self) -> bool:
        return bool(
            self.base_url
            and self.api_key.get_secret_value()
            and self.organization_id
            and self.project_id
            and self.environment_id
        )


class ExperimentsConfig(BaseConfig, env_prefix="APP_EXPERIMENT_"):
    trial_enabled: bool = False
    trial_on_weight: int = 50
    trial_offer_start_date: datetime | None = None
    trial_length_start_date: datetime | None = None
    start_tier_price_start_date: datetime | None = None
    intro_price_start_date: datetime | None = None
    checkout_flow_start_date: datetime | None = None
    payment_rescue_start_date: datetime | None = None
    estimand: EstimandConfig = Field(default_factory=EstimandConfig)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if not 0 <= self.trial_on_weight <= 100:
            raise ValueError("APP_EXPERIMENT_TRIAL_ON_WEIGHT must be between 0 and 100")
        return self
