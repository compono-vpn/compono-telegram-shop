from datetime import datetime

from loguru import logger
from redis.asyncio import Redis

from src.core.config import AppConfig
from src.core.experiments import Experiment, assign_variant
from src.core.metrics import EXPERIMENT_CONVERSIONS_TOTAL, EXPERIMENT_EXPOSURES_TOTAL

TRIAL_EXPERIMENT_KEY = "trial_offer"
TRIAL_VARIANT_ON = "trial_on"
TRIAL_VARIANT_OFF = "trial_off"

_EXPOSURE_TTL = 60 * 60 * 24 * 30


class ExperimentService:
    def __init__(self, config: AppConfig, redis_client: Redis) -> None:
        self.config = config
        self.redis_client = redis_client
        self._experiments = self._build_experiments(config)

    @staticmethod
    def _build_experiments(config: AppConfig) -> dict[str, Experiment]:
        cfg = config.experiments
        trial = Experiment(
            key=TRIAL_EXPERIMENT_KEY,
            variants=(TRIAL_VARIANT_ON, TRIAL_VARIANT_OFF),
            weights=(cfg.trial_on_weight, 100 - cfg.trial_on_weight),
            salt="trial_offer_v1",
            enabled=cfg.trial_enabled,
            start_date=cfg.trial_start_date,
        )
        return {trial.key: trial}

    @staticmethod
    def _is_new_user(experiment: Experiment, created_at: datetime | None) -> bool:
        if experiment.start_date is None or created_at is None:
            return False
        return created_at.date() >= experiment.start_date

    def variant(
        self,
        experiment_key: str,
        telegram_id: int,
        *,
        created_at: datetime | None = None,
    ) -> str:
        experiment = self._experiments[experiment_key]
        if not self._is_new_user(experiment, created_at):
            return experiment.variants[0]
        return assign_variant(experiment, telegram_id)

    async def expose(
        self,
        experiment_key: str,
        telegram_id: int,
        *,
        created_at: datetime | None = None,
    ) -> str:
        experiment = self._experiments[experiment_key]
        if not self._is_new_user(experiment, created_at):
            return experiment.variants[0]

        variant = assign_variant(experiment, telegram_id)
        try:
            first_time = await self.redis_client.set(
                name=f"exp_exposed:{experiment_key}:{telegram_id}",
                value=variant,
                nx=True,
                ex=_EXPOSURE_TTL,
            )
            if first_time:
                EXPERIMENT_EXPOSURES_TOTAL.labels(experiment=experiment_key, variant=variant).inc()
        except Exception:
            logger.opt(exception=True).warning("Failed to record experiment exposure")
        return variant

    def record_conversion(
        self,
        experiment_key: str,
        telegram_id: int,
        event: str,
        *,
        created_at: datetime | None = None,
    ) -> None:
        variant = self.variant(experiment_key, telegram_id, created_at=created_at)
        EXPERIMENT_CONVERSIONS_TOTAL.labels(
            experiment=experiment_key, variant=variant, event=event
        ).inc()

    async def is_trial_offer_enabled(
        self,
        telegram_id: int,
        *,
        created_at: datetime | None = None,
    ) -> bool:
        variant = await self.expose(TRIAL_EXPERIMENT_KEY, telegram_id, created_at=created_at)
        return variant == TRIAL_VARIANT_ON
