"""Tests for RemnawaveService — verifies Remnawave SDK calls, relay sync, URL rewriting,
user/device/node event handling, and sync logic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from remnapy.enums import TrafficLimitStrategy
from remnapy.exceptions import ApiErrorResponse, ConflictError, NotFoundError
from remnapy.models import (
    CreateUserResponseDto,
    DeleteUserResponseDto,
    GetStatsResponseDto,
    UserResponseDto,
)
from remnapy.models.hwid import (
    DeleteUserHwidDeviceResponseDto,
    GetUserHwidDevicesResponseDto,
    HwidDeviceDto,
)
from remnapy.models.webhook import (
    InternalSquadDto,
    NodeDto,
    UserDto as UserWebhookDto,
    UserTrafficDto,
)

from src.core.constants import IMPORTED_TAG
from src.core.enums import (
    PlanType,
    RemnaNodeEvent,
    RemnaUserEvent,
    RemnaUserHwidDevicesEvent,
    SubscriptionStatus,
    SystemNotificationType,
    UserNotificationType,
)
from src.models.dto import PlanSnapshotDto, SubscriptionDto
from src.services.remnawave import RemnawaveService

from tests.conftest import make_plan_snapshot, make_subscription, make_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(tz=timezone.utc)

_ERROR_RESPONSE = ApiErrorResponse(message="test error", code="TEST")


def _conflict_error() -> ConflictError:
    return ConflictError(status_code=409, error=_ERROR_RESPONSE)


def _not_found_error() -> NotFoundError:
    return NotFoundError(status_code=404, error=_ERROR_RESPONSE)


def _make_service(
    sub_public_domain: str = "",
    relay_sync_url: str = "",
) -> RemnawaveService:
    config = MagicMock()
    config.remnawave.sub_public_domain = sub_public_domain
    config.relay_sync_url = relay_sync_url

    bot = MagicMock()
    redis_client = AsyncMock()
    redis_repository = MagicMock()
    translator_hub = MagicMock()

    remnawave = AsyncMock()
    user_service = AsyncMock()
    subscription_service = AsyncMock()
    notification_service = AsyncMock()

    svc = RemnawaveService(
        config=config,
        bot=bot,
        redis_client=redis_client,
        redis_repository=redis_repository,
        translator_hub=translator_hub,
        remnawave=remnawave,
        user_service=user_service,
        subscription_service=subscription_service,
        notification_service=notification_service,
    )
    return svc


def _make_remna_user_response(
    uuid: UUID | None = None,
    username: str = "rs_100",
    subscription_url: str = "https://panel.internal.com/sub/token123",
) -> UserResponseDto:
    uid = uuid or uuid4()
    return UserResponseDto(
        uuid=uid,
        shortUuid="abc",
        username=username,
        status="ACTIVE",
        trafficLimitBytes=300 * 1024**3,
        trafficLimitStrategy=TrafficLimitStrategy.MONTH,
        expireAt=_NOW + timedelta(days=30),
        telegramId=100,
        description="test",
        tag=None,
        hwidDeviceLimit=6,
        trojanPassword="tp",
        vlessUuid=uuid4(),
        ssPassword="sp",
        lastTriggeredThreshold=0,
        createdAt=_NOW,
        updatedAt=_NOW,
        subscriptionUrl=subscription_url,
        activeInternalSquads=[],
        userTraffic={
            "usedTrafficBytes": 0,
            "lifetimeUsedTrafficBytes": 0,
        },
    )


def _make_create_response(
    uuid: UUID | None = None,
    username: str = "rs_100",
    subscription_url: str = "https://panel.internal.com/sub/token123",
) -> CreateUserResponseDto:
    uid = uuid or uuid4()
    return CreateUserResponseDto(
        uuid=uid,
        shortUuid="abc",
        username=username,
        status="ACTIVE",
        trafficLimitBytes=300 * 1024**3,
        trafficLimitStrategy=TrafficLimitStrategy.MONTH,
        expireAt=_NOW + timedelta(days=30),
        telegramId=100,
        description="test",
        tag=None,
        hwidDeviceLimit=6,
        trojanPassword="tp",
        vlessUuid=uuid4(),
        ssPassword="sp",
        lastTriggeredThreshold=0,
        createdAt=_NOW,
        updatedAt=_NOW,
        subscriptionUrl=subscription_url,
        activeInternalSquads=[],
        userTraffic={
            "usedTrafficBytes": 0,
            "lifetimeUsedTrafficBytes": 0,
        },
    )


def _make_webhook_user(
    uuid: UUID | None = None,
    telegram_id: int | None = 100,
    tag: str | None = None,
    status: str = "ACTIVE",
    expire_at: datetime | None = None,
    subscription_url: str | None = "https://panel.internal.com/sub/token123",
    traffic_limit_bytes: int = 300 * 1024**3,
    hwid_device_limit: int | None = 6,
) -> UserWebhookDto:
    uid = uuid or uuid4()
    return UserWebhookDto(
        uuid=uid,
        short_uuid="abc",
        username="rs_100",
        status=status,
        traffic_limit_bytes=traffic_limit_bytes,
        traffic_limit_strategy=TrafficLimitStrategy.MONTH,
        expire_at=expire_at or (_NOW + timedelta(days=30)),
        telegram_id=telegram_id,
        description="test",
        tag=tag,
        hwid_device_limit=hwid_device_limit,
        external_squad_uuid=None,
        trojan_password="tp",
        vless_uuid=uuid4(),
        ss_password="sp",
        last_triggered_threshold=0,
        created_at=_NOW,
        updated_at=_NOW,
        subscription_url=subscription_url,
        active_internal_squads=[],
        user_traffic=UserTrafficDto(
            used_traffic_bytes=1024,
            lifetime_used_traffic_bytes=2048,
        ),
    )


# ---------------------------------------------------------------------------
# _rewrite_sub_url
# ---------------------------------------------------------------------------

class TestRewriteSubUrl:
    def test_rewrites_netloc_when_domain_configured(self):
        svc = _make_service(sub_public_domain="componovpn.com")
        result = svc._rewrite_sub_url("https://panel.internal.com/sub/token123")
        assert result == "https://componovpn.com/sub/token123"

    def test_noop_when_no_domain_configured(self):
        svc = _make_service(sub_public_domain="")
        result = svc._rewrite_sub_url("https://panel.internal.com/sub/token123")
        assert result == "https://panel.internal.com/sub/token123"

    def test_preserves_path_and_query(self):
        svc = _make_service(sub_public_domain="pub.com")
        result = svc._rewrite_sub_url("https://old.com/sub/abc?key=val")
        assert result == "https://pub.com/sub/abc?key=val"


# ---------------------------------------------------------------------------
# _trigger_relay_sync
# ---------------------------------------------------------------------------

class TestTriggerRelaySync:
    async def test_skips_when_no_url(self):
        svc = _make_service(relay_sync_url="")
        # Should not raise
        await svc._trigger_relay_sync()

    async def test_calls_post_when_url_configured(self):
        svc = _make_service(relay_sync_url="http://relay-sync:8080")
        with patch("src.services.remnawave.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await svc._trigger_relay_sync()

            mock_client.post.assert_awaited_once_with("http://relay-sync:8080/trigger")

    async def test_does_not_raise_on_failure(self):
        svc = _make_service(relay_sync_url="http://relay-sync:8080")
        with patch("src.services.remnawave.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                side_effect=Exception("connection refused")
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            # Should not raise
            await svc._trigger_relay_sync()


# ---------------------------------------------------------------------------
# try_connection
# ---------------------------------------------------------------------------

class TestTryConnection:
    async def test_succeeds_with_valid_stats_response(self):
        svc = _make_service()
        svc.remnawave.system.get_stats.return_value = MagicMock(spec=GetStatsResponseDto)
        await svc.try_connection()
        svc.remnawave.system.get_stats.assert_awaited_once()

    async def test_raises_on_invalid_response(self):
        svc = _make_service()
        svc.remnawave.system.get_stats.return_value = "bad response"
        with pytest.raises(ValueError, match="Invalid response"):
            await svc.try_connection()


# ---------------------------------------------------------------------------
# create_user
# ---------------------------------------------------------------------------

class TestCreateUser:
    async def test_creates_from_plan(self):
        svc = _make_service()
        created = _make_create_response()
        svc.remnawave.users.create_user.return_value = created

        user = make_user(telegram_id=100)
        plan = make_plan_snapshot()

        result = await svc.create_user(user, plan=plan)

        svc.remnawave.users.create_user.assert_awaited_once()
        assert result.username == created.username

    async def test_creates_from_subscription(self):
        svc = _make_service()
        created = _make_create_response()
        svc.remnawave.users.create_user.return_value = created

        user = make_user(telegram_id=100)
        plan = make_plan_snapshot()
        sub = SubscriptionDto(
            user_remna_id=uuid4(),
            status=SubscriptionStatus.ACTIVE,
            traffic_limit=300,
            device_limit=6,
            traffic_limit_strategy=TrafficLimitStrategy.MONTH,
            tag=None,
            internal_squads=[],
            external_squad=None,
            expire_at=_NOW + timedelta(days=30),
            url="https://panel.internal.com/sub/token123",
            plan=plan,
        )

        result = await svc.create_user(user, subscription=sub)

        svc.remnawave.users.create_user.assert_awaited_once()
        assert result.username == created.username

    async def test_raises_when_no_plan_or_subscription(self):
        svc = _make_service()
        user = make_user(telegram_id=100)

        with pytest.raises(ValueError, match="Either 'plan' or 'subscription'"):
            await svc.create_user(user)

    async def test_conflict_error_without_force_raises(self):
        svc = _make_service()
        svc.remnawave.users.create_user.side_effect = _conflict_error()

        user = make_user(telegram_id=100)
        plan = make_plan_snapshot()

        with pytest.raises(ConflictError):
            await svc.create_user(user, plan=plan, force=False)

    async def test_conflict_error_with_force_recreates(self):
        svc = _make_service()
        created = _make_create_response()
        old_user = _make_remna_user_response()

        # First call: conflict, second call: success
        svc.remnawave.users.create_user.side_effect = [_conflict_error(), created]
        svc.remnawave.users.get_user_by_username.return_value = old_user
        svc.remnawave.users.delete_user.return_value = DeleteUserResponseDto(isDeleted=True)

        user = make_user(telegram_id=100)
        plan = make_plan_snapshot()

        result = await svc.create_user(user, plan=plan, force=True)

        svc.remnawave.users.get_user_by_username.assert_awaited_once_with(user.remna_name)
        svc.remnawave.users.delete_user.assert_awaited_once_with(old_user.uuid)
        assert result.username == created.username

    async def test_rewrites_subscription_url(self):
        svc = _make_service(sub_public_domain="componovpn.com")
        created = _make_create_response(subscription_url="https://panel.internal.com/sub/abc")
        svc.remnawave.users.create_user.return_value = created

        user = make_user(telegram_id=100)
        plan = make_plan_snapshot()

        result = await svc.create_user(user, plan=plan)

        assert "componovpn.com" in result.subscription_url
        assert "panel.internal.com" not in result.subscription_url

    async def test_triggers_relay_sync(self):
        svc = _make_service(relay_sync_url="http://relay:8080")
        created = _make_create_response()
        svc.remnawave.users.create_user.return_value = created

        user = make_user(telegram_id=100)
        plan = make_plan_snapshot()

        with patch.object(svc, "_trigger_relay_sync", new_callable=AsyncMock) as mock_sync:
            await svc.create_user(user, plan=plan)
            mock_sync.assert_awaited_once()


# ---------------------------------------------------------------------------
# updated_user
# ---------------------------------------------------------------------------

class TestUpdatedUser:
    async def test_updates_from_subscription(self):
        svc = _make_service()
        updated = _make_remna_user_response()
        svc.remnawave.users.update_user.return_value = updated

        user = make_user(telegram_id=100)
        plan = make_plan_snapshot()
        uid = uuid4()
        sub = SubscriptionDto(
            user_remna_id=uid,
            status=SubscriptionStatus.ACTIVE,
            traffic_limit=300,
            device_limit=6,
            traffic_limit_strategy=TrafficLimitStrategy.MONTH,
            tag=None,
            internal_squads=[],
            external_squad=None,
            expire_at=_NOW + timedelta(days=30),
            url="https://panel.internal.com/sub/token123",
            plan=plan,
        )

        result = await svc.updated_user(user, uid, subscription=sub)

        svc.remnawave.users.update_user.assert_awaited_once()
        assert result.uuid == updated.uuid

    async def test_updates_from_plan(self):
        svc = _make_service()
        updated = _make_remna_user_response()
        svc.remnawave.users.update_user.return_value = updated

        user = make_user(telegram_id=100)
        plan = make_plan_snapshot()
        uid = uuid4()

        result = await svc.updated_user(user, uid, plan=plan)

        svc.remnawave.users.update_user.assert_awaited_once()
        assert result.uuid == updated.uuid

    async def test_raises_when_no_plan_or_subscription(self):
        svc = _make_service()
        user = make_user(telegram_id=100)
        uid = uuid4()

        with pytest.raises(ValueError, match="Either 'plan' or 'subscription'"):
            await svc.updated_user(user, uid)

    async def test_resets_traffic_when_flag_set(self):
        svc = _make_service()
        updated = _make_remna_user_response()
        svc.remnawave.users.update_user.return_value = updated

        user = make_user(telegram_id=100)
        plan = make_plan_snapshot()
        uid = uuid4()

        await svc.updated_user(user, uid, plan=plan, reset_traffic=True)

        svc.remnawave.users.reset_user_traffic.assert_awaited_once_with(uid)

    async def test_does_not_reset_traffic_by_default(self):
        svc = _make_service()
        updated = _make_remna_user_response()
        svc.remnawave.users.update_user.return_value = updated

        user = make_user(telegram_id=100)
        plan = make_plan_snapshot()
        uid = uuid4()

        await svc.updated_user(user, uid, plan=plan)

        svc.remnawave.users.reset_user_traffic.assert_not_awaited()

    async def test_rewrites_subscription_url(self):
        svc = _make_service(sub_public_domain="componovpn.com")
        updated = _make_remna_user_response(subscription_url="https://panel.internal.com/sub/x")
        svc.remnawave.users.update_user.return_value = updated

        user = make_user(telegram_id=100)
        plan = make_plan_snapshot()
        uid = uuid4()

        result = await svc.updated_user(user, uid, plan=plan)

        assert "componovpn.com" in result.subscription_url

    async def test_disabled_subscription_passes_disabled_status(self):
        svc = _make_service()
        updated = _make_remna_user_response()
        svc.remnawave.users.update_user.return_value = updated

        user = make_user(telegram_id=100)
        plan = make_plan_snapshot()
        uid = uuid4()
        sub = SubscriptionDto(
            user_remna_id=uid,
            status=SubscriptionStatus.DISABLED,
            traffic_limit=300,
            device_limit=6,
            traffic_limit_strategy=TrafficLimitStrategy.MONTH,
            tag=None,
            internal_squads=[],
            external_squad=None,
            expire_at=_NOW + timedelta(days=30),
            url="https://panel.internal.com/sub/token123",
            plan=plan,
        )

        await svc.updated_user(user, uid, subscription=sub)

        call_args = svc.remnawave.users.update_user.call_args
        request_dto = call_args[0][0]
        assert request_dto.status == SubscriptionStatus.DISABLED

    async def test_triggers_relay_sync(self):
        svc = _make_service()
        updated = _make_remna_user_response()
        svc.remnawave.users.update_user.return_value = updated

        user = make_user(telegram_id=100)
        plan = make_plan_snapshot()
        uid = uuid4()

        with patch.object(svc, "_trigger_relay_sync", new_callable=AsyncMock) as mock_sync:
            await svc.updated_user(user, uid, plan=plan)
            mock_sync.assert_awaited_once()


# ---------------------------------------------------------------------------
# delete_user
# ---------------------------------------------------------------------------

class TestDeleteUser:
    async def test_deletes_by_subscription_uuid(self):
        svc = _make_service()
        sub = make_subscription()
        user = make_user(telegram_id=100, subscription=sub)
        svc.remnawave.users.delete_user.return_value = DeleteUserResponseDto(isDeleted=True)

        result = await svc.delete_user(user)

        svc.remnawave.users.delete_user.assert_awaited_once_with(sub.user_remna_id)
        assert result is True

    async def test_deletes_by_telegram_lookup_when_no_subscription(self):
        svc = _make_service()
        user = make_user(telegram_id=100, subscription=None)
        found_user = _make_remna_user_response()
        svc.remnawave.users.get_users_by_telegram_id.return_value = [found_user]
        svc.remnawave.users.delete_user.return_value = DeleteUserResponseDto(isDeleted=True)

        result = await svc.delete_user(user)

        svc.remnawave.users.get_users_by_telegram_id.assert_awaited_once_with(
            telegram_id="100"
        )
        svc.remnawave.users.delete_user.assert_awaited_once_with(found_user.uuid)
        assert result is True

    async def test_returns_false_when_no_subscription_and_no_remna_users(self):
        svc = _make_service()
        user = make_user(telegram_id=100, subscription=None)
        svc.remnawave.users.get_users_by_telegram_id.return_value = []

        result = await svc.delete_user(user)

        assert result is False
        svc.remnawave.users.delete_user.assert_not_awaited()

    async def test_returns_false_when_deletion_fails(self):
        svc = _make_service()
        sub = make_subscription()
        user = make_user(telegram_id=100, subscription=sub)
        svc.remnawave.users.delete_user.return_value = DeleteUserResponseDto(isDeleted=False)

        result = await svc.delete_user(user)

        assert result is False


# ---------------------------------------------------------------------------
# get_devices_user
# ---------------------------------------------------------------------------

class TestGetDevicesUser:
    async def test_returns_devices(self):
        svc = _make_service()
        sub = make_subscription()
        user = make_user(telegram_id=100, subscription=sub)

        device = HwidDeviceDto(
            hwid="hwid-123",
            userUuid=sub.user_remna_id,
            platform="android",
            createdAt=_NOW,
            updatedAt=_NOW,
        )
        svc.remnawave.hwid.get_hwid_user.return_value = GetUserHwidDevicesResponseDto(
            total=1, devices=[device]
        )

        result = await svc.get_devices_user(user)

        assert len(result) == 1
        assert result[0].hwid == "hwid-123"

    async def test_returns_empty_when_no_subscription(self):
        svc = _make_service()
        user = make_user(telegram_id=100, subscription=None)

        result = await svc.get_devices_user(user)

        assert result == []
        svc.remnawave.hwid.get_hwid_user.assert_not_awaited()

    async def test_returns_empty_when_no_devices(self):
        svc = _make_service()
        sub = make_subscription()
        user = make_user(telegram_id=100, subscription=sub)
        svc.remnawave.hwid.get_hwid_user.return_value = GetUserHwidDevicesResponseDto(
            total=0, devices=[]
        )

        result = await svc.get_devices_user(user)

        assert result == []


# ---------------------------------------------------------------------------
# delete_device
# ---------------------------------------------------------------------------

class TestDeleteDevice:
    async def test_deletes_device_and_returns_total(self):
        svc = _make_service()
        sub = make_subscription()
        user = make_user(telegram_id=100, subscription=sub)

        svc.remnawave.hwid.delete_hwid_to_user.return_value = DeleteUserHwidDeviceResponseDto(
            total=2, devices=[]
        )

        result = await svc.delete_device(user, "hwid-123")

        svc.remnawave.hwid.delete_hwid_to_user.assert_awaited_once()
        assert result == 2

    async def test_returns_none_when_no_subscription(self):
        svc = _make_service()
        user = make_user(telegram_id=100, subscription=None)

        result = await svc.delete_device(user, "hwid-123")

        assert result is None
        svc.remnawave.hwid.delete_hwid_to_user.assert_not_awaited()


# ---------------------------------------------------------------------------
# get_user
# ---------------------------------------------------------------------------

class TestGetUser:
    async def test_returns_user_when_found(self):
        svc = _make_service()
        uid = uuid4()
        remna_user = _make_remna_user_response(uuid=uid)
        svc.remnawave.users.get_user_by_uuid.return_value = remna_user

        result = await svc.get_user(uid)

        assert result is not None
        assert result.uuid == uid

    async def test_returns_none_on_not_found(self):
        svc = _make_service()
        uid = uuid4()
        svc.remnawave.users.get_user_by_uuid.side_effect = _not_found_error()

        result = await svc.get_user(uid)

        assert result is None


# ---------------------------------------------------------------------------
# get_subscription_url
# ---------------------------------------------------------------------------

class TestGetSubscriptionUrl:
    async def test_returns_rewritten_url(self):
        svc = _make_service(sub_public_domain="componovpn.com")
        uid = uuid4()
        remna_user = _make_remna_user_response(
            uuid=uid, subscription_url="https://panel.internal.com/sub/abc"
        )
        svc.remnawave.users.get_user_by_uuid.return_value = remna_user

        result = await svc.get_subscription_url(uid)

        assert result == "https://componovpn.com/sub/abc"

    async def test_returns_none_when_user_not_found(self):
        svc = _make_service()
        uid = uuid4()
        svc.remnawave.users.get_user_by_uuid.side_effect = _not_found_error()

        result = await svc.get_subscription_url(uid)

        assert result is None


# ---------------------------------------------------------------------------
# sync_user
# ---------------------------------------------------------------------------

class TestSyncUser:
    async def test_skips_when_no_telegram_id(self):
        svc = _make_service()
        remna_user = _make_webhook_user(telegram_id=None)

        await svc.sync_user(remna_user)

        svc.user_service.get.assert_not_awaited()

    async def test_creates_new_user_and_subscription_when_not_found(self):
        svc = _make_service()
        remna_user = _make_webhook_user(telegram_id=100)

        svc.user_service.get.return_value = None
        new_user = make_user(telegram_id=100)
        svc.user_service.create_from_panel.return_value = new_user
        svc.subscription_service.get_current.return_value = None

        await svc.sync_user(remna_user, creating=True)

        svc.user_service.create_from_panel.assert_awaited_once_with(remna_user)
        svc.subscription_service.create.assert_awaited_once()

    async def test_does_not_create_user_when_creating_false(self):
        svc = _make_service()
        remna_user = _make_webhook_user(telegram_id=100)

        existing_user = make_user(telegram_id=100)
        svc.user_service.get.return_value = existing_user
        svc.subscription_service.get_current.return_value = None

        await svc.sync_user(remna_user, creating=False)

        svc.user_service.create_from_panel.assert_not_awaited()
        # Should still create subscription if not found
        svc.subscription_service.create.assert_awaited_once()

    async def test_updates_existing_subscription(self):
        svc = _make_service()
        remna_user = _make_webhook_user(telegram_id=100)

        existing_user = make_user(telegram_id=100)
        existing_sub = make_subscription()
        svc.user_service.get.return_value = existing_user
        svc.subscription_service.get_current.return_value = existing_sub

        with patch(
            "src.services.remnawave.SubscriptionService.apply_sync",
            return_value=existing_sub,
        ) as mock_apply:
            await svc.sync_user(remna_user)

            mock_apply.assert_called_once()
            svc.subscription_service.update.assert_awaited_once()

    async def test_sets_expired_status_when_expired(self):
        svc = _make_service()
        expired_at = _NOW - timedelta(days=1)
        remna_user = _make_webhook_user(telegram_id=100, expire_at=expired_at)

        existing_user = make_user(telegram_id=100)
        svc.user_service.get.return_value = existing_user
        svc.subscription_service.get_current.return_value = None

        await svc.sync_user(remna_user)

        call_args = svc.subscription_service.create.call_args
        created_sub = call_args[0][1]
        assert created_sub.status == SubscriptionStatus.EXPIRED

    async def test_rewrites_subscription_url(self):
        svc = _make_service(sub_public_domain="componovpn.com")
        remna_user = _make_webhook_user(
            telegram_id=100,
            subscription_url="https://panel.internal.com/sub/abc",
        )

        existing_user = make_user(telegram_id=100)
        svc.user_service.get.return_value = existing_user
        svc.subscription_service.get_current.return_value = None

        await svc.sync_user(remna_user)

        call_args = svc.subscription_service.create.call_args
        created_sub = call_args[0][1]
        assert "componovpn.com" in created_sub.url

    async def test_fetches_subscription_url_when_missing(self):
        svc = _make_service()
        remna_user = _make_webhook_user(telegram_id=100, subscription_url="")

        existing_user = make_user(telegram_id=100)
        svc.user_service.get.return_value = existing_user
        svc.subscription_service.get_current.return_value = None

        # Mock get_subscription_url via get_user internally
        svc.remnawave.users.get_user_by_uuid.return_value = _make_remna_user_response(
            uuid=remna_user.uuid,
            subscription_url="https://panel.internal.com/sub/fallback",
        )

        await svc.sync_user(remna_user)

        call_args = svc.subscription_service.create.call_args
        created_sub = call_args[0][1]
        assert "fallback" in created_sub.url


# ---------------------------------------------------------------------------
# handle_user_event
# ---------------------------------------------------------------------------

class TestHandleUserEvent:
    async def test_skips_when_no_telegram_id(self):
        svc = _make_service()
        remna_user = _make_webhook_user(telegram_id=None)

        await svc.handle_user_event(RemnaUserEvent.CREATED, remna_user)

        svc.user_service.get.assert_not_awaited()

    async def test_created_event_with_imported_tag_syncs(self):
        svc = _make_service()
        remna_user = _make_webhook_user(telegram_id=100, tag=IMPORTED_TAG)

        with patch.object(svc, "sync_user", new_callable=AsyncMock) as mock_sync:
            await svc.handle_user_event(RemnaUserEvent.CREATED, remna_user)
            mock_sync.assert_awaited_once_with(remna_user)

    async def test_created_event_without_imported_tag_skips_sync(self):
        svc = _make_service()
        remna_user = _make_webhook_user(telegram_id=100, tag="some-other-tag")

        with patch.object(svc, "sync_user", new_callable=AsyncMock) as mock_sync:
            await svc.handle_user_event(RemnaUserEvent.CREATED, remna_user)
            mock_sync.assert_not_awaited()

    async def test_created_event_returns_early_no_user_lookup(self):
        svc = _make_service()
        remna_user = _make_webhook_user(telegram_id=100, tag="some-tag")

        await svc.handle_user_event(RemnaUserEvent.CREATED, remna_user)

        # For CREATED event, user_service.get should NOT be called (returns early)
        svc.user_service.get.assert_not_awaited()

    async def test_returns_when_local_user_not_found(self):
        svc = _make_service()
        remna_user = _make_webhook_user(telegram_id=100)
        svc.user_service.get.return_value = None

        # Should not raise for non-CREATED events
        await svc.handle_user_event(RemnaUserEvent.MODIFIED, remna_user)

    async def test_modified_event_syncs_without_creating(self):
        svc = _make_service()
        remna_user = _make_webhook_user(telegram_id=100)
        user = make_user(telegram_id=100)
        svc.user_service.get.return_value = user

        with patch.object(svc, "sync_user", new_callable=AsyncMock) as mock_sync:
            await svc.handle_user_event(RemnaUserEvent.MODIFIED, remna_user)
            mock_sync.assert_awaited_once_with(remna_user, creating=False)

    async def test_deleted_event_dispatches_delete_task(self):
        svc = _make_service()
        remna_user = _make_webhook_user(telegram_id=100)
        user = make_user(telegram_id=100)
        svc.user_service.get.return_value = user

        with patch(
            "src.infrastructure.taskiq.tasks.subscriptions.delete_current_subscription_task"
        ) as mock_task:
            mock_task.kiq = AsyncMock()
            await svc.handle_user_event(RemnaUserEvent.DELETED, remna_user)
            mock_task.kiq.assert_awaited_once_with(remna_user)

    async def test_status_change_events_dispatch_update_task(self):
        # Map events to valid UserWebhookDto status values
        event_status_map = {
            RemnaUserEvent.REVOKED: "DISABLED",
            RemnaUserEvent.ENABLED: "ACTIVE",
            RemnaUserEvent.DISABLED: "DISABLED",
            RemnaUserEvent.LIMITED: "LIMITED",
            RemnaUserEvent.EXPIRED: "EXPIRED",
        }
        for event, status_str in event_status_map.items():
            svc = _make_service()
            remna_user = _make_webhook_user(telegram_id=100, status=status_str)
            user = make_user(telegram_id=100)
            svc.user_service.get.return_value = user

            with patch(
                "src.infrastructure.taskiq.tasks.subscriptions.update_status_current_subscription_task"
            ) as mock_task, patch(
                "src.infrastructure.taskiq.tasks.notifications.send_subscription_limited_notification_task"
            ) as mock_limited, patch(
                "src.infrastructure.taskiq.tasks.notifications.send_subscription_expire_notification_task"
            ) as mock_expire:
                mock_task.kiq = AsyncMock()
                mock_limited.kiq = AsyncMock()
                mock_expire.kiq = AsyncMock()
                await svc.handle_user_event(event, remna_user)
                mock_task.kiq.assert_awaited_once()

    async def test_limited_event_sends_limited_notification(self):
        svc = _make_service()
        remna_user = _make_webhook_user(telegram_id=100, status="LIMITED")
        user = make_user(telegram_id=100)
        svc.user_service.get.return_value = user

        with patch(
            "src.infrastructure.taskiq.tasks.subscriptions.update_status_current_subscription_task"
        ) as mock_update, patch(
            "src.infrastructure.taskiq.tasks.notifications.send_subscription_limited_notification_task"
        ) as mock_limited:
            mock_update.kiq = AsyncMock()
            mock_limited.kiq = AsyncMock()
            await svc.handle_user_event(RemnaUserEvent.LIMITED, remna_user)
            mock_limited.kiq.assert_awaited_once()

    async def test_expired_event_sends_expire_notification(self):
        svc = _make_service()
        # Expire recently (within 3 days)
        remna_user = _make_webhook_user(
            telegram_id=100,
            status="EXPIRED",
            expire_at=_NOW - timedelta(hours=1),
        )
        user = make_user(telegram_id=100)
        svc.user_service.get.return_value = user

        with patch(
            "src.infrastructure.taskiq.tasks.subscriptions.update_status_current_subscription_task"
        ) as mock_update, patch(
            "src.infrastructure.taskiq.tasks.notifications.send_subscription_expire_notification_task"
        ) as mock_expire:
            mock_update.kiq = AsyncMock()
            mock_expire.kiq = AsyncMock()
            await svc.handle_user_event(RemnaUserEvent.EXPIRED, remna_user)
            mock_expire.kiq.assert_awaited_once()
            # Should be called with EXPIRED type
            call_kwargs = mock_expire.kiq.call_args[1]
            assert call_kwargs["ntf_type"] == UserNotificationType.EXPIRED

    async def test_expired_event_skips_notification_when_expired_long_ago(self):
        svc = _make_service()
        # Expired more than 3 days ago
        remna_user = _make_webhook_user(
            telegram_id=100,
            status="EXPIRED",
            expire_at=_NOW - timedelta(days=5),
        )
        user = make_user(telegram_id=100)
        svc.user_service.get.return_value = user

        with patch(
            "src.infrastructure.taskiq.tasks.subscriptions.update_status_current_subscription_task"
        ) as mock_update, patch(
            "src.infrastructure.taskiq.tasks.notifications.send_subscription_expire_notification_task"
        ) as mock_expire:
            mock_update.kiq = AsyncMock()
            mock_expire.kiq = AsyncMock()
            await svc.handle_user_event(RemnaUserEvent.EXPIRED, remna_user)
            mock_expire.kiq.assert_not_awaited()

    async def test_first_connected_event_sends_system_notification(self):
        svc = _make_service()
        remna_user = _make_webhook_user(telegram_id=100)
        user = make_user(telegram_id=100)
        svc.user_service.get.return_value = user

        await svc.handle_user_event(RemnaUserEvent.FIRST_CONNECTED, remna_user)

        svc.notification_service.system_notify.assert_awaited_once()
        call_kwargs = svc.notification_service.system_notify.call_args[1]
        assert call_kwargs["ntf_type"] == SystemNotificationType.USER_FIRST_CONNECTED

    async def test_expiration_warning_events_send_notifications(self):
        event_map = {
            RemnaUserEvent.EXPIRES_IN_72_HOURS: UserNotificationType.EXPIRES_IN_3_DAYS,
            RemnaUserEvent.EXPIRES_IN_48_HOURS: UserNotificationType.EXPIRES_IN_2_DAYS,
            RemnaUserEvent.EXPIRES_IN_24_HOURS: UserNotificationType.EXPIRES_IN_1_DAYS,
            RemnaUserEvent.EXPIRED_24_HOURS_AGO: UserNotificationType.EXPIRED_1_DAY_AGO,
        }
        for event, expected_type in event_map.items():
            svc = _make_service()
            remna_user = _make_webhook_user(telegram_id=100)
            user = make_user(telegram_id=100)
            svc.user_service.get.return_value = user

            with patch(
                "src.infrastructure.taskiq.tasks.notifications.send_subscription_expire_notification_task"
            ) as mock_expire:
                mock_expire.kiq = AsyncMock()
                await svc.handle_user_event(event, remna_user)
                mock_expire.kiq.assert_awaited_once()
                call_kwargs = mock_expire.kiq.call_args[1]
                assert call_kwargs["ntf_type"] == expected_type, (
                    f"Event {event} should map to {expected_type}"
                )

    async def test_unhandled_event_does_not_raise(self):
        svc = _make_service()
        remna_user = _make_webhook_user(telegram_id=100)
        user = make_user(telegram_id=100)
        svc.user_service.get.return_value = user

        # Should not raise for unknown event
        await svc.handle_user_event("user.unknown_event", remna_user)


# ---------------------------------------------------------------------------
# handle_device_event
# ---------------------------------------------------------------------------

class TestHandleDeviceEvent:
    def _make_device(self) -> MagicMock:
        device = MagicMock()
        device.hwid = "hwid-abc"
        device.platform = "android"
        device.device_model = "Pixel 6"
        device.os_version = "14"
        device.user_agent = "v2rayNG/1.8"
        return device

    async def test_skips_when_no_telegram_id(self):
        svc = _make_service()
        remna_user = _make_webhook_user(telegram_id=None)
        device = self._make_device()

        await svc.handle_device_event(
            RemnaUserHwidDevicesEvent.ADDED, remna_user, device
        )

        svc.user_service.get.assert_not_awaited()

    async def test_returns_when_local_user_not_found(self):
        svc = _make_service()
        remna_user = _make_webhook_user(telegram_id=100)
        svc.user_service.get.return_value = None
        device = self._make_device()

        await svc.handle_device_event(
            RemnaUserHwidDevicesEvent.ADDED, remna_user, device
        )

        svc.notification_service.system_notify.assert_not_awaited()

    async def test_added_event_sends_notification(self):
        svc = _make_service()
        remna_user = _make_webhook_user(telegram_id=100)
        user = make_user(telegram_id=100)
        svc.user_service.get.return_value = user
        device = self._make_device()

        await svc.handle_device_event(
            RemnaUserHwidDevicesEvent.ADDED, remna_user, device
        )

        svc.notification_service.system_notify.assert_awaited_once()
        call_kwargs = svc.notification_service.system_notify.call_args[1]
        assert call_kwargs["ntf_type"] == SystemNotificationType.USER_HWID
        payload = call_kwargs["payload"]
        assert payload.i18n_key == "ntf-event-user-hwid-added"

    async def test_deleted_event_sends_notification(self):
        svc = _make_service()
        remna_user = _make_webhook_user(telegram_id=100)
        user = make_user(telegram_id=100)
        svc.user_service.get.return_value = user
        device = self._make_device()

        await svc.handle_device_event(
            RemnaUserHwidDevicesEvent.DELETED, remna_user, device
        )

        svc.notification_service.system_notify.assert_awaited_once()
        call_kwargs = svc.notification_service.system_notify.call_args[1]
        payload = call_kwargs["payload"]
        assert payload.i18n_key == "ntf-event-user-hwid-deleted"

    async def test_unhandled_device_event_does_not_notify(self):
        svc = _make_service()
        remna_user = _make_webhook_user(telegram_id=100)
        user = make_user(telegram_id=100)
        svc.user_service.get.return_value = user
        device = self._make_device()

        await svc.handle_device_event("user_hwid_devices.unknown", remna_user, device)

        svc.notification_service.system_notify.assert_not_awaited()


# ---------------------------------------------------------------------------
# handle_node_event
# ---------------------------------------------------------------------------

class TestHandleNodeEvent:
    def _make_node(self) -> NodeDto:
        return NodeDto(
            uuid=uuid4(),
            name="node-de-01",
            address="1.2.3.4",
            port=443,
            is_connected=True,
            is_connecting=False,
            is_disabled=False,
            last_status_change=_NOW,
            last_status_message="OK",
            xray_uptime="24h",
            is_traffic_tracking_active=True,
            traffic_limit_bytes=1000 * 1024**3,
            traffic_used_bytes=500 * 1024**3,
            view_position=1,
            country_code="DE",
            consumption_multiplier=1,
            created_at=_NOW,
            updated_at=_NOW,
        )

    async def test_connection_lost_sends_notification(self):
        svc = _make_service()
        node = self._make_node()

        await svc.handle_node_event(RemnaNodeEvent.CONNECTION_LOST, node)

        svc.notification_service.system_notify.assert_awaited_once()
        call_kwargs = svc.notification_service.system_notify.call_args[1]
        assert call_kwargs["ntf_type"] == SystemNotificationType.NODE_STATUS
        assert call_kwargs["payload"].i18n_key == "ntf-event-node-connection-lost"

    async def test_connection_restored_sends_notification(self):
        svc = _make_service()
        node = self._make_node()

        await svc.handle_node_event(RemnaNodeEvent.CONNECTION_RESTORED, node)

        svc.notification_service.system_notify.assert_awaited_once()
        call_kwargs = svc.notification_service.system_notify.call_args[1]
        assert call_kwargs["payload"].i18n_key == "ntf-event-node-connection-restored"

    async def test_traffic_notify_sends_notification(self):
        svc = _make_service()
        node = self._make_node()

        await svc.handle_node_event(RemnaNodeEvent.TRAFFIC_NOTIFY, node)

        svc.notification_service.system_notify.assert_awaited_once()
        call_kwargs = svc.notification_service.system_notify.call_args[1]
        assert call_kwargs["payload"].i18n_key == "ntf-event-node-traffic"

    async def test_unhandled_node_event_does_not_notify(self):
        svc = _make_service()
        node = self._make_node()

        await svc.handle_node_event("node.unknown_event", node)

        svc.notification_service.system_notify.assert_not_awaited()

    async def test_node_without_last_status_change(self):
        svc = _make_service()
        node = self._make_node()
        node.last_status_change = None
        node.last_status_message = None

        await svc.handle_node_event(RemnaNodeEvent.CONNECTION_LOST, node)

        svc.notification_service.system_notify.assert_awaited_once()
        call_kwargs = svc.notification_service.system_notify.call_args[1]
        i18n_kwargs = call_kwargs["payload"].i18n_kwargs
        assert i18n_kwargs["last_status_change"] is False
        assert i18n_kwargs["last_status_message"] is False
