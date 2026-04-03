"""Tests for WebhookService — verifies webhook setup, deletion, and error detection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.enums import Locale
from src.services.webhook import WebhookService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service() -> tuple[WebhookService, MagicMock, AsyncMock, AsyncMock]:
    """Return (service, config, bot, redis_repository)."""
    config = MagicMock()
    config.bot.safe_webhook_url.return_value = "https://bot.example.com/webhook"
    config.bot.webhook_url.return_value.get_secret_value.return_value = "https://bot.example.com/webhook?secret=abc"
    config.bot.allowed_updates = ["message", "callback_query"]
    config.bot.drop_pending_updates = True
    config.bot.secret_token.get_secret_value.return_value = "secret123"
    config.bot.reset_webhook = False
    config.domain = "bot.example.com"

    bot = AsyncMock()
    bot.id = 12345

    redis_client = AsyncMock()
    redis_repository = AsyncMock()
    translator_hub = MagicMock()

    svc = WebhookService(
        config=config,
        bot=bot,
        redis_client=redis_client,
        redis_repository=redis_repository,
        translator_hub=translator_hub,
    )
    return svc, config, bot, redis_repository


# ---------------------------------------------------------------------------
# setup()
# ---------------------------------------------------------------------------

class TestSetup:
    @patch("src.services.webhook.get_webhook_hash", return_value="hash_abc")
    async def test_skips_setup_when_already_configured(self, mock_hash):
        svc, config, bot, redis_repo = _make_service()
        config.bot.reset_webhook = False
        redis_repo.exists.return_value = True

        webhook_info = MagicMock()
        bot.get_webhook_info.return_value = webhook_info

        result = await svc.setup(allowed_updates=["message"])

        assert result is webhook_info
        # Should not call bot() to set webhook
        bot.assert_not_awaited()
        bot.get_webhook_info.assert_awaited_once()

    @patch("src.services.webhook.get_webhook_hash", return_value="hash_abc")
    async def test_sets_webhook_when_not_configured(self, mock_hash):
        svc, config, bot, redis_repo = _make_service()
        config.bot.reset_webhook = False
        redis_repo.exists.return_value = False  # Not yet set

        bot.return_value = True  # bot(webhook) succeeds
        redis_repo.client.keys.return_value = []

        webhook_info = MagicMock()
        bot.get_webhook_info.return_value = webhook_info

        result = await svc.setup(allowed_updates=["message"])

        assert result is webhook_info
        bot.assert_awaited_once()  # Called with SetWebhook
        redis_repo.set.assert_awaited_once()

    @patch("src.services.webhook.get_webhook_hash", return_value="hash_abc")
    async def test_raises_when_set_webhook_fails(self, mock_hash):
        svc, config, bot, redis_repo = _make_service()
        config.bot.reset_webhook = False
        redis_repo.exists.return_value = False

        bot.return_value = False  # bot(webhook) fails

        with pytest.raises(RuntimeError, match="Failed to set bot webhook"):
            await svc.setup(allowed_updates=["message"])

    @patch("src.services.webhook.get_webhook_hash", return_value="hash_abc")
    async def test_forces_setup_when_reset_webhook_enabled(self, mock_hash):
        svc, config, bot, redis_repo = _make_service()
        config.bot.reset_webhook = True
        redis_repo.exists.return_value = True  # Already configured, but reset=True

        bot.return_value = True
        redis_repo.client.keys.return_value = []

        webhook_info = MagicMock()
        bot.get_webhook_info.return_value = webhook_info

        result = await svc.setup(allowed_updates=["message"])

        assert result is webhook_info
        bot.assert_awaited_once()  # Still sets webhook

    @patch("src.services.webhook.get_webhook_hash", return_value="hash_abc")
    async def test_clears_old_keys_before_setting_new(self, mock_hash):
        svc, config, bot, redis_repo = _make_service()
        config.bot.reset_webhook = False
        redis_repo.exists.return_value = False

        bot.return_value = True
        old_keys = [b"webhook_lock:12345:old_hash"]
        redis_repo.client.keys.return_value = old_keys

        webhook_info = MagicMock()
        bot.get_webhook_info.return_value = webhook_info

        await svc.setup(allowed_updates=["message"])

        redis_repo.client.delete.assert_awaited_once_with(*old_keys)


# ---------------------------------------------------------------------------
# delete()
# ---------------------------------------------------------------------------

class TestDelete:
    async def test_deletes_webhook_when_reset_enabled(self):
        svc, config, bot, redis_repo = _make_service()
        config.bot.reset_webhook = True
        bot.delete_webhook.return_value = True
        redis_repo.client.keys.return_value = []

        await svc.delete()

        bot.delete_webhook.assert_awaited_once()

    async def test_skips_delete_when_reset_disabled(self):
        svc, config, bot, redis_repo = _make_service()
        config.bot.reset_webhook = False

        await svc.delete()

        bot.delete_webhook.assert_not_awaited()

    async def test_logs_error_when_delete_fails(self):
        svc, config, bot, redis_repo = _make_service()
        config.bot.reset_webhook = True
        bot.delete_webhook.return_value = False

        await svc.delete()

        bot.delete_webhook.assert_awaited_once()
        # No clear should happen on failure
        redis_repo.client.keys.assert_not_awaited()


# ---------------------------------------------------------------------------
# has_error()
# ---------------------------------------------------------------------------

class TestHasError:
    def test_returns_false_when_no_error_message(self):
        svc, *_ = _make_service()
        webhook_info = MagicMock()
        webhook_info.last_error_message = None
        webhook_info.last_error_date = None

        assert svc.has_error(webhook_info) is False

    def test_returns_false_when_no_error_date(self):
        svc, *_ = _make_service()
        webhook_info = MagicMock()
        webhook_info.last_error_message = "Some error"
        webhook_info.last_error_date = None

        assert svc.has_error(webhook_info) is False

    @patch("src.services.webhook.datetime_now")
    def test_returns_true_for_recent_error(self, mock_now):
        svc, *_ = _make_service()
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_now.return_value = now

        webhook_info = MagicMock()
        webhook_info.last_error_message = "Connection timeout"
        webhook_info.last_error_date = now - timedelta(seconds=2)  # 2 seconds ago

        assert svc.has_error(webhook_info) is True

    @patch("src.services.webhook.datetime_now")
    def test_returns_false_for_old_error(self, mock_now):
        svc, *_ = _make_service()
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_now.return_value = now

        webhook_info = MagicMock()
        webhook_info.last_error_message = "Connection timeout"
        webhook_info.last_error_date = now - timedelta(seconds=10)  # 10 seconds ago

        assert svc.has_error(webhook_info) is False

    @patch("src.services.webhook.datetime_now")
    def test_returns_true_for_error_exactly_at_tolerance(self, mock_now):
        svc, *_ = _make_service()
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_now.return_value = now

        webhook_info = MagicMock()
        webhook_info.last_error_message = "Error"
        webhook_info.last_error_date = now - timedelta(seconds=5)  # Exactly at tolerance

        assert svc.has_error(webhook_info) is True


# ---------------------------------------------------------------------------
# _is_new_error()
# ---------------------------------------------------------------------------

class TestIsNewError:
    @patch("src.services.webhook.datetime_now")
    def test_new_error_within_tolerance(self, mock_now):
        svc, *_ = _make_service()
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_now.return_value = now

        assert svc._is_new_error(error_time=now - timedelta(seconds=3)) is True

    @patch("src.services.webhook.datetime_now")
    def test_old_error_outside_tolerance(self, mock_now):
        svc, *_ = _make_service()
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_now.return_value = now

        assert svc._is_new_error(error_time=now - timedelta(seconds=60)) is False

    @patch("src.services.webhook.datetime_now")
    def test_custom_tolerance(self, mock_now):
        svc, *_ = _make_service()
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_now.return_value = now

        # 8 seconds ago, tolerance=10 -> within tolerance
        assert svc._is_new_error(error_time=now - timedelta(seconds=8), tolerance=10) is True
        # 8 seconds ago, tolerance=3 -> outside tolerance
        assert svc._is_new_error(error_time=now - timedelta(seconds=8), tolerance=3) is False
