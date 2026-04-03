import uuid
from typing import Optional
from uuid import UUID

from aiogram import Bot
from fluentogram import TranslatorHub
from loguru import logger
from redis.asyncio import Redis

from src.bot.keyboards import get_user_keyboard
from src.core.config import AppConfig
from src.core.enums import (
    Currency,
    GatewayChannel,
    PaymentGatewayType,
    PurchaseType,
    SystemNotificationType,
    TransactionStatus,
)
from src.core.utils.formatters import (
    i18n_format_days,
    i18n_format_device_limit,
    i18n_format_traffic_limit,
)
from src.core.utils.message_payload import MessagePayload
from src.infrastructure.billing import BillingClient, billing_gateway_to_dto
from src.infrastructure.billing.client import BillingClientError
from src.infrastructure.database.models.dto import (
    PaymentGatewayDto,
    PaymentResult,
    PlanSnapshotDto,
    PriceDetailsDto,
    TransactionDto,
    UserDto,
)
from src.infrastructure.payment_gateways import BasePaymentGateway, PaymentGatewayFactory
from src.infrastructure.redis import RedisRepository
from src.infrastructure.taskiq.tasks.subscriptions import purchase_subscription_task
from src.services.notification import NotificationService
from src.services.referral import ReferralService
from src.services.subscription import SubscriptionService

from .base import BaseService
from .transaction import TransactionService
from .user import UserService


