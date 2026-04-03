from typing import Optional
from uuid import UUID

from loguru import logger
from redis.asyncio import Redis

from src.core.config import AppConfig
from src.core.enums import TransactionStatus
from src.infrastructure.billing import BillingClient, billing_transaction_to_dto
from src.infrastructure.billing.converters import billing_user_to_dto
from src.infrastructure.billing.models import BillingTransaction
from src.models.dto import TransactionDto, UserDto
from src.infrastructure.redis import RedisRepository

from .base_billing import BaseBillingService


class TransactionService(BaseBillingService):
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

    async def _attach_user(self, billing_tx: BillingTransaction, dto: TransactionDto) -> TransactionDto:
        """Fetch the user from billing API and attach to the transaction DTO."""
        if billing_tx.UserTelegramID:
            billing_user = await self.billing.get_user(billing_tx.UserTelegramID)
            if billing_user:
                dto.user = billing_user_to_dto(billing_user)
        return dto

    async def create(self, user: UserDto, transaction: TransactionDto) -> TransactionDto:
        transaction_data = {
            "payment_id": str(transaction.payment_id),
            "status": transaction.status.value,
            "is_test": transaction.is_test,
            "purchase_type": transaction.purchase_type.value,
            "gateway_type": transaction.gateway_type.value,
            "currency": transaction.currency.value,
            "plan": transaction.plan.model_dump(mode="json"),
            "pricing": transaction.pricing.model_dump(mode="json"),
        }

        billing_tx = await self.billing.create_transaction(user.telegram_id, transaction_data)
        result = billing_transaction_to_dto(billing_tx)
        result.user = user
        logger.info(f"Created transaction '{transaction.payment_id}' for user '{user.telegram_id}'")
        return result

    async def get(self, payment_id: UUID) -> Optional[TransactionDto]:
        billing_tx = await self.billing.get_transaction(payment_id)

        if billing_tx:
            logger.debug(f"Retrieved transaction '{payment_id}'")
            dto = billing_transaction_to_dto(billing_tx)
            await self._attach_user(billing_tx, dto)
            return dto

        logger.warning(f"Transaction '{payment_id}' not found")
        return None

    async def get_by_user(self, telegram_id: int) -> list[TransactionDto]:
        billing_txs = await self.billing.list_transactions(telegram_id)
        logger.debug(f"Retrieved '{len(billing_txs)}' transactions for user '{telegram_id}'")
        return [billing_transaction_to_dto(t) for t in billing_txs]

    async def get_all(self) -> list[TransactionDto]:
        billing_txs = await self.billing.list_all_transactions()
        logger.debug(f"Retrieved '{len(billing_txs)}' total transactions")
        return [billing_transaction_to_dto(t) for t in billing_txs]

    async def get_by_status(self, status: TransactionStatus) -> list[TransactionDto]:
        billing_txs = await self.billing.list_transactions_by_status(status.value)
        logger.debug(f"Retrieved '{len(billing_txs)}' transactions with status '{status}'")
        return [billing_transaction_to_dto(t) for t in billing_txs]

    async def update(self, transaction: TransactionDto) -> Optional[TransactionDto]:
        """Update a transaction by transitioning its status.

        Note: The billing API only supports atomic status transitions, not arbitrary
        field updates. This method uses the transition endpoint, inferring the
        from_status from the changed_data tracker. If the status hasn't changed,
        it re-fetches and returns the current transaction.
        """
        changed = transaction.changed_data
        new_status = changed.get("status")

        if new_status and isinstance(new_status, TransactionStatus):
            # We need the original status. Since TrackableDto only stores the new value,
            # we fetch the current transaction to get its persisted status.
            current = await self.billing.get_transaction(transaction.payment_id)
            if current:
                from_status = current.Status
                result = await self.billing.transition_transaction_status(
                    transaction.payment_id, from_status, new_status.value
                )
                if result:
                    logger.info(f"Updated transaction '{transaction.payment_id}' successfully")
                    dto = billing_transaction_to_dto(result)
                    await self._attach_user(result, dto)
                    return dto

            logger.warning(
                f"Attempted to update transaction '{transaction.payment_id}', "
                "but transaction was not found or update failed"
            )
            return None

        # No status change -- just return the current state
        billing_tx = await self.billing.get_transaction(transaction.payment_id)
        if billing_tx:
            logger.info(f"Updated transaction '{transaction.payment_id}' successfully")
            dto = billing_transaction_to_dto(billing_tx)
            await self._attach_user(billing_tx, dto)
            return dto

        logger.warning(
            f"Attempted to update transaction '{transaction.payment_id}', "
            "but transaction was not found or update failed"
        )
        return None

    async def transition_status(
        self,
        payment_id: UUID,
        from_status: TransactionStatus,
        to_status: TransactionStatus,
    ) -> Optional[TransactionDto]:
        """Atomically transition status. Returns None if the row was not in from_status
        (already processed by another worker)."""
        billing_tx = await self.billing.transition_transaction_status(
            payment_id, from_status.value, to_status.value
        )

        if billing_tx:
            logger.info(
                f"Transaction '{payment_id}' transitioned {from_status} -> {to_status}"
            )
            dto = billing_transaction_to_dto(billing_tx)
            await self._attach_user(billing_tx, dto)
            return dto

        logger.warning(
            f"Transaction '{payment_id}' was NOT in status '{from_status}', "
            f"skipping transition to '{to_status}'"
        )
        return None

    async def count(self) -> int:
        data = await self.billing.count_transactions()
        count = data.get("total", 0)
        logger.debug(f"Total transactions count: '{count}'")
        return count

    async def count_by_status(self, status: TransactionStatus) -> int:
        data = await self.billing.count_transactions()
        by_status = data.get("by_status", {})
        count = by_status.get(status.value, 0)
        logger.debug(f"Transactions count with status '{status}': '{count}'")
        return count
