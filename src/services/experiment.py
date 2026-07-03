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
        )
        return {trial.key: trial}

    def variant(self, experiment_key: str, telegram_id: int) -> str:
        return assign_variant(self._experiments[experiment_key], telegram_id)

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
        except Exception:
            logger.opt(exception=True).warning("Failed to record experiment exposure")
        return variant

    def record_conversion(self, experiment_key: str, telegram_id: int, event: str) -> None:
        variant = self.variant(experiment_key, telegram_id)
        EXPERIMENT_CONVERSIONS_TOTAL.labels(
            experiment=experiment_key, variant=variant, event=event
        ).inc()

    async def is_trial_offer_enabled(self, telegram_id: int) -> bool:
        variant = await self.expose(TRIAL_EXPERIMENT_KEY, telegram_id)
        return variant == TRIAL_VARIANT_ON
