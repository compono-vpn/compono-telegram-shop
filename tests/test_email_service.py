"""Tests for EmailService — verifies Resend API calls for OTP, trial, and purchase emails."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.services.email import EmailService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**overrides) -> MagicMock:
    config = MagicMock()
    config.resend_api_key = overrides.get("resend_api_key", "re_test_key")
    config.resend_from_email = overrides.get("resend_from_email", "noreply@compono.it.com")
    config.resend_api_base = overrides.get("resend_api_base", "https://api.resend.com")
    config.ios_download_url = overrides.get("ios_download_url", "https://apps.apple.com/streisand")
    config.android_download_url = overrides.get("android_download_url", "https://play.google.com/v2rayng")
    config.desktop_download_url = overrides.get("desktop_download_url", "https://hiddify.com")
    return config


def _make_service(**config_overrides) -> EmailService:
    return EmailService(config=_make_config(**config_overrides))


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> httpx.Response:
    resp = httpx.Response(status_code=status_code, json=json_data or {"id": "email_123"})
    return resp


# ---------------------------------------------------------------------------
# send_otp_code
# ---------------------------------------------------------------------------

class TestSendOtpCode:
    async def test_sends_otp_email(self):
        svc = _make_service()

        with patch("src.services.email.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = _mock_response()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await svc.send_otp_code("user@example.com", "123456")

            mock_client.post.assert_awaited_once()
            call_kwargs = mock_client.post.call_args
            assert call_kwargs[0][0] == "https://api.resend.com/emails"
            json_body = call_kwargs[1]["json"]
            assert json_body["to"] == ["user@example.com"]
            assert json_body["from"] == "noreply@compono.it.com"
            assert "123456" in json_body["html"]

    async def test_skips_when_api_key_empty(self):
        svc = _make_service(resend_api_key="")

        with patch("src.services.email.httpx.AsyncClient") as mock_client_cls:
            await svc.send_otp_code("user@example.com", "123456")
            mock_client_cls.assert_not_called()

    async def test_skips_when_api_key_none(self):
        svc = _make_service(resend_api_key=None)

        with patch("src.services.email.httpx.AsyncClient") as mock_client_cls:
            await svc.send_otp_code("user@example.com", "123456")
            mock_client_cls.assert_not_called()

    async def test_handles_http_error_gracefully(self):
        svc = _make_service()

        with patch("src.services.email.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            error_resp = httpx.Response(status_code=500, request=httpx.Request("POST", "https://api.resend.com/emails"))
            mock_client.post.return_value = error_resp
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            # Should not raise — error is caught internally
            await svc.send_otp_code("user@example.com", "123456")

    async def test_handles_network_error_gracefully(self):
        svc = _make_service()

        with patch("src.services.email.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ConnectError("Connection refused")
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await svc.send_otp_code("user@example.com", "123456")


# ---------------------------------------------------------------------------
# send_trial_bot_link
# ---------------------------------------------------------------------------

class TestSendTrialBotLink:
    async def test_sends_trial_email(self):
        svc = _make_service()

        with patch("src.services.email.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = _mock_response()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await svc.send_trial_bot_link("user@example.com", "https://t.me/compono_bot?start=abc")

            mock_client.post.assert_awaited_once()
            call_kwargs = mock_client.post.call_args
            json_body = call_kwargs[1]["json"]
            assert json_body["to"] == ["user@example.com"]
            assert "compono_bot?start=abc" in json_body["html"]

    async def test_skips_when_api_key_empty(self):
        svc = _make_service(resend_api_key="")

        with patch("src.services.email.httpx.AsyncClient") as mock_client_cls:
            await svc.send_trial_bot_link("user@example.com", "https://t.me/bot")
            mock_client_cls.assert_not_called()

    async def test_handles_exception_gracefully(self):
        svc = _make_service()

        with patch("src.services.email.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("Unexpected error")
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await svc.send_trial_bot_link("user@example.com", "https://t.me/bot")


# ---------------------------------------------------------------------------
# send_purchase_subscription
# ---------------------------------------------------------------------------

class TestSendPurchaseSubscription:
    async def test_sends_purchase_email_without_bot_link(self):
        svc = _make_service()

        with patch("src.services.email.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = _mock_response()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await svc.send_purchase_subscription(
                to_email="user@example.com",
                subscription_url="https://panel.example.com/sub/xyz",
                plan_name="Pro",
            )

            mock_client.post.assert_awaited_once()
            call_kwargs = mock_client.post.call_args
            json_body = call_kwargs[1]["json"]
            assert json_body["to"] == ["user@example.com"]
            assert "Pro" in json_body["subject"]
            assert "https://panel.example.com/sub/xyz" in json_body["html"]
            # No bot link section
            assert "Открыть в Telegram" not in json_body["html"]

    async def test_sends_purchase_email_with_bot_link(self):
        svc = _make_service()

        with patch("src.services.email.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = _mock_response()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await svc.send_purchase_subscription(
                to_email="user@example.com",
                subscription_url="https://panel.example.com/sub/xyz",
                plan_name="Pro",
                bot_link="https://t.me/compono_bot?start=claim_abc",
            )

            call_kwargs = mock_client.post.call_args
            json_body = call_kwargs[1]["json"]
            assert "Открыть в Telegram" in json_body["html"]
            assert "compono_bot?start=claim_abc" in json_body["html"]

    async def test_includes_download_links(self):
        svc = _make_service()

        with patch("src.services.email.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = _mock_response()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await svc.send_purchase_subscription(
                to_email="user@example.com",
                subscription_url="https://panel.example.com/sub/xyz",
                plan_name="Pro",
            )

            call_kwargs = mock_client.post.call_args
            html = call_kwargs[1]["json"]["html"]
            assert "https://apps.apple.com/streisand" in html
            assert "https://play.google.com/v2rayng" in html
            assert "https://hiddify.com" in html

    async def test_skips_when_api_key_empty(self):
        svc = _make_service(resend_api_key="")

        with patch("src.services.email.httpx.AsyncClient") as mock_client_cls:
            await svc.send_purchase_subscription(
                to_email="user@example.com",
                subscription_url="https://panel.example.com/sub/xyz",
                plan_name="Pro",
            )
            mock_client_cls.assert_not_called()

    async def test_handles_exception_gracefully(self):
        svc = _make_service()

        with patch("src.services.email.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("Boom")
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await svc.send_purchase_subscription(
                to_email="user@example.com",
                subscription_url="url",
                plan_name="Pro",
            )

    async def test_uses_correct_authorization_header(self):
        svc = _make_service(resend_api_key="re_my_secret_key")

        with patch("src.services.email.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = _mock_response()
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await svc.send_purchase_subscription(
                to_email="user@example.com",
                subscription_url="url",
                plan_name="Pro",
            )

            call_kwargs = mock_client.post.call_args
            assert call_kwargs[1]["headers"]["Authorization"] == "Bearer re_my_secret_key"
