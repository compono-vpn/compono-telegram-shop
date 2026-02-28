from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from aiogram import Bot
from fluentogram import TranslatorHub
from loguru import logger
from redis.asyncio import Redis

from src.core.config import AppConfig
from src.core.enums import PromocodeAvailability, PromocodeRewardType
from src.core.utils.time import datetime_now
from src.infrastructure.database import UnitOfWork
from src.infrastructure.database.models.dto import PromocodeDto, SubscriptionDto, UserDto
from src.infrastructure.database.models.sql import Promocode, PromocodeActivation
from src.infrastructure.redis import RedisRepository
from src.services.remnawave import RemnawaveService
from src.services.subscription import SubscriptionService

from .base import BaseService


@dataclass
class ActivationResult:
    success: bool
    notification_key: str
    notification_kwargs: dict = None
    reward_type: Optional[PromocodeRewardType] = None

    def __post_init__(self) -> None:
        if self.notification_kwargs is None:
            self.notification_kwargs = {}

    @property
    def has_subscription(self) -> bool:
        return self.reward_type in (PromocodeRewardType.SUBSCRIPTION, PromocodeRewardType.DURATION)


class PromocodeService(BaseService):
    uow: UnitOfWork

    def __init__(
        self,
        config: AppConfig,
        bot: Bot,
        redis_client: Redis,
        redis_repository: RedisRepository,
        translator_hub: TranslatorHub,
        #
        uow: UnitOfWork,
        subscription_service: SubscriptionService,
        remnawave_service: RemnawaveService,
    ) -> None:
        super().__init__(config, bot, redis_client, redis_repository, translator_hub)
        self.uow = uow
        self.subscription_service = subscription_service
        self.remnawave_service = remnawave_service

    async def create(self, promocode: PromocodeDto) -> Optional[PromocodeDto]:
        init_data = promocode.prepare_init_data()
        init_data.pop("id", None)
        init_data.pop("created_at", None)
        init_data.pop("updated_at", None)
        init_data.pop("activations", None)

        if promocode.plan:
            init_data["plan"] = promocode.plan.model_dump(mode="json")

        db_promocode = Promocode(**init_data)

        async with self.uow:
            created = await self.uow.repository.promocodes.create(db_promocode)

        logger.info(f"Created promocode '{promocode.code}'")
        return PromocodeDto.from_model(created)

    async def get(self, promocode_id: int) -> Optional[PromocodeDto]:
        async with self.uow:
            db_promocode = await self.uow.repository.promocodes.get(promocode_id)

        if db_promocode:
            logger.debug(f"Retrieved promocode '{promocode_id}'")
        else:
            logger.warning(f"Promocode '{promocode_id}' not found")

        return PromocodeDto.from_model(db_promocode)

    async def get_by_code(self, promocode_code: str) -> Optional[PromocodeDto]:
        async with self.uow:
            db_promocode = await self.uow.repository.promocodes.get_by_code(promocode_code)

        if db_promocode:
            logger.debug(f"Retrieved promocode by code '{promocode_code}'")
        else:
            logger.warning(f"Promocode with code '{promocode_code}' not found")

        return PromocodeDto.from_model(db_promocode)

    async def get_all(self) -> list[PromocodeDto]:
        async with self.uow:
            db_promocodes = await self.uow.repository.promocodes.get_all()

        logger.debug(f"Retrieved '{len(db_promocodes)}' promocodes")
        return PromocodeDto.from_model_list(db_promocodes)

    async def update(self, promocode: PromocodeDto) -> Optional[PromocodeDto]:
        changed = promocode.changed_data.copy()
        if "plan" in changed and promocode.plan:
            changed["plan"] = promocode.plan.model_dump(mode="json")

        async with self.uow:
            db_updated_promocode = await self.uow.repository.promocodes.update(
                promocode_id=promocode.id,  # type: ignore[arg-type]
                **changed,
            )

        if db_updated_promocode:
            logger.info(f"Updated promocode '{promocode.code}' successfully")
        else:
            logger.warning(
                f"Attempted to update promocode '{promocode.code}' "
                f"(ID: '{promocode.id}'), but promocode was not found or update failed"
            )

        return PromocodeDto.from_model(db_updated_promocode)

    async def delete(self, promocode_id: int) -> bool:
        async with self.uow:
            result = await self.uow.repository.promocodes.delete(promocode_id)

        if result:
            logger.info(f"Promocode '{promocode_id}' deleted successfully")
        else:
            logger.warning(
                f"Failed to delete promocode '{promocode_id}'. "
                f"Promocode not found or deletion failed"
            )

        return result

    async def filter_by_type(self, promocode_type: PromocodeRewardType) -> list[PromocodeDto]:
        async with self.uow:
            db_promocodes = await self.uow.repository.promocodes.filter_by_type(promocode_type)

        logger.debug(
            f"Filtered promocodes by type '{promocode_type}', found '{len(db_promocodes)}'"
        )
        return PromocodeDto.from_model_list(db_promocodes)

    async def filter_active(self, is_active: bool = True) -> list[PromocodeDto]:
        async with self.uow:
            db_promocodes = await self.uow.repository.promocodes.filter_active(is_active)

        logger.debug(f"Filtered active promocodes: '{is_active}', found '{len(db_promocodes)}'")
        return PromocodeDto.from_model_list(db_promocodes)

    async def activate(self, user: UserDto, code: str) -> ActivationResult:
        promocode = await self.get_by_code(code.strip().upper())

        if not promocode:
            return ActivationResult(False, "ntf-promocode-not-found")

        if not promocode.is_active:
            return ActivationResult(False, "ntf-promocode-inactive")

        if promocode.is_expired:
            return ActivationResult(False, "ntf-promocode-expired")

        if promocode.is_depleted:
            return ActivationResult(False, "ntf-promocode-depleted")

        # Check if already activated by this user
        for activation in promocode.activations:
            if activation.user_telegram_id == user.telegram_id:
                return ActivationResult(False, "ntf-promocode-already-activated")

        # Check availability rules
        if not self._check_availability(user, promocode):
            return ActivationResult(False, "ntf-promocode-not-available")

        # Apply reward
        apply_result = await self._apply_reward(user, promocode)
        if not apply_result.success:
            return apply_result

        # Create activation record
        async with self.uow:
            activation = PromocodeActivation(
                promocode_id=promocode.id,
                user_telegram_id=user.telegram_id,
            )
            await self.uow.repository.promocodes.create_activation(activation)

        logger.info(
            f"User '{user.telegram_id}' activated promocode '{promocode.code}' "
            f"(type={promocode.reward_type}, reward={promocode.reward})"
        )

        return ActivationResult(
            True,
            "ntf-promocode-activated",
            {"code": promocode.code},
        )

    def _check_availability(self, user: UserDto, promocode: PromocodeDto) -> bool:
        match promocode.availability:
            case PromocodeAvailability.ALL:
                return True
            case PromocodeAvailability.NEW:
                return not user.has_any_subscription
            case PromocodeAvailability.EXISTING:
                return user.has_any_subscription
            case PromocodeAvailability.INVITED:
                return user.is_invited_user
            case PromocodeAvailability.ALLOWED:
                if not promocode.allowed_telegram_ids:
                    return False
                return user.telegram_id in promocode.allowed_telegram_ids
            case _:
                return False

    async def _apply_reward(self, user: UserDto, promocode: PromocodeDto) -> ActivationResult:
        match promocode.reward_type:
            case PromocodeRewardType.PERSONAL_DISCOUNT:
                user.personal_discount = promocode.reward or 0
                await self._update_user(user)
                return ActivationResult(
                    True, "ntf-promocode-activated", {"code": promocode.code},
                    reward_type=PromocodeRewardType.PERSONAL_DISCOUNT,
                )

            case PromocodeRewardType.PURCHASE_DISCOUNT:
                user.purchase_discount = promocode.reward or 0
                await self._update_user(user)
                return ActivationResult(
                    True, "ntf-promocode-activated", {"code": promocode.code},
                    reward_type=PromocodeRewardType.PURCHASE_DISCOUNT,
                )

            case PromocodeRewardType.DURATION:
                subscription = await self.subscription_service.get_current(user.telegram_id)
                if not subscription:
                    return ActivationResult(False, "ntf-promocode-no-subscription")

                base_date = max(subscription.expire_at, datetime_now())
                new_expire = base_date + timedelta(days=promocode.reward)
                subscription.expire_at = new_expire

                await self.remnawave_service.updated_user(
                    user=user,
                    uuid=subscription.user_remna_id,
                    subscription=subscription,
                )
                await self.subscription_service.update(subscription)
                return ActivationResult(
                    True, "ntf-promocode-activated", {"code": promocode.code},
                    reward_type=PromocodeRewardType.DURATION,
                )

            case PromocodeRewardType.SUBSCRIPTION:
                if not promocode.plan:
                    return ActivationResult(False, "ntf-promocode-type-not-supported")

                subscription = await self.subscription_service.get_current(user.telegram_id)
                if subscription:
                    return ActivationResult(False, "ntf-promocode-already-has-subscription")

                remna_user = await self.remnawave_service.create_user(user=user, plan=promocode.plan)
                new_subscription = SubscriptionDto(
                    user_remna_id=remna_user.uuid,
                    status=remna_user.status,
                    traffic_limit=promocode.plan.traffic_limit,
                    device_limit=promocode.plan.device_limit,
                    traffic_limit_strategy=promocode.plan.traffic_limit_strategy,
                    tag=promocode.plan.tag,
                    internal_squads=promocode.plan.internal_squads,
                    external_squad=promocode.plan.external_squad,
                    expire_at=remna_user.expire_at,
                    url=remna_user.subscription_url,
                    plan=promocode.plan,
                )
                await self.subscription_service.create(user, new_subscription)
                return ActivationResult(
                    True, "ntf-promocode-activated", {"code": promocode.code},
                    reward_type=PromocodeRewardType.SUBSCRIPTION,
                )

            case _:
                return ActivationResult(False, "ntf-promocode-type-not-supported")

    async def _update_user(self, user: UserDto) -> None:
        async with self.uow:
            await self.uow.repository.users.update(
                telegram_id=user.telegram_id,
                **user.prepare_changed_data(),
            )
