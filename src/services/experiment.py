from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger
from redis.asyncio import Redis

from src.core.config import AppConfig
from src.core.experiments import Experiment, assign_variant
from src.core.metrics import EXPERIMENT_CONVERSIONS_TOTAL, EXPERIMENT_EXPOSURES_TOTAL

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


class ExperimentService:
    def __init__(
        self,
        config: AppConfig,
        redis_client: Redis,
        estimand_client: Any | None = None,
    ) -> None:
        self.config = config
        self.redis_client = redis_client
        self.estimand_config = self._resolve_estimand_config()
        self.estimand_client = estimand_client or self._build_estimand_client()
        self._experiments = self._build_experiments(config)
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

    def _get_trial_variants(self, config: AppConfig | None = None) -> tuple[str, str]:
        experiments_cfg = getattr(config or self.config, "experiments", None)
        return self._resolve_trial_variants(experiments_cfg)

    @staticmethod
    def _build_experiments(config: AppConfig) -> dict[str, Experiment]:
        cfg = config.experiments
        trial_on, trial_off = ExperimentService._resolve_trial_variants(cfg)
        trial = Experiment(
            key=TRIAL_EXPERIMENT_KEY,
            variants=(
                trial_on,
                trial_off,
            ),
            weights=(cfg.trial_on_weight, 100 - cfg.trial_on_weight),
            salt="trial_offer_v1",
            enabled=bool(getattr(cfg, "trial_enabled", False)),
        )
        return {trial.key: trial}

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

    def _trial_enabled(self) -> bool:
        return bool(
            self.estimand_config.enabled
            and self.estimand_config.is_fully_configured()
            and bool(getattr(self.config.experiments, "trial_enabled", False))
            and not self._estimand_disabled
            and self.estimand_client is not None
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

    def _should_use_estimand(self, experiment_key: str) -> bool:
        return bool(
            self._trial_enabled()
            and experiment_key == TRIAL_EXPERIMENT_KEY
            and self.estimand_client is not None
        )

    def variant(self, experiment_key: str, telegram_id: int) -> str:
        if not self._should_use_estimand(experiment_key):
            return assign_variant(self._experiments[experiment_key], telegram_id)

        try:
            payload = self._fetch_estimand_config()
            if payload is None:
                return assign_variant(self._experiments[experiment_key], telegram_id)

            result = self.estimand_client.evaluate_feature(
                feature_key=self.estimand_config.feature_key,
                unit_id=str(telegram_id),
                config=payload,
            )
            variation = getattr(result, "variation_key", None)
            on_variant, off_variant = self._get_trial_variants(self.config)
            if variation in (on_variant, off_variant):
                return variation

            logger.warning(
                f"Estimand experiment '{experiment_key}' returned unexpected variant "
                f"'{variation}', using local assignment"
            )
        except Exception:
            logger.opt(exception=True).warning(
                "Failed to evaluate Estimand experiment; using local fallback"
            )
            self._estimand_disabled = True

        return assign_variant(self._experiments[experiment_key], telegram_id)

    def _track_estimand_exposure(self, telegram_id: int, variant: str) -> None:
        if not self._trial_enabled():
            return

        try:
            self.estimand_client.track_exposure(
                project_id=self.estimand_config.project_id,
                environment_id=self.estimand_config.environment_id,
                feature_id=self.estimand_config.feature_id,
                unit_id=str(telegram_id),
                variant_key=variant,
            )
        except Exception:
            logger.opt(exception=True).warning(
                "Failed to send Estimand exposure event; keeping local metrics path"
            )

    def _track_estimand_conversion(self, telegram_id: int, variant: str, event: str) -> None:
        if not self._trial_enabled():
            return

        event_name = event or self.estimand_config.conversion_event
        if not event_name:
            return

        try:
            self.estimand_client.track_conversion(
                project_id=self.estimand_config.project_id,
                environment_id=self.estimand_config.environment_id,
                feature_id=self.estimand_config.feature_id,
                unit_id=str(telegram_id),
                event_name=event_name,
                variant_key=variant,
            )
        except Exception:
            logger.opt(exception=True).warning(
                "Failed to send Estimand conversion event; keeping local metrics path"
            )

    async def expose(self, experiment_key: str, telegram_id: int) -> str:
        variant = self.variant(experiment_key, telegram_id)
        try:
            first_time = await self.redis_client.set(
                name=f"exp_exposed:{experiment_key}:{telegram_id}",
                value=variant,
                nx=True,
                ex=_EXPOSURE_TTL,
            )
            if first_time:
                EXPERIMENT_EXPOSURES_TOTAL.labels(experiment=experiment_key, variant=variant).inc()
                if self._trial_enabled():
                    self._track_estimand_exposure(telegram_id, variant)
        except Exception:
            logger.opt(exception=True).warning("Failed to record experiment exposure")
        return variant

    def record_conversion(self, experiment_key: str, telegram_id: int, event: str) -> None:
        variant = self.variant(experiment_key, telegram_id)
        EXPERIMENT_CONVERSIONS_TOTAL.labels(
            experiment=experiment_key, variant=variant, event=event
        ).inc()
        if self._trial_enabled():
            self._track_estimand_conversion(telegram_id, variant, event)

    async def is_trial_offer_enabled(self, telegram_id: int) -> bool:
        variant = await self.expose(TRIAL_EXPERIMENT_KEY, telegram_id)
        on_variant, _ = self._get_trial_variants(self.config)
        return variant == on_variant
