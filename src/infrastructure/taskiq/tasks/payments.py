from uuid import UUID

from dishka.integrations.taskiq import FromDishka, inject
from loguru import logger
from remnapy.enums.users import TrafficLimitStrategy
from remnapy.models import CreateUserRequestDto

from src.core.enums import TransactionStatus
from src.core.utils.formatters import format_days_to_datetime
from src.infrastructure.database import UnitOfWork
from src.infrastructure.taskiq.broker import broker
from src.services.payment_gateway import PaymentGatewayService
from src.services.remnawave import RemnawaveService
from src.services.transaction import TransactionService


@broker.task()
@inject
async def handle_payment_transaction_task(
    payment_id: UUID,
    payment_status: TransactionStatus,
    payment_gateway_service: FromDishka[PaymentGatewayService],
    transaction_service: FromDishka[TransactionService],
) -> None:
    # First check if this is a regular bot transaction
    transaction = await transaction_service.get(payment_id)

    if transaction:
        match payment_status:
            case TransactionStatus.COMPLETED:
                await payment_gateway_service.handle_payment_succeeded(payment_id)
            case TransactionStatus.CANCELED:
                await payment_gateway_service.handle_payment_canceled(payment_id)
        return

    # Fall back to web order processing
    logger.info(f"No transaction found for '{payment_id}', trying web order")
    await handle_web_order_task.kiq(payment_id, payment_status)


@broker.task(schedule=[{"cron": "*/30 * * * *"}])
@inject
async def cancel_transaction_task(transaction_service: FromDishka[TransactionService]) -> None:
    transactions = await transaction_service.get_by_status(TransactionStatus.PENDING)

    if not transactions:
        logger.debug("No pending transactions found")
        return

    old_transactions = [tx for tx in transactions if tx.has_old]
    logger.debug(f"Found '{len(old_transactions)}' old transactions to cancel")

    for transaction in old_transactions:
        transaction.status = TransactionStatus.CANCELED
        await transaction_service.update(transaction)
        logger.debug(f"Transaction '{transaction.id}' canceled")


@broker.task()
@inject
async def handle_web_order_task(
    payment_id: UUID,
    payment_status: TransactionStatus,
    uow: FromDishka[UnitOfWork],
    remnawave_service: FromDishka[RemnawaveService],
) -> None:
    async with uow:
        order = await uow.repository.web_orders.get_by_payment_id(payment_id)

    if not order:
        logger.warning(f"Web order not found for payment_id='{payment_id}'")
        return

    if order.status == "completed":
        logger.warning(f"Web order '{payment_id}' already completed")
        return

    if payment_status == TransactionStatus.COMPLETED:
        short_id = str(payment_id).split("-")[0]
        username = f"web_{short_id}"

        created = await remnawave_service.remnawave.users.create_user(
            CreateUserRequestDto(
                username=username,
                expire_at=format_days_to_datetime(order.plan_duration_days),
                traffic_limit_bytes=0,
                traffic_limit_strategy=TrafficLimitStrategy.NO_RESET,
                description=f"Web trial: {order.email}",
                hwid_device_limit=1,
            )
        )
        subscription_url = remnawave_service._rewrite_sub_url(created.subscription_url)

        async with uow:
            await uow.repository.web_orders.update_by_payment_id(
                payment_id,
                status="completed",
                subscription_url=subscription_url,
            )

        logger.info(f"Web trial activated for '{order.email}', sub_url='{subscription_url}'")

    elif payment_status == TransactionStatus.CANCELED:
        async with uow:
            await uow.repository.web_orders.update_by_payment_id(
                payment_id, status="canceled"
            )
        logger.info(f"Web order '{payment_id}' canceled")
