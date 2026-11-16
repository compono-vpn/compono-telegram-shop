from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.enums import DedicatedIpCountry
from src.services import dedicated_ip
from src.services.dedicated_ip import (
    flag_release_after_expiry,
    is_active_ultra_billing_subscription,
    offer_country_choice,
)


def _sub(status="ACTIVE", days=10, tag="ULTRA", trial=False):
    return SimpleNamespace(
        Status=status,
        IsTrial=trial,
        ExpireAt=datetime.now(timezone.utc) + timedelta(days=days),
        Plan=SimpleNamespace(tag=tag),
    )


def _billing(answer, current):
    billing = MagicMock()
    reminder = SimpleNamespace(dedup_key="v1", answer=answer)
    billing.list_user_reminders = AsyncMock(return_value=[reminder] if answer else [])
    billing.get_current_subscription = AsyncMock(return_value=current)
    billing.claim_user_reminder = AsyncMock(return_value=True)
    return billing


class TestActiveUltra:
    def test_active(self):
        assert is_active_ultra_billing_subscription(_sub())

    def test_expired_status(self):
        assert not is_active_ultra_billing_subscription(_sub(status="EXPIRED"))

    def test_past_expiry(self):
        assert not is_active_ultra_billing_subscription(_sub(days=-1))

    def test_other_plan(self):
        assert not is_active_ultra_billing_subscription(_sub(tag="MAX"))


class TestReleaseAfterExpiry:
    async def test_expired_ultra_with_ip_posts_remove_card(self):
        billing = _billing("NL", _sub(status="EXPIRED", days=-1))
        with patch.object(dedicated_ip, "post_ops_event", new=AsyncMock(return_value=True)) as post:
            assert await flag_release_after_expiry(
                telegram_id=42, billing=billing, config=MagicMock()
            )
        kwargs = post.await_args.kwargs
        assert kwargs["details"]["command"] == "tools/compono-dedicated-ip.sh remove 42"
        assert kwargs["key"] == "compono-ultra-ip:42"

    async def test_no_country_no_card(self):
        billing = _billing(None, _sub(status="EXPIRED", days=-1))
        with patch.object(dedicated_ip, "post_ops_event", new=AsyncMock()) as post:
            assert not await flag_release_after_expiry(
                telegram_id=42, billing=billing, config=MagicMock()
            )
        post.assert_not_awaited()

    async def test_already_renewed_no_card(self):
        billing = _billing("SE", _sub())
        with patch.object(dedicated_ip, "post_ops_event", new=AsyncMock()) as post:
            assert not await flag_release_after_expiry(
                telegram_id=42, billing=billing, config=MagicMock()
            )
        post.assert_not_awaited()


class TestRepeatPayment:
    async def test_saved_country_posts_check_card_and_no_prompt(self):
        billing = _billing("SE", _sub())
        ntf = MagicMock(notify_user=AsyncMock())
        with patch.object(dedicated_ip, "post_ops_event", new=AsyncMock(return_value=True)) as post:
            sent = await offer_country_choice(
                user=SimpleNamespace(telegram_id=7),
                plan_tag="ULTRA",
                billing=billing,
                notification_service=ntf,
                config=MagicMock(),
            )
        assert sent is False
        ntf.notify_user.assert_not_called()
        command = post.await_args.kwargs["details"]["command"]
        assert "verify 7" in command and f"add 7 {DedicatedIpCountry.SE.value}" in command
