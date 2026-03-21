from uuid import UUID

from dishka.integrations.taskiq import FromDishka, inject
from loguru import logger
from remnapy.enums.users import TrafficLimitStrategy
from remnapy.models import CreateUserRequestDto

from src.core.enums import TransactionStatus
from src.core.utils.formatters import format_days_to_datetime
from src.infrastructure.database import UnitOfWork
from src.infrastructure.taskiq.broker import broker
from src.services.email import EmailService
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
    email_service: FromDishka[EmailService],
) -> None:
    async with uow:
        order = await uow.repository.web_orders.get_by_payment_id(payment_id)

    if not order:
        logger.warning(f"Web order not found for payment_id='{payment_id}'")
        return

    if order.status != "pending":
        logger.warning(f"Web order '{payment_id}' already in status '{order.status}', skipping")
        return

    if payment_status == TransactionStatus.COMPLETED:
        short_id = str(payment_id).split("-")[0]
        username = f"web_{short_id}"

        # Determine limits from plan snapshot (full purchase) or hardcoded defaults (trial)
        internal_squads = None
        external_squad = None

        if order.plan_snapshot:
            snapshot = order.plan_snapshot
            traffic_limit_gb = snapshot.get("traffic_limit", 5)
            traffic_limit_bytes = (
                traffic_limit_gb * 1024 * 1024 * 1024 if traffic_limit_gb > 0 else 0
            )
            device_limit = snapshot.get("device_limit", 1)
            strategy_value = snapshot.get("traffic_limit_strategy", "NO_RESET")
            try:
                traffic_strategy = TrafficLimitStrategy(strategy_value)
            except ValueError:
                traffic_strategy = TrafficLimitStrategy.NO_RESET
            description = f"Web purchase: {order.email} — {snapshot.get('name', 'N/A')}"

            raw_squads = snapshot.get("internal_squads", [])
            if raw_squads:
                internal_squads = [UUID(s) for s in raw_squads]
            raw_ext = snapshot.get("external_squad")
            if raw_ext:
                external_squad = UUID(raw_ext)
        else:
            traffic_limit_bytes = 5 * 1024 * 1024 * 1024  # 5 GB
            device_limit = 1
            traffic_strategy = TrafficLimitStrategy.NO_RESET
            description = f"Web trial: {order.email}"

        create_kwargs = dict(
            username=username,
            expire_at=format_days_to_datetime(order.plan_duration_days),
            traffic_limit_bytes=traffic_limit_bytes,
            traffic_limit_strategy=traffic_strategy,
            description=description,
            hwid_device_limit=device_limit,
        )
        if internal_squads:
            create_kwargs["active_internal_squads"] = internal_squads
        if external_squad:
            create_kwargs["external_squad_uuid"] = external_squad

        created = await remnawave_service.remnawave.users.create_user(
            CreateUserRequestDto(**create_kwargs)
        )
        subscription_url = remnawave_service._rewrite_sub_url(created.subscription_url)

        # Atomic transition: only update if still "pending" — prevents duplicate
        # subscription creation when webhook is delivered more than once
        async with uow:
            updated = await uow.repository.web_orders.transition_status(
                payment_id,
                from_status="pending",
                to_status="completed",
                subscription_url=subscription_url,
            )

        if not updated:
            logger.warning(f"Web order '{payment_id}' was already processed by another worker")
            return

        bot_link = f"https://t.me/compono_bot?start=web_{short_id}"

        if order.plan_snapshot:
            # Full purchase — send subscription + bot link for account linking
            await email_service.send_purchase_subscription(
                order.email, subscription_url,
                order.plan_snapshot.get("name", "Compono VPN"), bot_link,
            )
            logger.info(
                f"Web purchase activated for '{order.email}', "
                f"plan='{order.plan_snapshot.get('name')}', sub_url='{subscription_url}'"
            )
        else:
            # Trial — send bot link
            await email_service.send_trial_bot_link(order.email, bot_link)
            logger.info(f"Web trial activated for '{order.email}', sub_url='{subscription_url}'")

    elif payment_status == TransactionStatus.CANCELED:
        async with uow:
            await uow.repository.web_orders.transition_status(
                payment_id, from_status="pending", to_status="canceled"
            )
        logger.info(f"Web order '{payment_id}' canceled")