class PaymentGatewayService(BaseService):
    billing: BillingClient
    transaction_service: TransactionService
    subscription_service: SubscriptionService
    payment_gateway_factory: PaymentGatewayFactory
    referral_service: ReferralService
    user_service: UserService

    def __init__(
        self,
        config: AppConfig,
        bot: Bot,
        redis_client: Redis,
        redis_repository: RedisRepository,
        translator_hub: TranslatorHub,
        #
        billing: BillingClient,
        transaction_service: TransactionService,
        subscription_service: SubscriptionService,
        payment_gateway_factory: PaymentGatewayFactory,
        referral_service: ReferralService,
        notification_service: NotificationService,
        user_service: UserService,
    ) -> None:
        super().__init__(config, bot, redis_client, redis_repository, translator_hub)
        self.billing = billing
        self.transaction_service = transaction_service
        self.subscription_service = subscription_service
        self.payment_gateway_factory = payment_gateway_factory
        self.referral_service = referral_service
        self.notification_service = notification_service
        self.user_service = user_service

    async def create_default(self) -> None:
        existing_gateways = await self.billing.list_gateways()
        existing_types = {g.Type for g in existing_gateways}

        for gateway_type in PaymentGatewayType:
            if gateway_type.value in existing_types:
                continue

            match gateway_type:
                case PaymentGatewayType.TELEGRAM_STARS:
                    is_active = True
                case PaymentGatewayType.YOOKASSA:
                    is_active = False
                case PaymentGatewayType.YOOMONEY:
                    is_active = False
                case PaymentGatewayType.CRYPTOMUS:
                    is_active = False
                case PaymentGatewayType.HELEKET:
                    is_active = False
                case PaymentGatewayType.PLATEGA:
                    is_active = False
                case _:
                    logger.warning(f"Unhandled payment gateway type '{gateway_type}' - skipping")
                    continue

            gateway_data = {
                "order_index": len(existing_gateways) + 1,
                "type": gateway_type.value,
                "channel": GatewayChannel.ALL.value,
                "currency": Currency.from_gateway_type(gateway_type).value,
                "is_active": is_active,
            }

            await self.billing.create_gateway(gateway_data)
            existing_gateways = await self.billing.list_gateways()
            logger.info(f"Payment gateway '{gateway_type}' created")

    async def get(self, gateway_id: int) -> Optional[PaymentGatewayDto]:
        billing_gw = await self.billing.get_gateway(gateway_id)

        if not billing_gw:
            logger.warning(f"Payment gateway '{gateway_id}' not found")
            return None

        logger.debug(f"Retrieved payment gateway '{gateway_id}'")
        return billing_gateway_to_dto(billing_gw)

    async def get_by_type(
        self,
        gateway_type: PaymentGatewayType,
        channel: Optional[GatewayChannel] = None,
    ) -> Optional[PaymentGatewayDto]:
        billing_gw = await self.billing.get_gateway_by_type(gateway_type.value)

        if not billing_gw:
            logger.warning(f"Payment gateway of type '{gateway_type}' not found")
            return None

        # Filter by channel if specified
        if channel and billing_gw.Channel != GatewayChannel.ALL.value and billing_gw.Channel != channel.value:
            logger.warning(f"Payment gateway of type '{gateway_type}' not found for channel '{channel}'")
            return None

        logger.debug(f"Retrieved payment gateway of type '{gateway_type}'")
        return billing_gateway_to_dto(billing_gw)

    async def get_all(self, sorted: bool = False) -> list[PaymentGatewayDto]:
        billing_gateways = await self.billing.list_gateways()

        if sorted:
            billing_gateways.sort(key=lambda g: g.OrderIndex)

        logger.debug(f"Retrieved '{len(billing_gateways)}' payment gateways")
        return [billing_gateway_to_dto(g) for g in billing_gateways]

    async def update(self, gateway: PaymentGatewayDto) -> Optional[PaymentGatewayDto]:
        updated_data = gateway.changed_data

        if gateway.settings and gateway.settings.changed_data:
            updated_data["settings"] = gateway.settings.prepare_init_data(encrypt=True)

        gateway_data = {
            "id": gateway.id,
            **updated_data,
        }
        # Serialize enum values for the API
        for key, value in list(gateway_data.items()):
            if hasattr(value, "value"):
                gateway_data[key] = value.value

        try:
            billing_gw = await self.billing.update_gateway(gateway_data)
        except BillingClientError as e:
            logger.warning(
                f"Attempted to update gateway '{gateway.type}' (ID: '{gateway.id}'), "
                f"but update failed: {e}"
            )
            return None

        logger.info(f"Payment gateway '{gateway.type}' updated successfully")
        return billing_gateway_to_dto(billing_gw)

    async def filter_active(
        self,
        is_active: bool = True,
        channel: Optional[GatewayChannel] = None,
    ) -> list[PaymentGatewayDto]:
        if is_active:
            billing_gateways = await self.billing.list_active_gateways()
        else:
            billing_gateways = await self.billing.list_gateways()
            billing_gateways = [g for g in billing_gateways if not g.IsActive]

        if channel:
            billing_gateways = [
                g for g in billing_gateways
                if g.Channel == GatewayChannel.ALL.value or g.Channel == channel.value
            ]

        logger.debug(f"Filtered active gateways: '{is_active}', found '{len(billing_gateways)}'")
        return [billing_gateway_to_dto(g) for g in billing_gateways]

    async def move_gateway_up(self, gateway_id: int) -> bool:
        try:
            await self.billing.move_gateway_up(gateway_id)
        except BillingClientError as e:
            logger.warning(
                f"Payment gateway with ID '{gateway_id}' not found for move operation: {e}"
            )
            return False

        logger.info(f"Payment gateway '{gateway_id}' reorder successfully")
        return True

    #

    async def create_payment(
        self,
        user: UserDto,
        plan: PlanSnapshotDto,
        pricing: PriceDetailsDto,
        purchase_type: PurchaseType,
        gateway_type: PaymentGatewayType,
    ) -> PaymentResult:
        gateway_instance = await self._get_gateway_instance(gateway_type, channel=GatewayChannel.BOT)

        i18n = self.translator_hub.get_translator_by_locale(locale=user.language)
        key, kw = i18n_format_days(plan.duration)
        details = i18n.get(
            "payment-invoice-description",
            purchase_type=purchase_type,
            name=plan.name,
            duration=i18n.get(key, **kw),
        )

        transaction_data = {
            "status": TransactionStatus.PENDING,
            "purchase_type": purchase_type,
            "gateway_type": gateway_instance.data.type,
            "pricing": pricing,
            "currency": gateway_instance.data.currency,
            "plan": plan,
        }

        if pricing.is_free:
            payment_id = uuid.uuid4()

            transaction = TransactionDto(payment_id=payment_id, **transaction_data)
            await self.transaction_service.create(user, transaction)

            logger.info(f"Payment for user '{user.telegram_id}' not created. Pricing is free")
            return PaymentResult(id=payment_id, url=None)

        payment: PaymentResult = await gateway_instance.handle_create_payment(
            amount=pricing.final_amount,
            details=details,
        )
        transaction = TransactionDto(payment_id=payment.id, **transaction_data)
        await self.transaction_service.create(user, transaction)

        logger.info(f"Created transaction '{payment.id}' for user '{user.telegram_id}'")
        logger.info(f"Payment link: '{payment.url}' for user '{user.telegram_id}'")
        return payment

    async def create_test_payment(
        self,
        user: UserDto,
        gateway_type: PaymentGatewayType,
    ) -> PaymentResult:
        gateway_instance = await self._get_gateway_instance(gateway_type)
        i18n = self.translator_hub.get_translator_by_locale(locale=user.language)
        test_details = i18n.get("test-payment")

        test_pricing = PriceDetailsDto(original_amount=2)
        test_plan = PlanSnapshotDto.test()

        test_payment: PaymentResult = await gateway_instance.handle_create_payment(
            amount=test_pricing.final_amount,
            details=test_details,
        )
        test_transaction = TransactionDto(
            payment_id=test_payment.id,
            status=TransactionStatus.PENDING,
            purchase_type=PurchaseType.NEW,
            gateway_type=gateway_instance.data.type,
            is_test=True,
            pricing=test_pricing,
            currency=gateway_instance.data.currency,
            plan=test_plan,
        )
        await self.transaction_service.create(user, test_transaction)

        logger.info(f"Created test transaction '{test_payment.id}' for user '{user.telegram_id}'")
        logger.info(
            f"Created test payment '{test_payment.id}' for gateway '{gateway_type}', "
            f"link: '{test_payment.url}'"
        )
        return test_payment

    async def handle_payment_succeeded(self, payment_id: UUID) -> None:
        # Atomically transition PENDING -> COMPLETED.
        # If another worker already transitioned this, result is None => we stop.
        updated = await self.transaction_service.transition_status(
            payment_id, TransactionStatus.PENDING, TransactionStatus.COMPLETED
        )

        if not updated:
            logger.warning(f"Transaction '{payment_id}' already processed or not found, skipping")
            return

        # Re-fetch with user relation
        transaction = await self.transaction_service.get(payment_id)

        if not transaction or not transaction.user:
            logger.critical(f"Transaction or user not found for '{payment_id}' after status update")
            return

        logger.info(f"Payment succeeded '{payment_id}' for user '{transaction.user.telegram_id}'")

        if transaction.is_test:
            await self.notification_service.notify_user(
                user=transaction.user,
                payload=MessagePayload(
                    i18n_key="ntf-gateway-test-payment-confirmed",
                ),
            )
            return

        # Clear one-time purchase discount after successful payment
        if transaction.user.purchase_discount and transaction.user.purchase_discount > 0:
            user = await self.user_service.get(transaction.user.telegram_id)
            if user:
                user.purchase_discount = 0
                user.purchase_discount_max_days = 0
                await self.user_service.update(user)
                logger.info(
                    f"Cleared purchase_discount for user '{transaction.user.telegram_id}' "
                    f"after successful payment"
                )

        i18n_keys = {
            PurchaseType.NEW: "ntf-event-subscription-new",
            PurchaseType.RENEW: "ntf-event-subscription-renew",
            PurchaseType.CHANGE: "ntf-event-subscription-change",
        }
        i18n_key = i18n_keys[transaction.purchase_type]

        subscription = await self.subscription_service.get_current(transaction.user.telegram_id)
        extra_i18n_kwargs = {}

        if transaction.purchase_type == PurchaseType.CHANGE:
            plan = subscription.plan if subscription else None

            extra_i18n_kwargs = {
                "previous_plan_name": plan.name if plan else "N/A",
                "previous_plan_type": {
                    "key": "plan-type",
                    "plan_type": plan.type if plan else "N/A",
                },
                "previous_plan_traffic_limit": (
                    i18n_format_traffic_limit(plan.traffic_limit) if plan else "N/A"
                ),
                "previous_plan_device_limit": (
                    i18n_format_device_limit(plan.device_limit) if plan else "N/A"
                ),
                "previous_plan_duration": (i18n_format_days(plan.duration) if plan else "N/A"),
            }

        i18n_kwargs = {
            "payment_id": str(transaction.payment_id),
            "gateway_type": transaction.gateway_type,
            "final_amount": transaction.pricing.final_amount,
            "discount_percent": transaction.pricing.discount_percent,
            "original_amount": transaction.pricing.original_amount,
            "currency": transaction.currency.symbol,
            "user_id": str(transaction.user.telegram_id),
            "user_name": transaction.user.name,
            "username": transaction.user.username or False,
            "plan_name": transaction.plan.name,
            "plan_type": transaction.plan.type,
            "plan_traffic_limit": i18n_format_traffic_limit(transaction.plan.traffic_limit),
            "plan_device_limit": i18n_format_device_limit(transaction.plan.device_limit),
            "plan_duration": i18n_format_days(transaction.plan.duration),
        }

        await self.notification_service.system_notify(
            ntf_type=SystemNotificationType.SUBSCRIPTION,
            payload=MessagePayload.not_deleted(
                i18n_key=i18n_key,
                i18n_kwargs={**i18n_kwargs, **extra_i18n_kwargs},
                reply_markup=get_user_keyboard(transaction.user.telegram_id),
            ),
        )

        await purchase_subscription_task.kiq(transaction, subscription)

        if not transaction.pricing.is_free:
            await self.referral_service.assign_referral_rewards(transaction=transaction)

        logger.debug(f"Called tasks payment for user '{transaction.user.telegram_id}'")

    async def handle_payment_canceled(self, payment_id: UUID) -> None:
        updated = await self.transaction_service.transition_status(
            payment_id, TransactionStatus.PENDING, TransactionStatus.CANCELED
        )

        if not updated:
            logger.warning(f"Transaction '{payment_id}' already processed or not found, skipping cancel")
            return

        logger.info(f"Payment canceled '{payment_id}'")

    #

    async def list_active_by_type(
        self, gateway_type: PaymentGatewayType
    ) -> list[PaymentGatewayDto]:
        billing_gateways = await self.billing.list_active_gateways()
        filtered = [g for g in billing_gateways if g.Type == gateway_type.value]
        return [billing_gateway_to_dto(g) for g in filtered]

    async def _get_gateway_instance(
        self,
        gateway_type: PaymentGatewayType,
        channel: Optional[GatewayChannel] = None,
    ) -> BasePaymentGateway:
        logger.debug(f"Creating gateway instance for type '{gateway_type}' channel='{channel}'")
        gateway = await self.get_by_type(gateway_type, channel)

        if not gateway:
            raise ValueError(f"Payment gateway of type '{gateway_type}' not found")

        return self.payment_gateway_factory(gateway)
