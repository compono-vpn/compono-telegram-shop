from typing import Optional
from uuid import UUID

from loguru import logger
from redis.asyncio import Redis

from src.core.config import AppConfig
from src.core.enums import (
    BroadcastAudience,
    BroadcastMessageStatus,
    BroadcastStatus,
)
from src.infrastructure.billing import (
    BillingClient,
    billing_broadcast_message_to_dto,
    billing_broadcast_to_dto,
    billing_user_to_dto,
)
from src.infrastructure.redis import RedisRepository
from src.models.dto import BroadcastDto, BroadcastMessageDto, UserDto

from .base_billing import BaseBillingService


class BroadcastService(BaseBillingService):
    billing: BillingClient

    def __init__(
        self,
        config: AppConfig,
        redis_client: Redis,
        redis_repository: RedisRepository,
        #
        billing: BillingClient,
    ) -> None:
        super().__init__(config, redis_client, redis_repository)
        self.billing = billing

    async def create(self, broadcast: BroadcastDto) -> BroadcastDto:
        data = {
            "task_id": str(broadcast.task_id),
            "status": broadcast.status.value,
            "audience": broadcast.audience.value,
            "total_count": broadcast.total_count,
            "success_count": broadcast.success_count,
            "failed_count": broadcast.failed_count,
            "payload": broadcast.payload.model_dump() if broadcast.payload else None,
        }

        billing_broadcast = await self.billing.create_broadcast(data)
        logger.info(f"Created broadcast '{broadcast.task_id}'")
        return billing_broadcast_to_dto(billing_broadcast)

    async def create_messages(
        self,
        broadcast_id: int,
        messages: list[BroadcastMessageDto],
    ) -> list[BroadcastMessageDto]:
        messages_data = [
            {
                "user_id": m.user_id,
                "status": m.status.value,
            }
            for m in messages
        ]

        billing_messages = await self.billing.create_broadcast_messages(broadcast_id, messages_data)
        return [billing_broadcast_message_to_dto(m) for m in billing_messages]

    async def get(self, task_id: UUID) -> Optional[BroadcastDto]:
        # The billing API uses integer IDs; task_id is used as a lookup param.
        # We list all broadcasts and find by task_id. For a single lookup,
        # the billing API should support GET by task_id. For now, use the list
        # and filter approach until a dedicated endpoint exists.
        broadcasts = await self.billing.list_broadcasts()
        for bb in broadcasts:
            if bb.TaskID == str(task_id):
                logger.debug(f"Retrieved broadcast '{task_id}'")
                return billing_broadcast_to_dto(bb)

        logger.warning(f"Broadcast '{task_id}' not found")
        return None

    async def get_all(self) -> list[BroadcastDto]:
        billing_broadcasts = await self.billing.list_broadcasts()
        return list(reversed([billing_broadcast_to_dto(bb) for bb in billing_broadcasts]))

    async def update(self, broadcast: BroadcastDto) -> Optional[BroadcastDto]:
        if broadcast.id is None:
            logger.warning(
                f"Attempted to update broadcast '{broadcast.task_id}', but broadcast has no ID"
            )
            return None

        data = broadcast.changed_data
        # Convert enum values to strings for the API
        if "status" in data and isinstance(data["status"], BroadcastStatus):
            data["status"] = data["status"].value
        if "audience" in data and isinstance(data["audience"], BroadcastAudience):
            data["audience"] = data["audience"].value
        if "payload" in data:
            from src.core.utils.message_payload import MessagePayload  # noqa: PLC0415

            if isinstance(data["payload"], MessagePayload):
                data["payload"] = data["payload"].model_dump()

        billing_broadcast = await self.billing.update_broadcast(broadcast.id, data)

        if billing_broadcast:
            logger.info(f"Updated broadcast '{broadcast.task_id}' successfully")
        else:
            logger.warning(
                f"Attempted to update broadcast '{broadcast.task_id}', "
                f"but broadcast was not found or update failed"
            )

        return billing_broadcast_to_dto(billing_broadcast) if billing_broadcast else None

    async def update_message(self, broadcast_id: int, message: BroadcastMessageDto) -> None:
        data = message.changed_data
        if "status" in data and isinstance(data["status"], BroadcastMessageStatus):
            data["status"] = data["status"].value
        data["user_id"] = message.user_id
        data["broadcast_id"] = broadcast_id

        await self.billing.update_broadcast_messages([data])

    async def bulk_update_messages(self, messages: list[BroadcastMessageDto]) -> None:
        messages_data = []
        for m in messages:
            entry: dict = m.model_dump()
            if isinstance(entry.get("status"), BroadcastMessageStatus):
                entry["status"] = entry["status"].value
            messages_data.append(entry)

        await self.billing.update_broadcast_messages(messages_data)

    async def delete_broadcast(self, broadcast_id: int) -> None:
        await self.billing.delete_broadcast(broadcast_id)

    async def get_status(self, task_id: UUID) -> Optional[BroadcastStatus]:
        broadcast = await self.get(task_id)
        return broadcast.status if broadcast else None

    #

    async def get_audience_count(
        self,
        audience: BroadcastAudience,
        plan_id: Optional[int] = None,
    ) -> int:
        logger.debug(f"Counting audience '{audience}' for plan '{plan_id}'")
        count = await self.billing.get_broadcast_audience_count(audience.value, plan_id=plan_id)
        logger.debug(f"Audience count for '{audience}' (plan={plan_id}) is '{count}'")
        return count

    async def get_audience_users(
        self,
        audience: BroadcastAudience,
        plan_id: Optional[int] = None,
    ) -> list[UserDto]:
        logger.debug(f"Retrieving users for audience '{audience}', plan_id: {plan_id}")
        billing_users = await self.billing.get_broadcast_audience(audience.value, plan_id=plan_id)
        users = [billing_user_to_dto(bu) for bu in billing_users]
        logger.debug(f"Retrieved '{len(users)}' users for audience '{audience}' (plan={plan_id})")
        return users
