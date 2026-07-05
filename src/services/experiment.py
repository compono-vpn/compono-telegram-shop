from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from loguru import logger
from redis.asyncio import Redis

from src.core.config import AppConfig
from src.core.experiments import Experiment, assign_variant
from src.core.metrics import EXPERIMENT_CONVERSIONS_TOTAL, EXPERIMENT_EXPOSURES_TOTAL
from src.models.dto.user import UserDto

try:
    from estimand_sdk import (
        ConfigCacheMissError,
        EstimandClient,
        EstimandClientConfig,
    )
except Exception:
    EstimandClient = None
    EstimandClientConfig = None

    class ConfigCacheMissError(Exception):
        """Fallback when estimand_sdk is unavailable."""


TRIAL_EXPERIMENT_KEY = "trial_offer"
TRIAL_VARIANT_ON = "trial_on"
TRIAL_VARIANT_OFF = "trial_off"

_EXPOSURE_TTL = 60 * 60 * 24 * 30


class ExperimentFeature(str, Enum):
    TRIAL_OFFER = "trial_offer"
    TRIAL_LENGTH = "trial_length"
    START_TIER_PRICE = "start_tier_price"
    INTRO_PRICE = "intro_price"
    CHECKOUT_FLOW = "checkout_flow"
    PAYMENT_RESCUE = "payment_rescue"


@dataclass(frozen=True)
class _ResolvedEstimandConfig:
    enabled: bool = False
    base_url: str = "https://estimand.app"
    api_key: str = ""
    organization_id: str = ""
    project_id: str = ""
    environment_id: str = ""
    feature_key: str = TRIAL_EXPERIMENT_KEY
    feature_id: str = ""
    on_variant: str = TRIAL_VARIANT_ON
    off_variant: str = TRIAL_VARIANT_OFF
    conversion_event: str = "trial_activated"
    request_timeout: float = 3.0

    def is_fully_configured(self) -> bool:
        return bool(
            self.base_url
            and self.api_key
            and self.organization_id
            and self.project_id
            and self.environment_id
            and self.feature_key
            and self.feature_id
        )


@dataclass(frozen=True)
class _FeatureSpec:
    key: str
    experiment: Experiment
    start_date: datetime | None
    use_estimand: bool
    estimand_feature_key: str
    estimand_feature_id: str
    estimand_conversion_event: str
    estimand_on_variant: str
    estimand_off_variant: str


@dataclass(frozen=True)
class _FeatureEvaluation:
    feature_key: str
    variant: str
    payload: Any | None
    track_events: bool


@dataclass(frozen=True)
class FeatureEvaluation:
    feature_key: str
    variant: str
    payload: Any | None


