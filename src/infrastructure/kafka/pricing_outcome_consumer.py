from dishka import AsyncContainer
from loguru import logger

from src.bot.routers.subscription.checkout_experiments import track_payment_outcome
from src.core.config import AppConfig
from src.infrastructure.kafka.base_consumer import SupervisedKafkaConsumer
from src.services.experiment import ExperimentService


class PricingOutcomeConsumer(SupervisedKafkaConsumer):
    def __init__(
        self,
        config: AppConfig,
        container: AsyncContainer,
        *,
        topic: str,
        group_suffix: str,
        event: str,
    ) -> None:
        super().__init__(config, container)
        self._topic = topic
        self._group_id = f"{config.kafka_group_id}-{group_suffix}"
        self._event = event
        self.consumer_name = f"pricing_outcome_{event}"

    @property
    def topic(self) -> str:
        return self._topic

    @property
    def group_id(self) -> str:
        return self._group_id

    async def _handle_message(self, payload: dict) -> None:
        experiment_attribution = payload.get("experiment_attribution")
        if not isinstance(experiment_attribution, dict):
            return

        telegram_id = payload.get("telegram_id")
        if not telegram_id:
            logger.warning(f"{self.consumer_name} event missing telegram_id, skipping")
            return

        async with self._container() as request_container:
            experiment_service = await request_container.get(ExperimentService)
            await track_payment_outcome(
                experiment_service=experiment_service,
                telegram_id=int(telegram_id),
                event=self._event,
                experiment_attribution=experiment_attribution,
            )
            logger.info(
                f"Tracked {self._event} pricing outcome for telegram_id={telegram_id}, "
                f"feature={experiment_attribution.get('feature_key')}, "
                f"variant={experiment_attribution.get('variant_key')}"
            )
