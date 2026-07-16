"""Tests for on_calls_beta handler -- Calls (beta) provisioning flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.routers.menu.handlers import on_calls_beta
from src.core.constants import USER_KEY
from src.core.enums import MediaType
from src.infrastructure.billing.client import BillingClientError, CallsNotEntitledError
from src.infrastructure.billing.models import (
    BillingAmneziaWGConfig,
    BillingCallsBundle,
    BillingHysteria2Config,
)
from tests.conftest import make_dialog_manager, make_user, unwrap_inject


def _make_bundle() -> BillingCallsBundle:
    return BillingCallsBundle(
        amneziawg=BillingAmneziaWGConfig(
            private_key="aGVsbG8td29ybGQ=",
            address="10.8.0.2/32",
            dns="1.1.1.1",
            mtu=1280,
            server_public_key="cHVibGljLWtleQ==",
            endpoint="calls.componovpn.com:51820",
            allowed_ips="0.0.0.0/0, ::/0",
            persistent_keepalive=25,
            jc=4,
            jmin=40,
            jmax=70,
            s1=30,
            s2=25,
            h1=1234567891,
            h2=1234567892,
            h3=1234567893,
            h4=1234567894,
        ),
        hysteria2=BillingHysteria2Config(
            uri="hysteria2://auth@calls.componovpn.com:8443/?sni=calls.componovpn.com",
            server="calls.componovpn.com:8443",
            auth="auth",
            sni="calls.componovpn.com",
            insecure=False,
        ),
    )


def _setup(*, provision_side_effect=None, bundle: BillingCallsBundle | None = None) -> tuple:
    user = make_user(telegram_id=450987966, name="Анастасия")

    billing = AsyncMock()
    if provision_side_effect:
        billing.provision_calls.side_effect = provision_side_effect
    else:
        billing.provision_calls.return_value = bundle or _make_bundle()

    notification_service = AsyncMock()

    dm = make_dialog_manager()
    dm.middleware_data[USER_KEY] = user

    callback = MagicMock()
    widget = MagicMock()

    return callback, widget, dm, billing, notification_service


class TestOnCallsBeta:

    async def test_success_sends_conf_and_two_qr_codes(self):
        callback, widget, dm, billing, ntf = _setup()
        raw_fn = unwrap_inject(on_calls_beta)

        await raw_fn(callback, widget, dm, billing, ntf)

        billing.provision_calls.assert_called_once_with(450987966)
        assert ntf.notify_user.call_count == 3

        doc_payload = ntf.notify_user.call_args_list[0][1]["payload"]
        assert doc_payload.i18n_key == "msg-calls-beta"
        assert doc_payload.media_type == MediaType.DOCUMENT
        assert doc_payload.media.filename == "compono-calls.conf"

        amneziawg_qr_payload = ntf.notify_user.call_args_list[1][1]["payload"]
        assert amneziawg_qr_payload.media_type == MediaType.PHOTO

        hysteria2_qr_payload = ntf.notify_user.call_args_list[2][1]["payload"]
        assert hysteria2_qr_payload.media_type == MediaType.PHOTO

    async def test_not_entitled_sends_friendly_message(self):
        callback, widget, dm, billing, ntf = _setup(
            provision_side_effect=CallsNotEntitledError(403, "not entitled"),
        )
        raw_fn = unwrap_inject(on_calls_beta)

        await raw_fn(callback, widget, dm, billing, ntf)

        ntf.notify_user.assert_called_once()
        payload = ntf.notify_user.call_args[1]["payload"]
        assert payload.i18n_key == "ntf-calls-beta-not-entitled"

    async def test_other_billing_error_propagates(self):
        callback, widget, dm, billing, ntf = _setup(
            provision_side_effect=BillingClientError(500, "database connection refused"),
        )
        raw_fn = unwrap_inject(on_calls_beta)

        with pytest.raises(BillingClientError):
            await raw_fn(callback, widget, dm, billing, ntf)

        ntf.notify_user.assert_not_called()
