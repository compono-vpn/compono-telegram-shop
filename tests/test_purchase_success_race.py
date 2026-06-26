"""Race coverage for the post-purchase getters.

Subscription creation is async (Kafka), so billing can return None for a moment
right after payment. The success/connect screens must poll instead of hard-failing
with "no active subscription after purchase" (which broke the success screen and
left paying users without their connect link).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from src.bot.routers.subscription.getters import _await_billing_subscription


async def test_returns_sub_once_billing_commits():
    billing = MagicMock()
    sub = MagicMock()
    billing.get_current_subscription = AsyncMock(side_effect=[None, None, sub])
    with patch("src.bot.routers.subscription.getters.asyncio.sleep", new=AsyncMock()):
        result = await _await_billing_subscription(billing, 242178867, attempts=6, delay=0.0)
    assert result is sub
    assert billing.get_current_subscription.await_count == 3


async def test_returns_immediately_when_present():
    billing = MagicMock()
    sub = MagicMock()
    billing.get_current_subscription = AsyncMock(return_value=sub)
    with patch("src.bot.routers.subscription.getters.asyncio.sleep", new=AsyncMock()) as sleep:
        result = await _await_billing_subscription(billing, 1, attempts=6)
    assert result is sub
    assert billing.get_current_subscription.await_count == 1
    sleep.assert_not_awaited()


async def test_returns_none_after_exhausting_attempts():
    billing = MagicMock()
    billing.get_current_subscription = AsyncMock(return_value=None)
    with patch("src.bot.routers.subscription.getters.asyncio.sleep", new=AsyncMock()):
        result = await _await_billing_subscription(billing, 1, attempts=4, delay=0.0)
    assert result is None
    assert billing.get_current_subscription.await_count == 4
