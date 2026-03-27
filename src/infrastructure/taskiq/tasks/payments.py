from uuid import UUID

from dishka.integrations.taskiq import FromDishka, inject
from loguru import logger
from remnapy.enums.users import TrafficLimitStrategy
from remnapy.exceptions import NotFoundError
from remnapy.models import CreateUserRequestDto, UpdateUserRequestDto

from src.core.enums import SystemNotificationType, TransactionStatus
from src.core.utils.formatters import format_days_to_datetime
from src.core.utils.message_payload import MessagePayload
from src.core.utils.time import datetime_now

from datetime import timedelta
from src.infrastructure.database import UnitOfWork
from src.infrastructure.database.models.sql.customer import Customer
from src.infrastructure.taskiq.broker import broker
from src.services.email import EmailService
from src.services.notification import NotificationService
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
    notification_service: FromDishka[NotificationService],
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

        # Find-or-create Customer by email
        async with uow:
            customer, _ = await uow.repository.customers.get_or_create_by_email(order.email)

        if customer.remna_user_uuid:
            # Customer already has a Remnawave user — extend it
            try:
                existing = await remnawave_service.remnawave.users.get_user_by_uuid(
                    customer.remna_user_uuid
                )
                # Extend expiry: stack new days on top of current expiry or now, whichever is later
                base = max(existing.expire_at, datetime_now())
                new_expire = base + timedelta(days=order.plan_duration_days)

                updated_remna = await remnawave_service.remnawave.users.update_user(
                    UpdateUserRequestDto(
                        uuid=customer.remna_user_uuid,
                        expire_at=new_expire,
                        traffic_limit_bytes=max(
                            existing.traffic_limit_bytes, traffic_limit_bytes
                        ),
                        traffic_limit_strategy=traffic_strategy,
                        description=description,
                        hwid_device_limit=max(
                            existing.hwid_device_limit or 0, device_limit
                        ),
                        **(
                            {"active_internal_squads": internal_squads}
                            if internal_squads
                            else {}
                        ),
                        **(
                            {"external_squad_uuid": external_squad}
                            if external_squad
                            else {}
                        ),
                    )
                )
                subscription_url = remnawave_service._rewrite_sub_url(
                    updated_remna.subscription_url
                )
                logger.info(
                    f"Extended existing Remnawave user for customer '{customer.id}' "
                    f"(email='{order.email}')"
                )
            except NotFoundError:
                # Remnawave user was deleted — recreate
                logger.warning(
                    f"Remnawave user '{customer.remna_user_uuid}' not found, recreating"
                )
                customer_username = customer.remna_username or f"compono_{customer.id}"
                create_kwargs = dict(
                    username=customer_username,
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
                subscription_url = remnawave_service._rewrite_sub_url(
                    created.subscription_url
                )

                async with uow:
                    await uow.repository.customers.update(
                        customer.id,
                        remna_user_uuid=created.uuid,
                        remna_username=created.username,
                        subscription_url=subscription_url,
                    )
        else:
            # First purchase for this customer — create Remnawave user
            customer_username = f"compono_{customer.id}"
            create_kwargs = dict(
                username=customer_username,
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
            subscription_url = remnawave_service._rewrite_sub_url(
                created.subscription_url
            )

            async with uow:
                await uow.repository.customers.update(
                    customer.id,
                    remna_user_uuid=created.uuid,
                    remna_username=created.username,
                    subscription_url=subscription_url,
                )

        # Update customer's subscription_url (always keep it fresh)
        async with uow:
            await uow.repository.customers.update(
                customer.id, subscription_url=subscription_url
            )

        # Atomic transition: only update if still "pending" — prevents duplicate
        # subscription creation when webhook is delivered more than once
        async with uow:
            updated = await uow.repository.web_orders.transition_status(
                payment_id,
                from_status="pending",
                to_status="completed",
                subscription_url=subscription_url,
                customer_id=customer.id,
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
            await notification_service.system_notify(
                ntf_type=SystemNotificationType.WEB_PURCHASE,
                payload=MessagePayload.not_deleted(
                    i18n_key="ntf-event-web-purchase",
                    i18n_kwargs={
                        "email": order.email,
                        "amount": float(order.amount),
                        "currency": order.currency or "RUB",
                        "plan_name": order.plan_snapshot.get("name", "N/A"),
                        "plan_duration": order.plan_duration_days,
                        "bot_link": bot_link,
                    },
                ),
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