class ExperimentService:
    def __init__(
        self,
        config: AppConfig,
        redis_client: Redis,
    ) -> None:
        self.config = config
        self.redis_client = redis_client
        self.estimand_config = self._resolve_estimand_config()
        self.estimand_client = self._build_estimand_client()
        self._features = self._build_features(config, self.estimand_config)
        self._fetched_config = None
        self._estimand_disabled = False

    @staticmethod
    def _as_str(value: Any, default: str) -> str:
        if isinstance(value, str):
            return value.strip() or default
        return default

    @staticmethod
    def _resolve_secret(value: Any) -> str:
        if value is None:
            return ""
        if hasattr(value, "get_secret_value"):
            return value.get_secret_value().strip()
        return str(value).strip() if value else ""

    @staticmethod
    def _coerce_start_date(value: Any) -> datetime | None:
        return value if isinstance(value, datetime) else None

    @classmethod
    def _resolve_trial_variants(cls, experiments_cfg: Any) -> tuple[str, str]:
        estimand_cfg = getattr(experiments_cfg, "estimand", None) if experiments_cfg else None
        return (
            cls._as_str(getattr(estimand_cfg, "on_variant", None), TRIAL_VARIANT_ON),
            cls._as_str(getattr(estimand_cfg, "off_variant", None), TRIAL_VARIANT_OFF),
        )

    def _resolve_estimand_config(self) -> _ResolvedEstimandConfig:
        experiment_cfg = getattr(self.config, "experiments", None)
        estimand_cfg = getattr(experiment_cfg, "estimand", None) if experiment_cfg else None
        raw_api_key = getattr(estimand_cfg, "api_key", "")

        return _ResolvedEstimandConfig(
            enabled=bool(getattr(estimand_cfg, "enabled", False)),
            base_url=self._as_str(
                getattr(estimand_cfg, "base_url", None),
                "https://estimand.app",
            ),
            api_key=self._resolve_secret(raw_api_key),
            organization_id=self._as_str(getattr(estimand_cfg, "organization_id", None), ""),
            project_id=self._as_str(getattr(estimand_cfg, "project_id", None), ""),
            environment_id=self._as_str(getattr(estimand_cfg, "environment_id", None), ""),
            feature_key=self._as_str(
                getattr(estimand_cfg, "feature_key", None),
                TRIAL_EXPERIMENT_KEY,
            ),
            feature_id=self._as_str(getattr(estimand_cfg, "feature_id", None), ""),
            on_variant=self._as_str(getattr(estimand_cfg, "on_variant", None), TRIAL_VARIANT_ON),
            off_variant=self._as_str(getattr(estimand_cfg, "off_variant", None), TRIAL_VARIANT_OFF),
            conversion_event=self._as_str(
                getattr(estimand_cfg, "conversion_event", None),
                "trial_activated",
            ),
            request_timeout=float(getattr(estimand_cfg, "request_timeout", 3.0)),
        )

    @staticmethod
    def _binary_variant_set(feature_key: str, suffix: str) -> tuple[str, str]:
        return (f"{feature_key}_{suffix}_off", f"{feature_key}_{suffix}_on")

    def _build_features(
        self,
        config: AppConfig,
        estimand_config: _ResolvedEstimandConfig,
    ) -> dict[str, _FeatureSpec]:
        cfg = config.experiments
        trial_on, trial_off = self._resolve_trial_variants(cfg)

        trial_length_off, trial_length_on = self._binary_variant_set("trial_length", "v1")
        (
            start_tier_price_off,
            start_tier_price_on,
        ) = self._binary_variant_set("start_tier_price", "v1")
        intro_price_off, intro_price_on = self._binary_variant_set("intro_price", "v1")
        checkout_flow_off, checkout_flow_on = self._binary_variant_set("checkout_flow", "v1")
        payment_rescue_off, payment_rescue_on = self._binary_variant_set("payment_rescue", "v1")

        return {
            TRIAL_EXPERIMENT_KEY: _FeatureSpec(
                key=TRIAL_EXPERIMENT_KEY,
                experiment=Experiment(
                    key=TRIAL_EXPERIMENT_KEY,
                    variants=(trial_on, trial_off),
                    weights=(cfg.trial_on_weight, 100 - cfg.trial_on_weight),
                    salt="trial_offer_v1",
                    enabled=bool(getattr(cfg, "trial_enabled", False)),
                ),
                start_date=self._coerce_start_date(
                    getattr(cfg, "trial_offer_start_date", None)
                ),
                use_estimand=True,
                estimand_feature_key=estimand_config.feature_key,
                estimand_feature_id=estimand_config.feature_id,
                estimand_conversion_event=estimand_config.conversion_event,
                estimand_on_variant=estimand_config.on_variant,
                estimand_off_variant=estimand_config.off_variant,
            ),
            ExperimentFeature.TRIAL_LENGTH.value: _FeatureSpec(
                key=ExperimentFeature.TRIAL_LENGTH.value,
                experiment=Experiment(
                    key=ExperimentFeature.TRIAL_LENGTH.value,
                    variants=(trial_length_off, trial_length_on),
                    weights=(100, 0),
                    salt="trial_length_v1",
                    enabled=False,
                ),
                start_date=self._coerce_start_date(
                    getattr(cfg, "trial_length_start_date", None)
                ),
                use_estimand=False,
                estimand_feature_key=ExperimentFeature.TRIAL_LENGTH.value,
                estimand_feature_id="",
                estimand_conversion_event=estimand_config.conversion_event,
                estimand_on_variant=ExperimentFeature.TRIAL_LENGTH.value + "_on",
                estimand_off_variant=ExperimentFeature.TRIAL_LENGTH.value + "_off",
            ),
            ExperimentFeature.START_TIER_PRICE.value: _FeatureSpec(
                key=ExperimentFeature.START_TIER_PRICE.value,
                experiment=Experiment(
                    key=ExperimentFeature.START_TIER_PRICE.value,
                    variants=(start_tier_price_off, start_tier_price_on),
                    weights=(100, 0),
                    salt="start_tier_price_v1",
                    enabled=False,
                ),
                start_date=self._coerce_start_date(
                    getattr(cfg, "start_tier_price_start_date", None)
                ),
                use_estimand=False,
                estimand_feature_key=ExperimentFeature.START_TIER_PRICE.value,
                estimand_feature_id="",
                estimand_conversion_event=estimand_config.conversion_event,
                estimand_on_variant=ExperimentFeature.START_TIER_PRICE.value + "_on",
                estimand_off_variant=ExperimentFeature.START_TIER_PRICE.value + "_off",
            ),
            ExperimentFeature.INTRO_PRICE.value: _FeatureSpec(
                key=ExperimentFeature.INTRO_PRICE.value,
                experiment=Experiment(
                    key=ExperimentFeature.INTRO_PRICE.value,
                    variants=(intro_price_off, intro_price_on),
                    weights=(100, 0),
                    salt="intro_price_v1",
                    enabled=False,
                ),
                start_date=self._coerce_start_date(
                    getattr(cfg, "intro_price_start_date", None)
                ),
                use_estimand=False,
                estimand_feature_key=ExperimentFeature.INTRO_PRICE.value,
                estimand_feature_id="",
                estimand_conversion_event=estimand_config.conversion_event,
                estimand_on_variant=ExperimentFeature.INTRO_PRICE.value + "_on",
                estimand_off_variant=ExperimentFeature.INTRO_PRICE.value + "_off",
            ),
            ExperimentFeature.CHECKOUT_FLOW.value: _FeatureSpec(
                key=ExperimentFeature.CHECKOUT_FLOW.value,
                experiment=Experiment(
                    key=ExperimentFeature.CHECKOUT_FLOW.value,
                    variants=(checkout_flow_off, checkout_flow_on),
                    weights=(100, 0),
                    salt="checkout_flow_v1",
                    enabled=False,
                ),
                start_date=self._coerce_start_date(
                    getattr(cfg, "checkout_flow_start_date", None)
                ),
                use_estimand=False,
                estimand_feature_key=ExperimentFeature.CHECKOUT_FLOW.value,
                estimand_feature_id="",
                estimand_conversion_event=estimand_config.conversion_event,
                estimand_on_variant=ExperimentFeature.CHECKOUT_FLOW.value + "_on",
                estimand_off_variant=ExperimentFeature.CHECKOUT_FLOW.value + "_off",
            ),
            ExperimentFeature.PAYMENT_RESCUE.value: _FeatureSpec(
                key=ExperimentFeature.PAYMENT_RESCUE.value,
                experiment=Experiment(
                    key=ExperimentFeature.PAYMENT_RESCUE.value,
                    variants=(payment_rescue_off, payment_rescue_on),
                    weights=(100, 0),
                    salt="payment_rescue_v1",
                    enabled=False,
                ),
                start_date=self._coerce_start_date(
                    getattr(cfg, "payment_rescue_start_date", None)
                ),
                use_estimand=False,
                estimand_feature_key=ExperimentFeature.PAYMENT_RESCUE.value,
                estimand_feature_id="",
                estimand_conversion_event=estimand_config.conversion_event,
                estimand_on_variant=ExperimentFeature.PAYMENT_RESCUE.value + "_on",
                estimand_off_variant=ExperimentFeature.PAYMENT_RESCUE.value + "_off",
            ),
        }

    def _build_estimand_client(self) -> Any | None:
        if (
            not self.estimand_config.enabled
            or not self.estimand_config.is_fully_configured()
            or not bool(getattr(self.config.experiments, "trial_enabled", False))
            or EstimandClient is None
            or EstimandClientConfig is None
        ):
            return None

        try:
            return EstimandClient(
                config=EstimandClientConfig(
                    base_url=self.estimand_config.base_url,
                    api_key=self.estimand_config.api_key,
                    request_timeout=self.estimand_config.request_timeout,
                )
            )
        except Exception:
            logger.opt(exception=True).warning(
                "Failed to initialize Estimand client; using local experiment fallback"
            )
            return None

    def _should_use_estimand(self, feature: _FeatureSpec) -> bool:
        return (
            feature.use_estimand
            and bool(
                self.estimand_config.enabled
                and self.estimand_config.is_fully_configured()
                and bool(getattr(self.config.experiments, "trial_enabled", False))
                and not self._estimand_disabled
                and self.estimand_client is not None
            )
            and bool(feature.estimand_feature_id)
            and bool(feature.estimand_feature_key)
        )

    def _fetch_estimand_config(self) -> Any | None:
        if self._fetched_config is not None:
            return self._fetched_config
        if self.estimand_client is None:
            return None

        try:
            self._fetched_config = self.estimand_client.fetch_config(
                organization_id=self.estimand_config.organization_id,
                project_id=self.estimand_config.project_id,
                environment_id=self.estimand_config.environment_id,
            )
            return self._fetched_config
        except (Exception, ConfigCacheMissError):
            logger.opt(exception=True).warning(
                "Failed to fetch Estimand config; using local experiment fallback"
            )
            self._estimand_disabled = True
            return None

    def _is_feature_enabled_for_user(
        self,
        feature: _FeatureSpec,
        created_at: datetime | None,
    ) -> bool:
        if feature.start_date is None:
            return True

        if created_at is None:
            return False

        return created_at >= feature.start_date

    def _feature_for_key(self, experiment_key: str) -> _FeatureSpec:
        return self._features[experiment_key]

    def _evaluate(
        self,
        experiment_key: str,
        telegram_id: int,
        created_at: datetime | None,
    ) -> _FeatureEvaluation:
        feature = self._feature_for_key(experiment_key)

        if not self._is_feature_enabled_for_user(feature, created_at):
            return _FeatureEvaluation(
                feature_key=feature.key,
                variant=feature.experiment.variants[0],
                payload=None,
                track_events=False,
            )

        if not self._should_use_estimand(feature):
            return _FeatureEvaluation(
                feature_key=feature.key,
                variant=assign_variant(feature.experiment, telegram_id),
                payload=None,
                track_events=True,
            )

        try:
            payload = self._fetch_estimand_config()
            if payload is None:
                return _FeatureEvaluation(
                    feature_key=feature.key,
                    variant=assign_variant(feature.experiment, telegram_id),
                    payload=None,
                    track_events=True,
                )

            result = self.estimand_client.evaluate_feature(
                feature_key=feature.estimand_feature_key,
                unit_id=str(telegram_id),
                config=payload,
            )
            variation = getattr(result, "variation_key", None)
            if variation in feature.experiment.variants:
                return _FeatureEvaluation(
                    feature_key=feature.key,
                    variant=variation,
                    payload=getattr(result, "value", None),
                    track_events=True,
                )

            logger.warning(
                f"Estimand feature '{experiment_key}' returned unexpected variant "
                f"'{variation}', using local assignment"
            )
        except Exception:
            logger.opt(exception=True).warning(
                "Failed to evaluate Estimand feature; using local fallback"
            )
            self._estimand_disabled = True

        return _FeatureEvaluation(
            feature_key=feature.key,
            variant=assign_variant(feature.experiment, telegram_id),
            payload=None,
            track_events=True,
        )

    def _get_feature_variants(self, experiment_key: str) -> tuple[str, str]:
        feature = self._feature_for_key(experiment_key)
        on_default = feature.experiment.variants[0]
        off_default = feature.experiment.variants[1]

        if feature.key == TRIAL_EXPERIMENT_KEY:
            on_default = self._as_str(feature.estimand_on_variant, on_default)
            off_default = self._as_str(feature.estimand_off_variant, off_default)

        return on_default, off_default

    def _track_estimand_exposure(
        self,
        feature: _FeatureSpec,
        telegram_id: int,
        variant: str,
    ) -> None:
        if not self._should_use_estimand(feature):
            return

        try:
            self.estimand_client.track_exposure(
                project_id=self.estimand_config.project_id,
                environment_id=self.estimand_config.environment_id,
                feature_id=feature.estimand_feature_id,
                unit_id=str(telegram_id),
                variant_key=variant,
            )
        except Exception:
            logger.opt(exception=True).warning(
                "Failed to send Estimand exposure event; keeping local metrics path"
            )

    def _track_estimand_conversion(
        self,
        feature: _FeatureSpec,
        telegram_id: int,
        variant: str,
        event: str,
    ) -> None:
        if not self._should_use_estimand(feature):
            return

        event_name = event or feature.estimand_conversion_event
        if not event_name:
            return

        try:
            self.estimand_client.track_conversion(
                project_id=self.estimand_config.project_id,
                environment_id=self.estimand_config.environment_id,
                feature_id=feature.estimand_feature_id,
                unit_id=str(telegram_id),
                event_name=event_name,
                variant_key=variant,
            )
        except Exception:
            logger.opt(exception=True).warning(
                "Failed to send Estimand conversion event; keeping local metrics path"
            )

    def variant(
        self,
        experiment_key: str,
        telegram_id: int,
        created_at: datetime | None = None,
    ) -> str:
        return self._evaluate(experiment_key, telegram_id, created_at).variant

    def evaluate_feature_for_user(
        self,
        user: UserDto,
        experiment_key: str | ExperimentFeature,
    ) -> FeatureEvaluation:
        feature_key = self._as_str(
            experiment_key if isinstance(experiment_key, str) else experiment_key.value,
            "",
        )
        evaluation = self._evaluate(feature_key, user.telegram_id, user.created_at)
        return FeatureEvaluation(
            feature_key=evaluation.feature_key,
            variant=evaluation.variant,
            payload=evaluation.payload,
        )

    async def expose(
        self,
        experiment_key: str,
        telegram_id: int,
        created_at: datetime | None = None,
    ) -> str:
        feature = self._feature_for_key(experiment_key)
        evaluation = self._evaluate(experiment_key, telegram_id, created_at)
        variant = evaluation.variant

        if not evaluation.track_events:
            return variant

        try:
            first_time = await self.redis_client.set(
                name=f"exp_exposed:{experiment_key}:{telegram_id}",
                value=variant,
                nx=True,
                ex=_EXPOSURE_TTL,
            )
            if first_time:
                EXPERIMENT_EXPOSURES_TOTAL.labels(experiment=experiment_key, variant=variant).inc()
                self._track_estimand_exposure(feature, telegram_id, variant)
        except Exception:
            logger.opt(exception=True).warning("Failed to record experiment exposure")
        return variant

    def record_conversion(
        self,
        experiment_key: str,
        telegram_id: int,
        event: str,
        created_at: datetime | None = None,
    ) -> None:
        feature = self._feature_for_key(experiment_key)
        evaluation = self._evaluate(experiment_key, telegram_id, created_at)

        if not evaluation.track_events:
            return

        EXPERIMENT_CONVERSIONS_TOTAL.labels(
            experiment=experiment_key, variant=evaluation.variant, event=event
        ).inc()
        self._track_estimand_conversion(feature, telegram_id, evaluation.variant, event)

    async def is_trial_offer_enabled(self, user_or_telegram_id: int | UserDto) -> bool:
        if isinstance(user_or_telegram_id, UserDto):
            telegram_id = user_or_telegram_id.telegram_id
            created_at = user_or_telegram_id.created_at
        else:
            telegram_id = user_or_telegram_id
            created_at = None

        variant = await self.expose(TRIAL_EXPERIMENT_KEY, telegram_id, created_at)
        on_variant, _ = self._get_feature_variants(TRIAL_EXPERIMENT_KEY)
        return variant == on_variant
