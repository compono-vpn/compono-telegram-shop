from dishka import AsyncContainer
from loguru import logger

from src.core.config import AppConfig
from src.infrastructure.kafka.base_consumer import SupervisedKafkaConsumer
from src.services.referral import ReferralService


class ReferralRewardConsumer(SupervisedKafkaConsumer):
    """Consumes billing's referral.reward events and grants the referrer's
    pending rewards. Billing only records the reward; without this nothing
    ever adds the days.
    """

    consumer_name = "referral_reward"

    def __init__(self, config: AppConfig, container: AsyncContainer) -> None:
        super().__init__(config, container)
        self._topic = config.kafka_referral_reward_topic
        self._group_id = f"{config.kafka_group_id}-referral-reward"

    @property
    def topic(self) -> str:
        return self._topic

    @property
    def group_id(self) -> str:
        return self._group_id

    async def _handle_message(self, payload: dict) -> None:
        telegram_id = payload.get("telegram_id")
        if not telegram_id:
            logger.warning(f"Referral reward event missing telegram_id, skipping: {payload}")
            return

        async with self._container() as request_container:
            referral_service = await request_container.get(ReferralService)
            await referral_service.issue_pending_rewards(int(telegram_id))
